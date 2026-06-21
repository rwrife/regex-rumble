"""Tests for the ReDoS dojo module."""

from __future__ import annotations

from regex_rumble.redos import (
    ReDoSFinding,
    detect,
    pump_strings,
    render_report,
    trace,
)


def test_detect_finds_nested_quantifier():
    findings = detect(r"(a+)+$")
    assert findings
    kinds = {f.kind for f in findings}
    assert "nested-quantifier" in kinds
    f = next(f for f in findings if f.kind == "nested-quantifier")
    assert f.snippet == "(a+)+"
    assert f.severity >= 3
    s, e = f.span
    assert r"(a+)+$"[s:e] == "(a+)+"


def test_detect_finds_overlapping_alternation():
    findings = detect(r"^(a|a)+$")
    assert any(f.kind == "overlapping-alternation" for f in findings)


def test_detect_finds_adjacent_greedy():
    findings = detect(r".*.*x")
    assert any(f.kind == "adjacent-greedy" for f in findings)


def test_detect_clean_pattern():
    assert detect(r"^[a-z]+@[a-z]+\.[a-z]{2,}$") == []
    assert detect("") == []


def test_detect_dedupes_by_span_keeps_highest_severity():
    # Same span could match nested-quantifier and quantified-optional rules
    # in some shapes; ensure we don't emit dupes.
    findings = detect(r"(a?)+")
    spans = [f.span for f in findings]
    assert len(spans) == len(set(spans))


def test_pump_strings_uses_seed_from_snippet():
    finding = ReDoSFinding(
        kind="nested-quantifier",
        span=(0, 5),
        snippet="(z+)+",
        message="",
        severity=3,
    )
    pumps = pump_strings("(z+)+", finding, lengths=(3, 5))
    assert pumps == ["zzz!", "zzzzz!"]


def test_pump_strings_auto_picks_finding():
    pumps = pump_strings(r"(a+)+$", lengths=(2,))
    assert pumps == ["aa!"]


def test_pump_strings_fallback_when_no_finding():
    pumps = pump_strings(r"^foo$", lengths=(2, 4))
    # No suspect construct → generic 'a' pump.
    assert pumps == ["aa!", "aaaa!"]


def test_trace_clean_pattern_is_fast():
    steps = trace(r"^[a-z]+$", lengths=(4, 8), timeout_s=0.5)
    assert len(steps) == 2
    assert all(not s.timed_out for s in steps)
    assert all(s.elapsed_ms < 500 for s in steps)


def test_trace_explodes_on_classic_redos():
    # (a+)+$ with non-matching trailer is the textbook exponential case.
    steps = trace(r"^(a+)+$", lengths=(10, 20, 30, 40), timeout_s=0.6)
    assert any(s.timed_out for s in steps), [s.elapsed_ms for s in steps]
    # Once we explode, the rest of the trace is short-circuited as timed-out.
    first_timeout = next(i for i, s in enumerate(steps) if s.timed_out)
    assert all(s.timed_out for s in steps[first_timeout:])


def test_render_report_includes_findings_and_bars():
    findings = detect(r"(a+)+$")
    steps = trace(r"^[a-z]+$", lengths=(4,), timeout_s=0.5)
    out = render_report(r"(a+)+$", findings, steps)
    assert "pattern:" in out
    assert "nested-quantifier" in out
    assert "pump trace" in out
