"""Persistent dojo state: HP, XP, belts, streaks, daily challenges.

M5 adds long-term progression so practice feels addictive:

* ``DojoState`` — JSON-persistable dataclass tracking the player's HP, XP,
  current/best win streak, total wins/losses, and current belt rank.
* ``Belt`` — the white→black progression, derived purely from total XP.
* ``daily_challenge()`` — a deterministic seeded challenge for ``--daily``
  mode (same day → same pattern target, allies, enemies).
* JSON I/O lives at ``~/.regex-rumble/state.json`` by default but every
  helper accepts an explicit path so tests stay hermetic.

The module is intentionally pure-Python / stdlib only so it can be imported
without textual or httpx being available (e.g. from the CLI, or from unit
tests in an environment without a TTY).
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import random
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

STATE_VERSION = 1
DEFAULT_MAX_HP = 100

# Belt thresholds: (rank_name, min_xp). Ordered low → high.
BELTS: tuple[tuple[str, int], ...] = (
    ("white", 0),
    ("yellow", 10),
    ("orange", 25),
    ("green", 50),
    ("blue", 100),
    ("purple", 175),
    ("brown", 275),
    ("black", 400),
)


@dataclass(frozen=True)
class Belt:
    """A belt rank — name + the XP needed to reach it."""

    name: str
    min_xp: int

    @property
    def emoji(self) -> str:
        return {
            "white": "⚪",
            "yellow": "🟡",
            "orange": "🟠",
            "green": "🟢",
            "blue": "🔵",
            "purple": "🟣",
            "brown": "🟤",
            "black": "⚫",
        }.get(self.name, "🎽")


def belt_for_xp(xp: int) -> Belt:
    """Return the highest belt the given XP qualifies for."""
    current = BELTS[0]
    for name, threshold in BELTS:
        if xp >= threshold:
            current = (name, threshold)
        else:
            break
    return Belt(name=current[0], min_xp=current[1])


def next_belt(current: Belt) -> Belt | None:
    """Return the belt above ``current`` or ``None`` if already black."""
    for i, (name, _threshold) in enumerate(BELTS):
        if name == current.name and i + 1 < len(BELTS):
            nxt = BELTS[i + 1]
            return Belt(name=nxt[0], min_xp=nxt[1])
    return None


# ---- persistent state -------------------------------------------------------


@dataclass
class DojoState:
    """Player progression that survives across sessions."""

    hp: int = DEFAULT_MAX_HP
    max_hp: int = DEFAULT_MAX_HP
    xp: int = 0
    total_wins: int = 0
    total_losses: int = 0
    current_streak: int = 0
    best_streak: int = 0
    last_daily: str | None = None  # ISO date of the last completed daily
    # Per-feature heatmap counters used by regex_rumble.analytics.
    # Shape: {"misses": {feature: int}, "totals": {feature: int}}
    analytics: dict[str, dict[str, int]] = field(
        default_factory=lambda: {"misses": {}, "totals": {}}
    )
    version: int = STATE_VERSION

    # ---- belts -----------------------------------------------------------

    @property
    def belt(self) -> Belt:
        return belt_for_xp(self.xp)

    def xp_into_belt(self) -> int:
        return self.xp - self.belt.min_xp

    def xp_to_next(self) -> int | None:
        nxt = next_belt(self.belt)
        if nxt is None:
            return None
        return nxt.min_xp - self.xp

    # ---- mutations -------------------------------------------------------

    def apply_attack(self, *, xp_gained: int, damage: int) -> AttackOutcome:
        """Apply one sensei attack outcome and return what changed.

        Win/loss/streak rules:
        * Zero damage AND any xp → counts as a win (streak +1).
        * Any damage → counts as a loss (streak reset to 0).
        * Zero of both → a no-op (e.g. provider returned no attacks).
        """
        before_belt = self.belt
        self.xp += max(0, xp_gained)
        self.hp = max(0, self.hp - max(0, damage))

        promoted = False
        new_belt = self.belt
        if new_belt.name != before_belt.name:
            promoted = True

        won = False
        lost = False
        if xp_gained > 0 and damage == 0:
            won = True
            self.total_wins += 1
            self.current_streak += 1
            if self.current_streak > self.best_streak:
                self.best_streak = self.current_streak
        elif damage > 0:
            lost = True
            self.total_losses += 1
            self.current_streak = 0

        return AttackOutcome(
            xp_gained=xp_gained,
            damage=damage,
            belt_before=before_belt,
            belt_after=new_belt,
            promoted=promoted,
            won=won,
            lost=lost,
            hp_remaining=self.hp,
            knocked_out=self.hp <= 0,
        )

    def reset_round(self) -> None:
        """Restore HP to full for a fresh round; preserve XP/belt/streaks."""
        self.hp = self.max_hp

    def record_daily(self, iso_date: str) -> None:
        self.last_daily = iso_date

    # ---- serialization ---------------------------------------------------

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, blob: str) -> DojoState:
        data: dict[str, Any] = json.loads(blob)
        # Drop unknown keys so forward-compat is graceful.
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in known}
        return cls(**clean)


@dataclass(frozen=True)
class AttackOutcome:
    """The summary of one applied attack — drives the UI updates."""

    xp_gained: int
    damage: int
    belt_before: Belt
    belt_after: Belt
    promoted: bool
    won: bool
    lost: bool
    hp_remaining: int
    knocked_out: bool

    def headline(self) -> str:
        bits: list[str] = []
        if self.xp_gained:
            bits.append(f"+{self.xp_gained} XP")
        if self.damage:
            bits.append(f"−{self.damage} HP")
        if self.promoted:
            bits.append(f"🎉 promoted to {self.belt_after.name}!")
        elif self.knocked_out:
            bits.append("💥 K.O.")
        return " · ".join(bits) if bits else "no change"


# ---- I/O --------------------------------------------------------------------


def default_state_path() -> Path:
    """``~/.regex-rumble/state.json`` (respects ``REGEX_RUMBLE_HOME``)."""
    override = os.environ.get("REGEX_RUMBLE_HOME")
    base = Path(override) if override else Path.home() / ".regex-rumble"
    return base / "state.json"


def load_state(path: Path | None = None) -> DojoState:
    """Load state from disk, returning a fresh state if missing/corrupt."""
    p = path or default_state_path()
    try:
        return DojoState.from_json(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return DojoState()
    except (json.JSONDecodeError, TypeError, ValueError):
        # Corrupted file — back it up and start fresh.
        try:
            backup = p.with_suffix(p.suffix + ".bak")
            p.rename(backup)
        except OSError:
            pass
        return DojoState()


def save_state(state: DojoState, path: Path | None = None) -> Path:
    """Persist ``state`` atomically; returns the path written."""
    p = path or default_state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(state.to_json(), encoding="utf-8")
    tmp.replace(p)
    return p


# ---- daily challenge --------------------------------------------------------


# A small pool of starter challenges. The daily seed picks one + a small
# shuffle/sample so today's run is the same for every player but different
# from yesterday's.
_CHALLENGE_POOL: tuple[dict[str, Any], ...] = (
    {
        "name": "US ZIP codes",
        "hint": "Match valid 5-digit ZIPs, reject the impostors.",
        "allies": ["94110", "10001", "30301", "60601", "98101"],
        "enemies": ["1234", "ABCDE", "12 345", "123456", ""],
    },
    {
        "name": "hex colors",
        "hint": "Match 3- or 6-digit hex colors with a leading #.",
        "allies": ["#fff", "#000000", "#ABCDEF", "#1a2b3c", "#F0F"],
        "enemies": ["fff", "#ggg", "#12345", "#1234567", "rgb(0,0,0)"],
    },
    {
        "name": "semver",
        "hint": "Match MAJOR.MINOR.PATCH (no pre-release, for now).",
        "allies": ["1.0.0", "10.20.30", "0.0.1", "2.4.8", "99.99.99"],
        "enemies": ["1.0", "1.0.0.0", "v1.0.0", "1.0.0-rc1", "one.two.three"],
    },
    {
        "name": "ipv4",
        "hint": "Match dotted-quad IPv4 addresses (no leading zeros).",
        "allies": ["1.2.3.4", "127.0.0.1", "10.0.0.255", "192.168.1.1", "8.8.8.8"],
        "enemies": ["256.1.1.1", "1.2.3", "1.2.3.4.5", "01.02.03.04", "::1"],
    },
    {
        "name": "emails (loose)",
        "hint": "Match name@host.tld; reject obviously-bad shapes.",
        "allies": ["a@b.co", "ryan@example.com", "x.y+z@sub.example.org",
                   "u_n@dash-host.io", "n@a.b.c.d"],
        "enemies": ["plainaddress", "@nope.com", "name@", "spaces in@x.com", "a@b"],
    },
)


@dataclass(frozen=True)
class DailyChallenge:
    iso_date: str
    name: str
    hint: str
    allies: tuple[str, ...]
    enemies: tuple[str, ...]


def _today_iso(today: _dt.date | None = None) -> str:
    return (today or _dt.date.today()).isoformat()


def daily_challenge(today: _dt.date | None = None) -> DailyChallenge:
    """Return today's deterministic challenge."""
    iso = _today_iso(today)
    rng = random.Random(iso)
    base = rng.choice(_CHALLENGE_POOL)
    # Light shuffle of examples so order isn't always identical.
    allies = list(base["allies"])
    enemies = list(base["enemies"])
    rng.shuffle(allies)
    rng.shuffle(enemies)
    return DailyChallenge(
        iso_date=iso,
        name=base["name"],
        hint=base["hint"],
        allies=tuple(allies),
        enemies=tuple(enemies),
    )


__all__ = [
    "AttackOutcome",
    "Belt",
    "BELTS",
    "DailyChallenge",
    "DojoState",
    "STATE_VERSION",
    "belt_for_xp",
    "daily_challenge",
    "default_state_path",
    "load_state",
    "next_belt",
    "replace",
    "save_state",
]
