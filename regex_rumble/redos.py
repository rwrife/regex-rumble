"""ReDoS dojo — hunt catastrophic-backtracking patterns.

This module is the foundation for the dedicated "ReDoS dojo" mode tracked in
issue #10.  It provides three building blocks the TUI (and the ``redos`` CLI
subcommand) compose on top of:

1. :func:`detect` — static heuristic scan that flags patterns smelling like
   classic exponential-backtracking traps (nested quantifiers, overlapping
   alternation, adjacent greedy wildcards…).  Each finding includes the
   substring span so the UI can highlight it.
2. :func:`pump_strings` — given a pattern + finding, generate a sequence of
   "pump" inputs of growing length that should trigger backtracking on the
   suspect construct.  Used both for the trace and as ready-made enemies.
3. :func:`trace` — execute the pattern against pump strings of increasing
   length under a watchdog timeout and return per-step wall-clock numbers
   so the TUI can plot an exponential curve.

We deliberately keep the heuristics conservative-but-actionable.  Proving a
pattern is ReDoS-safe in general is undecidable for PCRE-style engines; the
goal here is to nudge the user toward suspicious shapes and let them *see*
the backtracking blow up with their own eyes.
"""

from __future__ import annotations

import multiprocessing as mp
import re
import time
from dataclasses import dataclass
from typing import Literal

# ---- findings --------------------------------------------------------------

ReDoSKind = Literal[
    "nested-quantifier",
    "overlapping-alternation",
    "adjacent-greedy",
    "quantified-optional",
]

_SEVERITY: dict[ReDoSKind, int] = {
    "nested-quantifier": 3,
    "overlapping-alternation": 3,
    "adjacent-greedy": 2,
    "quantified-optional": 2,
}


@dataclass(frozen=True)
class ReDoSFinding:
    """One suspicious construct discovered in a pattern."""

    kind: ReDoSKind
    span: tuple[int, int]   # (start, end) into the original pattern string
    snippet: str
    message: str
    severity: int           # 1 = mild, 3 = nasty

    def format(self) -> str:
        s, e = self.span
        return f"[{self.kind} sev={self.severity}] {s}:{e} `{self.snippet}` — {self.message}"


# Heuristic regexes.  Each entry: (kind, compiled, message, pump-builder key).
_HEURISTICS: tuple[tuple[ReDoSKind, re.Pattern[str], str, str], ...] = (
    (
        "nested-quantifier",
        re.compile(r"\((?:\?[:=!])?[^()]*[+*][^()]*\)[+*]"),
        "nested quantifiers like (a+)+ can backtrack exponentially",
        "nested",
    ),
    (
        "overlapping-alternation",
        re.compile(r"\((?:\?[:=!])?[^()|]+\|[^()]*\)[+*]"),
        "alternation with overlapping branches inside a quantifier is a classic ReDoS trap",
        "alternation",
    ),
    (
        "adjacent-greedy",
        re.compile(r"\.[+*]\.[+*]"),
        "adjacent greedy wildcards (.*.*) can backtrack badly",
        "wildcard",
    ),
    (
        "quantified-optional",
        re.compile(r"\((?:\?[:=!])?[^()]*\?\)[+*]"),
        "quantified optional group like (a?)+ has many empty-match paths",
        "optional",
    ),
)


def detect(pattern: str) -> list[ReDoSFinding]:
    """Return findings for ``pattern``; empty list if nothing suspicious.

    Findings are returned in source order.  The same span may surface under
    multiple kinds (e.g. ``(a|a)+`` is both overlapping-alternation and a
    nested-ish trap) — we keep the highest-severity match per span.
    """
    if not pattern:
        return []
    by_span: dict[tuple[int, int], ReDoSFinding] = {}
    for kind, rx, msg, _ in _HEURISTICS:
        for m in rx.finditer(pattern):
            span = m.span()
            f = ReDoSFinding(
                kind=kind,
                span=span,
                snippet=m.group(0),
                message=msg,
                severity=_SEVERITY[kind],
            )
            existing = by_span.get(span)
            if existing is None or f.severity > existing.severity:
                by_span[span] = f
    return sorted(by_span.values(), key=lambda f: f.span[0])


# ---- pump strings ----------------------------------------------------------


_TRAILER_DEFAULT = "!"


def _seed_char(snippet: str) -> str:
    """Pick a plausible pump character based on the suspect snippet.

    Falls back to ``'a'`` if we can't extract anything sensible.  For an
    alternation like ``(a|b)+`` we use the first literal branch character so
    the pump actually exercises the overlapping branch.
    """
    # Strip outer group + trailing quantifier.
    inner = snippet
    if inner.startswith("("):
        inner = inner[1:]
        if inner.startswith(("?:", "?=", "?!")):
            inner = inner[2:]
    inner = re.sub(r"\)[+*]?$", "", inner)
    for ch in inner:
        if ch.isalnum():
            return ch
    return "a"


