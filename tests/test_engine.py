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
