"""Tests for the persistent state / belts / daily challenge module."""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from regex_rumble.state import (
    BELTS,
    DojoState,
    belt_for_xp,
    daily_challenge,
    default_state_path,
    load_state,
    next_belt,
    save_state,
)

# ---- belts ------------------------------------------------------------------


def test_belt_for_xp_thresholds():
    assert belt_for_xp(0).name == "white"
    assert belt_for_xp(9).name == "white"
    assert belt_for_xp(10).name == "yellow"
    assert belt_for_xp(49).name == "orange"
    assert belt_for_xp(50).name == "green"
    assert belt_for_xp(99).name == "green"
    assert belt_for_xp(400).name == "black"
    assert belt_for_xp(10_000).name == "black"


def test_next_belt_progression():
    assert next_belt(belt_for_xp(0)).name == "yellow"
    assert next_belt(belt_for_xp(49)).name == "green"
    assert next_belt(belt_for_xp(400)) is None  # black is terminal


def test_belt_emoji_defined_for_all_ranks():
    for name, _ in BELTS:
        assert belt_for_xp({n: th for n, th in BELTS}[name]).emoji  # truthy


# ---- DojoState mutations ----------------------------------------------------


def test_apply_attack_win_increments_streak_and_xp():
    s = DojoState()
    out = s.apply_attack(xp_gained=3, damage=0)
    assert out.won and not out.lost
    assert s.xp == 3
    assert s.hp == s.max_hp  # no damage
    assert s.total_wins == 1
    assert s.current_streak == 1
    assert s.best_streak == 1
    assert not out.knocked_out


def test_apply_attack_loss_resets_streak():
    s = DojoState(current_streak=4, best_streak=4)
    out = s.apply_attack(xp_gained=2, damage=3)
    assert out.lost and not out.won
    assert s.current_streak == 0
    assert s.best_streak == 4  # preserved
    assert s.total_losses == 1
    assert s.hp == s.max_hp - 3
    assert s.xp == 2  # XP still banked even on a loss


def test_apply_attack_promotion_signals_change():
    s = DojoState(xp=9)
    out = s.apply_attack(xp_gained=1, damage=0)
    assert out.promoted
    assert out.belt_before.name == "white"
    assert out.belt_after.name == "yellow"


def test_apply_attack_no_op_when_zero_zero():
    s = DojoState(current_streak=2)
    out = s.apply_attack(xp_gained=0, damage=0)
    assert not out.won and not out.lost
    assert s.current_streak == 2  # unchanged


def test_apply_attack_knockout_flagged():
    s = DojoState(hp=5)
    out = s.apply_attack(xp_gained=0, damage=10)
    assert out.knocked_out
    assert s.hp == 0


def test_reset_round_restores_hp_keeps_xp():
    s = DojoState(hp=10, xp=42, total_wins=5)
    s.reset_round()
    assert s.hp == s.max_hp
    assert s.xp == 42
    assert s.total_wins == 5


# ---- xp_to_next -------------------------------------------------------------


def test_xp_to_next_counts_down():
    s = DojoState(xp=7)
    assert s.xp_to_next() == 3  # 10 - 7


def test_xp_to_next_none_at_black():
    s = DojoState(xp=500)
    assert s.belt.name == "black"
    assert s.xp_to_next() is None


# ---- persistence ------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path: Path):
    p = tmp_path / "state.json"
    s = DojoState(xp=33, total_wins=7, best_streak=4)
    save_state(s, p)
    loaded = load_state(p)
    assert loaded.xp == 33
    assert loaded.total_wins == 7
    assert loaded.best_streak == 4
    assert loaded.belt.name == "orange"


def test_load_missing_returns_fresh(tmp_path: Path):
    s = load_state(tmp_path / "nope.json")
    assert s.xp == 0
    assert s.hp == s.max_hp


def test_load_corrupt_backs_up_and_returns_fresh(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("{not: valid json", encoding="utf-8")
    s = load_state(p)
    assert s.xp == 0
    assert (tmp_path / "state.json.bak").exists()


def test_save_is_atomic_via_tmp(tmp_path: Path):
    p = tmp_path / "state.json"
    save_state(DojoState(xp=1), p)
    # No leftover tmp file after a successful save.
    assert not (tmp_path / "state.json.tmp").exists()
    assert json.loads(p.read_text())["xp"] == 1


def test_default_state_path_respects_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REGEX_RUMBLE_HOME", str(tmp_path))
    assert default_state_path() == tmp_path / "state.json"


def test_load_forward_compat_ignores_unknown_keys(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"xp": 5, "future_field": "ignored"}), encoding="utf-8")
    s = load_state(p)
    assert s.xp == 5


# ---- daily challenge --------------------------------------------------------


def test_daily_challenge_deterministic_for_a_date():
    d = dt.date(2026, 6, 15)
    a = daily_challenge(d)
    b = daily_challenge(d)
    assert a == b
    assert a.iso_date == "2026-06-15"
    assert a.allies and a.enemies


def test_daily_challenge_varies_by_date():
    a = daily_challenge(dt.date(2026, 6, 15))
    b = daily_challenge(dt.date(2026, 6, 16))
    # The pool is small so we can't guarantee a different name, but the
    # shuffled example order should almost certainly differ.
    assert (a.name, a.allies, a.enemies) != (b.name, b.allies, b.enemies)