def pump_strings(
    pattern: str,
    finding: ReDoSFinding | None = None,
    *,
    lengths: tuple[int, ...] = (4, 8, 12, 16, 20, 24, 28),
    trailer: str = _TRAILER_DEFAULT,
) -> list[str]:
    """Generate pump payloads for the worst (or given) finding.

    Each payload is ``seed * n + trailer`` where ``trailer`` is a character
    chosen to *fail* the pattern's final anchor, forcing the engine to
    backtrack through every alternative split.  If no finding is supplied,
    the highest-severity one in ``pattern`` is used; if there are none we
    still return generic ``'a' * n`` payloads so callers can probe blind.
    """
    if finding is None:
        findings = detect(pattern)
        finding = max(findings, key=lambda f: f.severity, default=None)
    seed = _seed_char(finding.snippet) if finding else "a"
    return [seed * n + trailer for n in lengths]


# ---- timing trace ----------------------------------------------------------


@dataclass(frozen=True)
class TraceStep:
    """One row in a ReDoS trace table."""

    length: int
    text: str
    elapsed_ms: float
    matched: bool
    timed_out: bool

    def bar(self, *, width: int = 30, scale_ms: float = 1.0) -> str:
        if self.timed_out:
            return "█" * width + " ⏱"
        units = min(width, int(self.elapsed_ms / max(scale_ms, 0.001)))
        return "█" * units


def _match_worker(pattern: str, text: str, q: mp.Queue) -> None:  # pragma: no cover
    # Runs in a subprocess so we can hard-kill on timeout.
    try:
        compiled = re.compile(pattern)
        matched = compiled.search(text) is not None
        q.put(("ok", matched))
    except re.error as exc:
        q.put(("err", str(exc)))


def _time_one(pattern: str, text: str, timeout_s: float) -> tuple[float, bool, bool]:
    """Return (elapsed_ms, matched, timed_out)."""
    ctx = mp.get_context("spawn")
    q: mp.Queue = ctx.Queue()
    proc = ctx.Process(target=_match_worker, args=(pattern, text, q), daemon=True)
    start = time.perf_counter()
    proc.start()
    proc.join(timeout_s)
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    if proc.is_alive():
        proc.terminate()
        proc.join(0.5)
        if proc.is_alive():  # pragma: no cover
            proc.kill()
        return elapsed_ms, False, True
    try:
        kind, value = q.get_nowait()
    except Exception:
        return elapsed_ms, False, True
    if kind == "err":
        # Invalid regex — surface as not-matched, not-timed-out so caller can
        # still see the elapsed (basically zero) row.
        return elapsed_ms, False, False
    return elapsed_ms, bool(value), False


def trace(
    pattern: str,
    *,
    lengths: tuple[int, ...] = (4, 8, 12, 16, 20, 24, 28),
    timeout_s: float = 1.0,
    finding: ReDoSFinding | None = None,
) -> list[TraceStep]:
    """Time ``pattern`` against pump strings of increasing length.

    Each step runs in a subprocess with a hard ``timeout_s`` watchdog.  Once
    a step times out, subsequent steps are reported as timed-out without
    actually running (the curve has already exploded — no need to burn more
    CPU on it).
    """
    payloads = pump_strings(pattern, finding, lengths=lengths)
    out: list[TraceStep] = []
    exploded = False
    for n, text in zip(lengths, payloads, strict=True):
        if exploded:
            out.append(
                TraceStep(length=n, text=text, elapsed_ms=timeout_s * 1000.0,
                          matched=False, timed_out=True)
            )
            continue
        elapsed_ms, matched, timed_out = _time_one(pattern, text, timeout_s)
        out.append(TraceStep(length=n, text=text, elapsed_ms=elapsed_ms,
                             matched=matched, timed_out=timed_out))
        if timed_out:
            exploded = True
    return out


# ---- pretty-printing helpers (used by CLI + future TUI) --------------------


def render_report(pattern: str, findings: list[ReDoSFinding], steps: list[TraceStep]) -> str:
    """Compose a human-readable ReDoS report for terminal output."""
    lines: list[str] = []
    lines.append(f"pattern: {pattern}")
    if not findings:
        lines.append("static check: no obvious ReDoS shapes ✓")
    else:
        lines.append(f"static check: {len(findings)} suspicious construct(s)")
        for f in findings:
            lines.append("  - " + f.format())
    if steps:
        # Scale bars so the longest non-timed-out row hits ~30 chars.
        finite = [s.elapsed_ms for s in steps if not s.timed_out]
        peak = max(finite, default=1.0)
        scale = max(peak / 30.0, 0.1)
        lines.append("")
        lines.append("pump trace:")
        lines.append(f"  {'len':>4}  {'ms':>10}  graph")
        for s in steps:
            ms = "TIMEOUT" if s.timed_out else f"{s.elapsed_ms:8.2f}"
            lines.append(f"  {s.length:>4}  {ms:>10}  {s.bar(scale_ms=scale)}")
    return "\n".join(lines)
