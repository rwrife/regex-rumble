"""Minimal MCP (Model Context Protocol) server for regex-rumble.

Exposes two tools so coding agents can fuzz their regexes before commit:

* ``evaluate`` — run a pattern against ally/enemy example lists, returning
  per-example pass/fail plus a ReDoS warning when the pattern smells risky.
* ``attack`` — let the sensei generate adversarial examples and report which
  ones the pattern misclassifies.

Transport is stdio with newline-delimited JSON-RPC 2.0, the lowest-common-
denominator MCP wire format. No third-party SDK required — we implement
just the handshake + tool surface we actually use. That keeps the dependency
surface small and the tests trivial to drive in-process.

This is intentionally a thin slice of MCP: ``initialize``, ``tools/list``,
``tools/call``, plus ``ping``. It's enough for any agent client (Claude,
Cursor, OpenAI Agents SDK, etc.) that speaks the standard tool surface.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, BinaryIO, TextIO

from . import __version__
from .engine import evaluate as _engine_evaluate
from .sensei import run_attack as _run_attack

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "regex-rumble"


# ---- JSON-RPC plumbing -----------------------------------------------------


class JsonRpcError(Exception):
    """Wraps a JSON-RPC error so handlers can raise instead of returning."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


# ---- tool definitions ------------------------------------------------------


