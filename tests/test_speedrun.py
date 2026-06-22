"""Tests for the speedrun engine (issue #21)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regex_rumble import speedrun as sr

# ---- pack loading ----------------------------------------------------------


def test_load_builtin_default_pack():
    pack = sr.load_pack("speedrun_default")
    assert pack.id == "speedrun_default"
    assert len(pack.challenges) >= 20
    # All challenges have at least one ally or enemy.
    for c in pack.challenges:
        assert c.allies or c.enemies
        assert c.name


def test_load_pack_missing(tmp_path: Path):
    with pytest.raises(sr.SpeedrunError):
        sr.load_pack("definitely_not_a_real_pack")


def test_load_pack_from_file(tmp_path: Path):
    payload = {
        "id": "tiny",
        "name": "Tiny",
        "challenges": [
            {"name": "a", "allies": ["a"], "enemies": ["b"]},
        ],
    }
    p = tmp_path / "tiny.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    pack = sr.load_pack(p)
    assert pack.id == "tiny"
    assert pack.challenges[0].name == "a"


def test_load_pack_malformed(tmp_path: Path):
    p = tmp_path / "bad.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(sr.SpeedrunError):
        sr.load_pack(p)


# ---- challenge selection ---------------------------------------------------


def test_select_challenges_is_deterministic():
    pack = sr.load_pack("speedrun_default")
    a = sr.select_challenges(pack, count=5, seed=42)
    b = sr.select_challenges(pack, count=5, seed=42)
    c = sr.select_challenges(pack, count=5, seed=43)
    assert a == b
    assert a != c
    assert len(a) == 5


def test_select_challenges_wraps_when_count_exceeds_pack():
    pack = sr.SpeedrunPack(
        id="x",
        name="x",
        challenges=(
            sr.SpeedrunChallenge("one", "", ("1",), ("a",)),
            sr.SpeedrunChallenge("two", "", ("2",), ("b",)),
        ),
    )
    chosen = sr.select_challenges(pack, count=5, seed=1)
    assert len(chosen) == 5
    assert {c.name for c in chosen} == {"one", "two"}


def test_select_challenges_rejects_zero_count():
    pack = sr.load_pack("speedrun_default")
    with pytest.raises(sr.SpeedrunError):
        sr.select_challenges(pack, count=0, seed=1)


# ---- pattern_solves --------------------------------------------------------


def test_pattern_solves_basic():
    challenge = sr.SpeedrunChallenge("digits", "", ("1", "42"), ("a", "1a"))
    assert sr.pattern_solves(r"^\d+$", challenge)
    assert not sr.pattern_solves(r"\d", challenge)  # matches enemies too
    assert not sr.pattern_solves("", challenge)
    assert not sr.pattern_solves("(", challenge)  # invalid regex


# ---- round-advance + timing -----------------------------------------------


class FakeClock:
    def __init__(self, *, start: float = 100.0):
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _two_round_pack():
    return sr.SpeedrunPack(
        id="test",
        name="test",
        challenges=(
            sr.SpeedrunChallenge("digits", "", ("1", "2"), ("a",)),
            sr.SpeedrunChallenge("letters", "", ("a", "b"), ("1",)),
        ),
    )


def test_speedrun_run_happy_path_timing():
    clock = FakeClock()
    pack = _two_round_pack()
    run = sr.SpeedrunRun(
        pack=pack,
        challenges=pack.challenges,
        count=2,
        seed=7,
        clock=clock,
    )
    assert run.current_index == 1
    run.start_round()

    clock.advance(2.5)
    # Wrong pattern: no advance.
    assert run.submit("zzz") is False
    assert run.current_index == 1
    assert not run.is_finished

    clock.advance(1.5)
    assert run.submit(r"^\d+$") is True
    assert run.current_index == 2  # auto-advanced
    assert run.results[0].elapsed_s == pytest.approx(4.0)
    assert run.results[0].solved is True

    # Second round — let submit lazy-start the clock.
    clock.advance(7.0)
    assert run.submit(r"^[a-z]+$") is True
    assert run.is_finished
    assert len(run.results) == 2
    assert run.results[1].elapsed_s == pytest.approx(0.0)  # lazy-started right before submit

    result = run.result()
    assert result.all_solved
    assert result.total_elapsed_s == pytest.approx(4.0)


def test_speedrun_elapsed_total_includes_live_round():
    clock = FakeClock()
    pack = _two_round_pack()
    run = sr.SpeedrunRun(
        pack=pack, challenges=pack.challenges, count=2, seed=1, clock=clock,
    )
    run.start_round()
    clock.advance(3.0)
    assert run.elapsed_total_s == pytest.approx(3.0)
    assert run.submit(r"^\d+$")
    # Between rounds the live timer is zero again.
    assert run.elapsed_total_s == pytest.approx(3.0)


def test_speedrun_abort_does_not_mark_all_solved():
    clock = FakeClock()
    pack = _two_round_pack()
    run = sr.SpeedrunRun(
        pack=pack, challenges=pack.challenges, count=2, seed=1, clock=clock,
    )
    run.start_round()
    clock.advance(1.0)
    result = run.abort()
    assert result.aborted
    assert not result.all_solved


def test_submit_after_finish_returns_false():
    clock = FakeClock()
    pack = _two_round_pack()
    run = sr.SpeedrunRun(
        pack=pack, challenges=pack.challenges[:1], count=1, seed=1, clock=clock,
    )
    run.start_round()
    assert run.submit(r"^\d+$")
    assert run.is_finished
    assert run.submit(r"^\d+$") is False


# ---- PR persistence --------------------------------------------------------


def test_save_pr_writes_and_improves(tmp_path: Path):
    state_path = tmp_path / "state.json"

    updated, previous = sr.save_pr("p", 5, 1, 10.0, state_path=state_path)
    assert updated is True
    assert previous is None
    assert sr.load_prs(state_path)[sr.pr_key("p", 5, 1)] == 10.0

    # Slower: no update.
    updated, previous = sr.save_pr("p", 5, 1, 12.0, state_path=state_path)
    assert updated is False
    assert previous == 10.0
    assert sr.load_prs(state_path)[sr.pr_key("p", 5, 1)] == 10.0

    # Faster: PR beaten.
    updated, previous = sr.save_pr("p", 5, 1, 7.5, state_path=state_path)
    assert updated is True
    assert previous == 10.0
    assert sr.load_prs(state_path)[sr.pr_key("p", 5, 1)] == 7.5


def test_save_pr_preserves_dojo_state_keys(tmp_path: Path):
    state_path = tmp_path / "state.json"
    # Pre-existing DojoState-like blob.
    state_path.write_text(json.dumps({"hp": 80, "xp": 5}), encoding="utf-8")
    sr.save_pr("p", 3, 9, 4.2, state_path=state_path)
    data = json.loads(state_path.read_text())
    assert data["hp"] == 80
    assert data["xp"] == 5
    assert data["speedrun_prs"][sr.pr_key("p", 3, 9)] == 4.2


def test_load_prs_handles_missing_and_corrupt(tmp_path: Path):
    assert sr.load_prs(tmp_path / "missing.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("garbage", encoding="utf-8")
    assert sr.load_prs(bad) == {}


# ---- formatting + render_summary ------------------------------------------


def test_format_split_under_and_over_minute():
    assert sr.format_split(0.5).endswith("s")
    assert ":" in sr.format_split(75.25)


def test_render_summary_shows_new_pr_when_no_previous():
    result = sr.SpeedrunResult(
        pack_id="p",
        count=2,
        seed=1,
        rounds=[
            sr.RoundResult(1, "a", 1.0, True),
            sr.RoundResult(2, "b", 2.0, True),
        ],
    )
    text = sr.render_summary(result, previous_pr=None)
    assert "new PR" in text
    assert "round  1" in text


def test_render_summary_shows_pr_stands_when_slower():
    result = sr.SpeedrunResult(
        pack_id="p",
        count=1,
        seed=1,
        rounds=[sr.RoundResult(1, "a", 10.0, True)],
    )
    text = sr.render_summary(result, previous_pr=5.0)
    assert "PR stands" in text


def test_render_summary_aborted_does_not_claim_pr():
    result = sr.SpeedrunResult(
        pack_id="p", count=1, seed=1,
        rounds=[sr.RoundResult(1, "a", 1.0, True)],
        aborted=True,
    )
    text = sr.render_summary(result, previous_pr=None)
    assert "aborted" in text
    assert "new PR" not in text


# ---- build_run helper ------------------------------------------------------


def test_build_run_assigns_seed_when_none():
    run = sr.build_run(count=3, seed=None)
    assert run.seed > 0
    assert run.count == 3
    assert len(run.challenges) == 3


def test_build_run_deterministic_with_seed():
    a = sr.build_run(count=4, seed=99)
    b = sr.build_run(count=4, seed=99)
    assert [c.name for c in a.challenges] == [c.name for c in b.challenges]
