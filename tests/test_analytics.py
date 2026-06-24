"""Tests for the regex weakness heatmap analytics (issue #22)."""

from __future__ import annotations

import json

from regex_rumble.analytics import (
    FEATURES,
    feature_tags,
    heatmap_payload,
    record_batch,
    record_outcome,
    render_heatmap,
    reset_analytics,
)
from regex_rumble.state import DojoState

# ---- feature tagging --------------------------------------------------------


def test_feature_tags_empty_string() -> None:
    assert feature_tags("") == frozenset({"empty"})


def test_feature_tags_ascii_digits() -> None:
    tags = feature_tags("12345")
    assert "digit" in tags
    assert "ascii-only" in tags
    assert "alpha" not in tags
    assert "unicode" not in tags


def test_feature_tags_unicode_and_whitespace() -> None:
    tags = feature_tags("héllo world\n")
    assert "unicode" in tags
    assert "whitespace" in tags
    assert "newline" in tags
    assert "boundary-whitespace" in tags
    assert "ascii-only" not in tags


def test_feature_tags_mixed_case_meta() -> None:
    tags = feature_tags("Foo.bar*")
    assert "mixed-case" in tags
    assert "regex-meta" in tags
    assert "alpha" in tags


def test_feature_tags_long_string() -> None:
    assert "long-string" in feature_tags("x" * 50)
    assert "long-string" not in feature_tags("short")


def test_feature_tags_deterministic_on_fixed_corpus() -> None:
    corpus = {
        "": frozenset({"empty"}),
        "abc": frozenset({"alpha", "ascii-only"}),
        " abc ": frozenset({"alpha", "ascii-only", "whitespace", "boundary-whitespace"}),
        "ABc": frozenset({"alpha", "ascii-only", "mixed-case"}),
        "12.3": frozenset({"digit", "ascii-only", "regex-meta", "punctuation"}),
    }
    for text, expected in corpus.items():
        assert feature_tags(text) == expected, text


# ---- counter increments -----------------------------------------------------


def test_record_outcome_bumps_totals_and_misses() -> None:
    s = DojoState()
    record_outcome(s, "abc", missed=False)
    assert s.analytics["totals"]["alpha"] == 1
    assert s.analytics["totals"]["ascii-only"] == 1
    assert s.analytics["misses"].get("alpha", 0) == 0

    record_outcome(s, "abc", missed=True)
    assert s.analytics["totals"]["alpha"] == 2
    assert s.analytics["misses"]["alpha"] == 1


def test_record_batch_handles_correct_and_missed() -> None:
    s = DojoState()
    record_batch(s, correct=["abc", "12"], missed=["héllo "])
    # "héllo " is unicode + whitespace + boundary-whitespace + alpha
    assert s.analytics["misses"]["unicode"] == 1
    assert s.analytics["totals"]["unicode"] == 1
    assert s.analytics["totals"]["ascii-only"] == 2  # "abc" + "12"


def test_reset_analytics_clears_counters_only() -> None:
    s = DojoState(xp=42)
    record_outcome(s, "héllo", missed=True)
    assert s.analytics["misses"]
    reset_analytics(s)
    assert s.analytics == {"misses": {}, "totals": {}}
    # Other progression untouched.
    assert s.xp == 42


# ---- heatmap rendering ------------------------------------------------------


def test_render_heatmap_empty_state_friendly_message() -> None:
    out = render_heatmap(DojoState(), color=False)
    assert "no sensei attacks" in out


def _seeded_state() -> DojoState:
    """Deterministic seed corpus so the heatmap is stable across runs."""
    s = DojoState()
    # Whitespace: high miss rate.
    record_batch(s, correct=[], missed=["a b", " trailing ", "tab\there"])
    # Digit: low miss rate.
    record_batch(s, correct=["1", "22", "333", "4444"], missed=["5"])
    # Unicode: medium miss rate.
    record_batch(s, correct=["plain"], missed=["héllo", "naïve"])
    return s


def test_render_heatmap_deterministic_order() -> None:
    s = _seeded_state()
    out = render_heatmap(s, color=False)
    lines = [ln for ln in out.splitlines() if "%" in ln]
    # First data row should be the worst miss rate.
    features_in_order = []
    for ln in lines:
        for f in FEATURES:
            if ln.lstrip().startswith(f):
                features_in_order.append(f)
                break
    assert features_in_order  # rendered something
    # whitespace and boundary-whitespace were 100% misses → must appear before digit (low).
    assert features_in_order.index("whitespace") < features_in_order.index("digit")


def test_render_heatmap_no_color_has_no_ansi() -> None:
    s = _seeded_state()
    out = render_heatmap(s, color=False)
    assert "\x1b[" not in out


def test_render_heatmap_color_includes_ansi() -> None:
    s = _seeded_state()
    out = render_heatmap(s, color=True)
    assert "\x1b[" in out


def test_heatmap_payload_is_json_serializable() -> None:
    s = _seeded_state()
    payload = heatmap_payload(s)
    blob = json.dumps(payload)  # must not raise
    parsed = json.loads(blob)
    assert "rows" in parsed
    assert parsed["features_known"] == list(FEATURES)
    rates = [r["rate"] for r in parsed["rows"]]
    assert rates == sorted(rates, reverse=True)


# ---- state round-trips through JSON ----------------------------------------


def test_dojo_state_json_round_trip_preserves_analytics() -> None:
    s = _seeded_state()
    reloaded = DojoState.from_json(s.to_json())
    assert reloaded.analytics == s.analytics