@dataclass(frozen=True)
class Tool:
    """One MCP tool the server exposes."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], dict[str, Any]]

    def descriptor(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def _as_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        # Accept newline-blob, matches the TUI ergonomics.
        return [line for line in value.splitlines() if line.strip()]
    if isinstance(value, list) and all(isinstance(x, str) for x in value):
        return list(value)
    raise JsonRpcError(
        INVALID_PARAMS,
        f"`{field_name}` must be a string or array of strings",
    )


def _require_str(args: dict[str, Any], name: str) -> str:
    val = args.get(name)
    if not isinstance(val, str):
        raise JsonRpcError(INVALID_PARAMS, f"`{name}` must be a string")
    return val


def _tool_evaluate(args: dict[str, Any]) -> dict[str, Any]:
    pattern = _require_str(args, "pattern")
    allies = _as_list(args.get("allies"), "allies")
    enemies = _as_list(args.get("enemies"), "enemies")
    result = _engine_evaluate(pattern, allies, enemies)
    return {
        "pattern": result.pattern,
        "valid": result.valid,
        "error": result.error,
        "redos_warning": result.redos_warning,
        "summary": result.status_line(),
        "allies": [dataclasses.asdict(r) for r in result.allies],
        "enemies": [dataclasses.asdict(r) for r in result.enemies],
        "totals": {
            "allies_passed": result.ally_pass_count,
            "enemies_passed": result.enemy_pass_count,
            "total_passed": result.total_passed,
            "total_examples": result.total_examples,
        },
    }


def _tool_attack(args: dict[str, Any]) -> dict[str, Any]:
    pattern = _require_str(args, "pattern")
    allies = _as_list(args.get("allies"), "allies")
    enemies = _as_list(args.get("enemies"), "enemies")
    report = _run_attack(pattern, allies, enemies)

    def _attack_dict(a: Any) -> dict[str, Any]:
        return {
            "text": a.text,
            "label": a.label,
            "rationale": a.rationale,
            "should_match": a.should_match,
        }

    return {
        "pattern": report.pattern,
        "provider": report.provider,
        "used_fallback": report.used_fallback,
        "summary": report.summary(),
        "attacks": [_attack_dict(a) for a in report.attacks],
        "correct": [_attack_dict(a) for a in report.correct],
        "misses": [_attack_dict(a) for a in report.misses],
        "xp": report.xp,
        "damage": report.damage,
    }


_EVALUATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["pattern"],
    "properties": {
        "pattern": {"type": "string", "description": "Regex pattern to evaluate."},
        "allies": {
            "description": "Strings the pattern SHOULD match. String (newline-separated) or array.",
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
        },
        "enemies": {
            "description": "Strings the pattern should NOT match.",
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
        },
    },
    "additionalProperties": False,
}


_ATTACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["pattern"],
    "properties": {
        "pattern": {"type": "string", "description": "Regex pattern the sensei will attack."},
        "allies": {
            "description": "Existing should-match examples (string or array).",
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
        },
        "enemies": {
            "description": "Existing should-not-match examples.",
            "oneOf": [
                {"type": "string"},
                {"type": "array", "items": {"type": "string"}},
            ],
        },
    },
    "additionalProperties": False,
}


def default_tools() -> list[Tool]:
    """Return the built-in toolset. Exposed so tests can introspect easily."""
    return [
        Tool(
            name="evaluate",
            description=(
                "Evaluate a regex pattern against ally (should-match) and enemy "
                "(should-not-match) example strings. Returns per-example results, "
                "a pass/fail tally, and a ReDoS warning when the pattern looks risky."
            ),
            input_schema=_EVALUATE_SCHEMA,
            handler=_tool_evaluate,
        ),
        Tool(
            name="attack",
            description=(
                "Ask the regex-rumble sensei to generate adversarial example strings "
                "and report which ones the pattern misclassifies. Useful for fuzzing "
                "a regex before committing it."
            ),
            input_schema=_ATTACK_SCHEMA,
            handler=_tool_attack,
        ),
    ]


# ---- server ----------------------------------------------------------------


@dataclass
class MCPServer:
    """Stdio JSON-RPC MCP server.

    Drive it via :meth:`serve` (reads ``stdin`` until EOF) or :meth:`handle`
    (one request → one response, for in-process tests).
    """

    tools: list[Tool] = field(default_factory=default_tools)
    _initialized: bool = False

    # ---- core dispatch -----------------------------------------------------

    def _tool_by_name(self, name: str) -> Tool:
        for t in self.tools:
            if t.name == name:
                return t
        raise JsonRpcError(METHOD_NOT_FOUND, f"unknown tool: {name}")

    def handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        """Process one JSON-RPC request and return the response dict.

        Returns ``None`` for notifications (no ``id``), matching JSON-RPC 2.0.
        """
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return _error_response(None, INVALID_REQUEST, "expected JSON-RPC 2.0 request")

        method = request.get("method")
        req_id = request.get("id")
        params = request.get("params") or {}
        is_notification = "id" not in request

        if not isinstance(method, str):
            return _error_response(req_id, INVALID_REQUEST, "missing `method`")

        try:
            result = self._dispatch(method, params if isinstance(params, dict) else {})
        except JsonRpcError as exc:
            if is_notification:
                return None
            return _error_response(req_id, exc.code, exc.message, exc.data)
        except Exception as exc:  # noqa: BLE001 — last-line safety net
            log.exception("unhandled error in %s", method)
            if is_notification:
                return None
            return _error_response(req_id, INTERNAL_ERROR, f"internal error: {exc}")

        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            return self._initialize(params)
        if method == "initialized" or method == "notifications/initialized":
            # Client telling us the handshake is complete. Nothing to do.
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [t.descriptor() for t in self.tools]}
        if method == "tools/call":
            return self._tools_call(params)
        raise JsonRpcError(METHOD_NOT_FOUND, f"unknown method: {method}")

    def _initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        self._initialized = True
        # Echo the client's protocol version when it's a string we recognise,
        # else fall back to our supported version.
        client_version = params.get("protocolVersion")
        protocol = client_version if isinstance(client_version, str) else PROTOCOL_VERSION
        return {
            "protocolVersion": protocol,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": __version__},
        }

    def _tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        if not isinstance(name, str):
            raise JsonRpcError(INVALID_PARAMS, "tools/call requires `name`")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            raise JsonRpcError(INVALID_PARAMS, "`arguments` must be an object")
        tool = self._tool_by_name(name)
        payload = tool.handler(args)
        # MCP tools/call result is a list of content blocks plus optional structured content.
        return {
            "content": [
                {"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}
            ],
            "structuredContent": payload,
            "isError": False,
        }

    # ---- transport ---------------------------------------------------------

    def serve(
        self,
        stdin: TextIO | BinaryIO | None = None,
        stdout: TextIO | BinaryIO | None = None,
    ) -> None:
        """Run the stdio loop until EOF on stdin.

        One JSON object per line in, one per line out (newline-delimited
        JSON-RPC, the simpler of the two MCP framings). Stays alive across
        per-request errors so a long-lived agent client doesn't drop us.
        """
        in_stream = stdin if stdin is not None else sys.stdin
        out_stream = stdout if stdout is not None else sys.stdout
        for response in self._iter_responses(_iter_lines(in_stream)):
            _write_line(out_stream, response)

    def _iter_responses(self, lines: Iterable[str]) -> Iterable[dict[str, Any]]:
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as exc:
                yield _error_response(None, PARSE_ERROR, f"parse error: {exc}")
                continue
            response = self.handle(request)
            if response is not None:
                yield response


def _iter_lines(stream: TextIO | BinaryIO) -> Iterable[str]:
    for raw in stream:
        if isinstance(raw, bytes):
            yield raw.decode("utf-8", errors="replace")
        else:
            yield raw


def _write_line(stream: TextIO | BinaryIO, payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False) + "\n"
    if hasattr(stream, "buffer"):
        # text stream — write str directly.
        stream.write(line)  # type: ignore[arg-type]
    else:
        try:
            stream.write(line)  # type: ignore[arg-type]
        except TypeError:
            stream.write(line.encode("utf-8"))  # type: ignore[arg-type]
    try:
        stream.flush()
    except Exception:  # noqa: BLE001
        pass


def _error_response(
    req_id: Any, code: int, message: str, data: Any = None
) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def run_server() -> None:
    """Entry point used by ``regex-rumble --serve-mcp``."""
    MCPServer().serve()
