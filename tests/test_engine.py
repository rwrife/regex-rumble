"""M3 — live regex evaluation engine."""

from __future__ import annotations

from regex_rumble.engine import evaluate, split_examples


def test_empty_pattern_is_invalid_but_does_not_crash() -> None:
    result = evaluate("", "alice\nbob", "carol")
    assert result.valid is False
    assert result.error == "empty pattern"
    # examples still carried through, all failing
    assert [r.text for r in result.allies] == ["alice", "bob"]
    assert all(not r.passed for r in result.allies)
    assert all(not r.passed for r in result.enemies)
    assert "invalid regex" in result.status_line()


def test_invalid_regex_is_reported_gracefully() -> None:
    result = evaluate("(", "x", "y")
    assert result.valid is False
    assert result.error
    assert all(not r.passed for r in result.allies + result.enemies)


def test_anchored_pattern_classifies_allies_and_enemies() -> None:
    result = evaluate(r"^foo$", "foo\nfoobar", "bar\nfoo bar")
    assert result.valid is True
    assert [r.passed for r in result.allies] == [True, False]
    assert [r.matched for r in result.allies] == [True, False]
    # enemies "must NOT match" — passing means the regex correctly rejected them
    assert [r.passed for r in result.enemies] == [True, True]
    assert result.ally_pass_count == 1
    assert result.enemy_pass_count == 2
    assert result.total_examples == 4
    assert result.total_passed == 3
    assert "allies 1/2" in result.status_line()
    assert "enemies 2/2" in result.status_line()


def test_character_class_pattern() -> None:
    result = evaluate(r"^[a-z]+$", "abc\nxyz", "ABC\nabc123\n42")
    assert result.valid is True
    assert all(r.passed for r in result.allies)
    assert all(r.passed for r in result.enemies)


def test_empty_examples_produce_zero_totals_but_valid_pattern() -> None:
    result = evaluate(r"foo", "", "")
    assert result.valid is True
    assert result.total_examples == 0
    assert result.status_line() == "no examples yet — add allies and enemies"


def test_split_examples_strips_comments_and_blanks() -> None:
    blob = "# header\n\nalpha\n  beta  \n# trailing\n"
    assert split_examples(blob) == ["alpha", "  beta  "]


def test_iterable_inputs_are_accepted() -> None:
    result = evaluate(r"\d+", ["123", "abc"], ["nope"])
    assert result.valid is True
    assert [r.passed for r in result.allies] == [True, False]
    assert [r.passed for r in result.enemies] == [True]


def test_failing_ally_and_failing_enemy_are_marked() -> None:
    # ally "bar" doesn't match `^foo` → fail; enemy "foozilla" matches → fail
    result = evaluate(r"^foo", "foo\nbar", "carrot\nfoozilla")
    assert [r.passed for r in result.allies] == [True, False]
    assert [r.passed for r in result.enemies] == [True, False]


def test_redos_risk_flags_nested_quantifiers() -> None:
    from regex_rumble.engine import redos_risk

    assert redos_risk(r"(a+)+") is not None
    assert redos_risk(r"(a*)*b") is not None
    assert redos_risk(r"(.+)+") is not None


def test_redos_risk_flags_overlapping_alternation() -> None:
    from regex_rumble.engine import redos_risk

    assert redos_risk(r"(a|a)+") is not None
    assert redos_risk(r"(a|ab)*") is not None


def test_redos_risk_flags_adjacent_greedy_wildcards() -> None:
    from regex_rumble.engine import redos_risk

    assert redos_risk(r".*.*") is not None
    assert redos_risk(r".+.+") is not None


def test_redos_risk_silent_for_safe_patterns() -> None:
    from regex_rumble.engine import redos_risk

    assert redos_risk(r"^foo$") is None
    assert redos_risk(r"\d{3}-\d{4}") is None
    assert redos_risk(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9-]+\.[A-Za-z]{2,}") is None
    assert redos_risk("") is None


def test_evaluation_carries_redos_warning_on_risky_pattern() -> None:
    result = evaluate(r"(a+)+$", "aaaa", "bbbb")
    assert result.valid is True
    assert result.redos_warning is not None
    assert "backtrack" in result.redos_warning.lower() or "redos" in result.redos_warning.lower()


def test_evaluation_no_warning_for_safe_pattern() -> None:
    result = evaluate(r"^foo$", "foo", "bar")
    assert result.redos_warning is None
