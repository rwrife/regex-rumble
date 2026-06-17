"""Challenge bundles for the multiplayer dojo (issue #7, slice 1).

A *challenge bundle* is a shareable description of a dojo round:

* an optional pattern *goal* (what the player should be matching),
* a hint / description,
* a list of allies (must match),
* a list of enemies (must not match).

Bundles are encoded in two ways:

* **File** — pretty-printed JSON, easy to commit / email / paste.
* **URL** — a compact ``regex-rumble://challenge/<base64url-zlib(json)>``
  link suitable for posting in chat. The same payload is also accepted as
  the fragment of an ``https://`` URL (``...#challenge=<payload>``) so the
  link can be opened in browsers.

This module is intentionally stdlib-only so it can be imported anywhere in
the package (CLI, app, tests) without dragging in textual / httpx.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import urllib.request
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

BUNDLE_VERSION = 1
URL_SCHEME = "regex-rumble"
URL_HOST = "challenge"


@dataclass(frozen=True)
class ChallengeBundle:
    """A shareable dojo round.

    ``goal_pattern`` is optional — bundles can simply ship example sets and
    let the recipient *invent* the pattern (the multiplayer use case).
    """

    name: str
    hint: str = ""
    allies: tuple[str, ...] = field(default_factory=tuple)
    enemies: tuple[str, ...] = field(default_factory=tuple)
    goal_pattern: str | None = None
    author: str | None = None
    version: int = BUNDLE_VERSION

    # ---- dict / json -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["allies"] = list(self.allies)
        d["enemies"] = list(self.enemies)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChallengeBundle:
        if not isinstance(data, dict):
            raise BundleError("bundle payload must be a JSON object")
        version = data.get("version", BUNDLE_VERSION)
        if not isinstance(version, int) or version > BUNDLE_VERSION:
            raise BundleError(f"unsupported bundle version: {version!r}")
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise BundleError("bundle is missing a non-empty 'name'")
        allies = _coerce_str_list(data.get("allies", []), "allies")
        enemies = _coerce_str_list(data.get("enemies", []), "enemies")
        hint = data.get("hint", "") or ""
        if not isinstance(hint, str):
            raise BundleError("'hint' must be a string")
        goal = data.get("goal_pattern")
        if goal is not None and not isinstance(goal, str):
            raise BundleError("'goal_pattern' must be a string or null")
        author = data.get("author")
        if author is not None and not isinstance(author, str):
            raise BundleError("'author' must be a string or null")
        return cls(
            name=name.strip(),
            hint=hint,
            allies=tuple(allies),
            enemies=tuple(enemies),
            goal_pattern=goal,
            author=author,
            version=version,
        )

    def to_json(self, *, pretty: bool = True) -> str:
        return json.dumps(
            self.to_dict(),
            indent=2 if pretty else None,
            sort_keys=True,
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> ChallengeBundle:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BundleError(f"invalid JSON: {exc.msg}") from exc
        return cls.from_dict(data)

    # ---- file ------------------------------------------------------------

    def write_file(self, path: str | Path) -> Path:
        p = Path(path)
        p.write_text(self.to_json() + "\n", encoding="utf-8")
        return p

    @classmethod
    def read_file(cls, path: str | Path) -> ChallengeBundle:
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    # ---- url -------------------------------------------------------------

    def to_url(self) -> str:
        payload = _encode_payload(self.to_json(pretty=False))
        return f"{URL_SCHEME}://{URL_HOST}/{payload}"

    @classmethod
    def from_url(cls, url: str) -> ChallengeBundle:
        payload = _extract_payload(url)
        return cls.from_json(_decode_payload(payload))


class BundleError(ValueError):
    """Raised on malformed bundle input."""


# ---------------------------------------------------------------------------
# Generic loader — accepts file paths, regex-rumble:// URLs, or https:// URLs
# with ?challenge=... / #challenge=... fragments.
# ---------------------------------------------------------------------------


def load_bundle(source: str | Path) -> ChallengeBundle:
    """Best-effort load from a path, URL, or raw JSON string."""
    if isinstance(source, Path):
        return ChallengeBundle.read_file(source)
    s = source.strip()
    if not s:
        raise BundleError("empty bundle source")
    lowered = s.lower()
    if lowered.startswith(f"{URL_SCHEME}://"):
        return ChallengeBundle.from_url(s)
    if lowered.startswith(("http://", "https://")):
        parsed = urllib.parse.urlparse(s)
        # Prefer embedded payload to avoid a network round-trip.
        for blob in (parsed.fragment, parsed.query):
            payload = _payload_from_query(blob)
            if payload:
                return ChallengeBundle.from_json(_decode_payload(payload))
        # Fall back to fetching the URL — assume it returns bundle JSON.
        with urllib.request.urlopen(s, timeout=10) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
        return ChallengeBundle.from_json(raw)
    # Raw JSON?
    if s.startswith("{"):
        return ChallengeBundle.from_json(s)
    # Otherwise treat as filesystem path.
    return ChallengeBundle.read_file(s)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _coerce_str_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise BundleError(f"'{field_name}' must be a list of strings")
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            raise BundleError(f"'{field_name}[{i}]' must be a string")
        out.append(item)
    return out


def _encode_payload(raw_json: str) -> str:
    compressed = zlib.compress(raw_json.encode("utf-8"), 9)
    return base64.urlsafe_b64encode(compressed).rstrip(b"=").decode("ascii")


def _decode_payload(payload: str) -> str:
    # Restore base64 padding.
    pad = "=" * (-len(payload) % 4)
    try:
        compressed = base64.urlsafe_b64decode(payload + pad)
        return zlib.decompress(compressed).decode("utf-8")
    except (ValueError, zlib.error) as exc:
        raise BundleError(f"invalid bundle payload: {exc}") from exc


def _extract_payload(url: str) -> str:
    if not url.lower().startswith(f"{URL_SCHEME}://"):
        raise BundleError(f"expected a {URL_SCHEME}:// URL")
    # Strip scheme.
    rest = url[len(URL_SCHEME) + 3 :]
    # Drop optional host (challenge) and slash.
    if "/" in rest:
        host, _, payload = rest.partition("/")
        if host and host.lower() != URL_HOST:
            raise BundleError(f"unknown bundle URL host: {host!r}")
        return payload
    return rest


def _payload_from_query(blob: str) -> str | None:
    if not blob:
        return None
    # blob may be either "challenge=XYZ&foo=1" or just "XYZ".
    if "=" in blob:
        params = urllib.parse.parse_qs(blob, keep_blank_values=False)
        values = params.get("challenge")
        if values:
            return values[0]
        return None
    return blob


__all__ = [
    "BUNDLE_VERSION",
    "BundleError",
    "ChallengeBundle",
    "load_bundle",
]
