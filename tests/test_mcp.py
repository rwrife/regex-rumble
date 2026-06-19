"""Tests for the MCP server surface."""

from __future__ import annotations

import io
import json

from regex_rumble import __version__
from regex_rumble.mcp import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    MCPServer,
    default_tools,
)
from regex_rumble.sensei import Attack, MockProvider, run_attack


def _req(method: str, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    return msg


def test_initialize_returns_server_info_and_capabilities():
    server = MCPServer()
    resp = server.handle(_req("initialize", {"protocolVersion": "2025-03-26"}))
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    result = resp["result"]
    assert result["serverInfo"] == {"name": "regex-rumble", "version": __version__}
    assert "tools" in result["capabilities"]
    assert result["protocolVersion"] == "2025-03-26"


def test_initialize_falls_back_when_client_version_missing():
    server = MCPServer()
    resp = server.handle(_req("initialize", {}))
    assert isinstance(resp["result"]["protocolVersion"], str)


def test_tools_list_exposes_evaluate_and_attack():
    server = MCPServer()
    resp = server.handle(_req("tools/list"))
    names = sorted(t["name"] for t in resp["result"]["tools"])
    assert names == ["attack", "evaluate"]
    for tool in resp["result"]["tools"]:
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_default_tools_have_pattern_required():
    for tool in default_tools():
        assert "pattern" in tool.input_schema["required"]


def test_tools_call_evaluate_classifies_examples():
    server = MCPServer()
    server.handle(_req("initialize", {}))
    resp = server.handle(
        _req(
            "tools/call",
            {
                "name": "evaluate",
                "arguments": {
                    "pattern": r"^\d+$",
                    "allies": ["123", "42"],
                    "enemies": ["abc", "12a"],
                },
            },
        )
    )
    payload = resp["result"]["structuredContent"]
    assert payload["valid"] is True
    assert payload["totals"] == {
        "allies_passed": 2,
        "enemies_passed": 2,
        "total_passed": 4,
        "total_examples": 4,
    }
    # Content block must also be valid JSON for clients that only read text.
    content_text = resp["result"]["content"][0]["text"]
    assert json.loads(content_text) == payload


def test_tools_call_evaluate_accepts_newline_blob():
    server = MCPServer()
    resp = server.handle(
        _req(
            "tools/call",
            {
                "name": "evaluate",
                "arguments": {
                    "pattern": r"^\d+$",
                    "allies": "1\n2\n3\n",
                    "enemies": "x",
                },
            },
        )
    )
    payload = resp["result"]["structuredContent"]
    assert payload["totals"]["total_examples"] == 4
    assert payload["totals"]["allies_passed"] == 3


def test_tools_call_evaluate_reports_invalid_regex():
    server = MCPServer()
    resp = server.handle(
        _req(
            "tools/call",
            {"name": "evaluate", "arguments": {"pattern": "(", "allies": [], "enemies": []}},
        )
    )
    payload = resp["result"]["structuredContent"]
    assert payload["valid"] is False
    assert payload["error"]


def test_tools_call_attack_uses_run_attack_with_mock(monkeypatch):
    attacks = [
        Attack("yes", "should-match", "should be ok"),
        Attack("no!", "should-not-match", "punctuation trip"),
    ]
    provider = MockProvider(attacks)

    def _fake_run(pattern, allies, enemies, *, provider=None):
        return run_attack(pattern, allies, enemies, provider=provider or provider)

    # Patch the module-level run_attack used by the MCP server so we control
    # the sensei without making real network calls.
    monkeypatch.setattr(
        "regex_rumble.mcp._run_attack",
        lambda pattern, allies, enemies: run_attack(
            pattern, allies, enemies, provider=provider
        ),
    )
    server = MCPServer()
    resp = server.handle(
        _req(
            "tools/call",
            {
                "name": "attack",
                "arguments": {"pattern": r"^yes$", "allies": ["yes"], "enemies": ["no"]},
            },
        )
    )
    payload = resp["result"]["structuredContent"]
    assert payload["provider"] == "mock"
    assert len(payload["attacks"]) == 2
    assert payload["xp"] + payload["damage"] == 2


def test_tools_call_unknown_tool_returns_method_not_found():
    server = MCPServer()
    resp = server.handle(_req("tools/call", {"name": "nope", "arguments": {}}))
    assert resp["error"]["code"] == METHOD_NOT_FOUND


def test_tools_call_missing_pattern_is_invalid_params():
    server = MCPServer()
    resp = server.handle(_req("tools/call", {"name": "evaluate", "arguments": {}}))
    assert resp["error"]["code"] == INVALID_PARAMS


def test_unknown_method_returns_method_not_found():
    server = MCPServer()
    resp = server.handle(_req("does/not/exist"))
    assert resp["error"]["code"] == METHOD_NOT_FOUND


def test_notification_returns_none():
    server = MCPServer()
    # No `id` field → notification per JSON-RPC 2.0.
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_notification_swallows_errors():
    server = MCPServer()
    # Notifications must not produce a response even on error.
    assert server.handle({"jsonrpc": "2.0", "method": "does/not/exist"}) is None


def test_invalid_jsonrpc_envelope():
    server = MCPServer()
    resp = server.handle({"id": 1, "method": "ping"})  # missing jsonrpc field
    assert resp["error"]["code"] != 0


def test_serve_stdio_roundtrip():
    server = MCPServer()
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "evaluate",
                "arguments": {"pattern": "a", "allies": ["a"], "enemies": ["b"]},
            },
        },
    ]
    stdin = io.StringIO("\n".join(json.dumps(r) for r in requests) + "\n")
    stdout = io.StringIO()
    server.serve(stdin=stdin, stdout=stdout)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert [r["id"] for r in lines] == [1, 2, 3]
    assert lines[1]["result"]["tools"]
    assert lines[2]["result"]["structuredContent"]["valid"] is True


def test_serve_recovers_from_parse_errors():
    server = MCPServer()
    stdin = io.StringIO("not json\n" + json.dumps(_req("ping", req_id=7)) + "\n")
    stdout = io.StringIO()
    server.serve(stdin=stdin, stdout=stdout)
    lines = [json.loads(line) for line in stdout.getvalue().splitlines() if line.strip()]
    assert lines[0]["error"]["code"] == PARSE_ERROR
    assert lines[1]["id"] == 7
    assert lines[1]["result"] == {}
