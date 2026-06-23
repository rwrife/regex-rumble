"""Speedrun mode: race the clock through N regex challenges.

Issue #21. This module is the pure engine — pack loading, deterministic
challenge selection, round/state transitions, timing accumulation, and
personal-record persistence. The Textual screen in :mod:`regex_rumble.app`
drives this engine; tests inject a fake clock to keep things hermetic.

The clock is provided by the caller (any zero-arg callable returning a
monotonic-ish float in seconds) so timing logic is fully testable without
``time.sleep``.
"""

from __future__ import annotations

import json
import random
import time as _time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .engine import evaluate
from .packs import builtin_pack_path

# ---- data ------------------------------------------------------------------


@dataclass(frozen=True)
class SpeedrunChallenge:
    """One round in a speedrun pack."""

    name: str
    hint: str
    allies: tuple[str, ...]
    enemies: tuple[str, ...]


@dataclass(frozen=True)
class SpeedrunPack:
    """A collection of speedrun challenges."""

    id: str
    name: str
    challenges: tuple[SpeedrunChallenge, ...]
    version: int = 1


@dataclass(frozen=True)
class RoundResult:
    """Outcome of one solved (or aborted) round."""

    index: int               # 1-based round number
    name: str
    elapsed_s: float
    solved: bool


@dataclass
class SpeedrunResult:
    """The full outcome of a speedrun run."""

    pack_id: str
    count: int
    seed: int
    rounds: list[RoundResult] = field(default_factory=list)
    aborted: bool = False

    @property
    def total_elapsed_s(self) -> float:
        return sum(r.elapsed_s for r in self.rounds)

    @property
    def all_solved(self) -> bool:
        return (not self.aborted) and len(self.rounds) > 0 and all(r.solved for r in self.rounds)


# ---- pack loading ----------------------------------------------------------


class SpeedrunError(ValueError):
    """Raised for malformed packs / invalid input."""


def _coerce_challenge(data: dict[str, Any]) -> SpeedrunChallenge:
    if not isinstance(data, dict):
        raise SpeedrunError("challenge must be a JSON object")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise SpeedrunError("challenge is missing a non-empty 'name'")
    hint = data.get("hint", "") or ""
    if not isinstance(hint, str):
        raise SpeedrunError("'hint' must be a string")
    allies_raw = data.get("allies", [])
    enemies_raw = data.get("enemies", [])
    if not isinstance(allies_raw, list) or not isinstance(enemies_raw, list):
        raise SpeedrunError("'allies' and 'enemies' must be lists")
    if not allies_raw and not enemies_raw:
        raise SpeedrunError(f"challenge {name!r} has no allies or enemies")
    allies = tuple(str(x) for x in allies_raw)
    enemies = tuple(str(x) for x in enemies_raw)
    return SpeedrunChallenge(name=name.strip(), hint=hint, allies=allies, enemies=enemies)


def load_pack(source: str | Path) -> SpeedrunPack:
    """Load a speedrun pack from a built-in id, a file path, or a bundle path.

    ``source`` may be:

    * the id of a built-in pack (e.g. ``"speedrun_default"``)
    * a filesystem path to a JSON pack file
    """
    source_str = str(source)
    candidate = Path(source_str)
    if candidate.exists():
        path = candidate
    else:
        path = builtin_pack_path(source_str)
        if not path.exists():
            raise SpeedrunError(f"no such pack: {source_str!r}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SpeedrunError(f"pack {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SpeedrunError(f"pack {path} must be a JSON object")
    pack_id = str(data.get("id") or path.stem)
    name = str(data.get("name") or pack_id)
    raw_challenges = data.get("challenges", [])
    if not isinstance(raw_challenges, list) or not raw_challenges:
        raise SpeedrunError(f"pack {pack_id!r} has no challenges")
    challenges = tuple(_coerce_challenge(c) for c in raw_challenges)
    version = data.get("version", 1)
    if not isinstance(version, int):
        raise SpeedrunError("'version' must be an int")
    return SpeedrunPack(id=pack_id, name=name, challenges=challenges, version=version)


# ---- challenge selection ---------------------------------------------------


def select_challenges(
    pack: SpeedrunPack, *, count: int, seed: int
) -> tuple[SpeedrunChallenge, ...]:
    """Pick ``count`` challenges from ``pack`` deterministically by ``seed``.

    If the pack has fewer than ``count`` challenges, the sequence wraps —
    we cycle through a fresh shuffled copy so every selected entry is still
    a real challenge from the pack.
    """
    if count <= 0:
        raise SpeedrunError("count must be positive")
    rng = random.Random(seed)
    available = list(pack.challenges)
    rng.shuffle(available)
    out: list[SpeedrunChallenge] = []
    i = 0
    while len(out) < count:
        if i >= len(available):
            rng.shuffle(available)
            i = 0
        out.append(available[i])
        i += 1
    return tuple(out)


# ---- pattern check ---------------------------------------------------------


def pattern_solves(pattern: str, challenge: SpeedrunChallenge) -> bool:
    """True iff ``pattern`` correctly classifies every example in ``challenge``."""
    if not pattern:
        return False
    result = evaluate(pattern, challenge.allies, challenge.enemies)
    if not result.valid:
        return False
    return result.total_passed == result.total_examples


# ---- run accumulator -------------------------------------------------------


Clock = Callable[[], float]


@dataclass
class SpeedrunRun:
    """Stateful accumulator for an in-progress speedrun.

    The TUI (or a test) calls :meth:`start_round` then :meth:`finish_round`
    once the user's pattern solves the current challenge; :meth:`abort`
    stops the run without saving a PR.
    """

    pack: SpeedrunPack
    challenges: Sequence[SpeedrunChallenge]
    count: int
    seed: int
    clock: Clock = _time.monotonic
    _round_index: int = 0           # 0-based index of the *current* round
    _round_started_at: float | None = None
    _results: list[RoundResult] = field(default_factory=list)
    _aborted: bool = False

    # ---- introspection ---------------------------------------------------

    @property
    def current_index(self) -> int:
        """1-based index of the round in progress (0 if not started/finished)."""
        if self.is_finished:
            return 0
        return self._round_index + 1

    @property
    def current_challenge(self) -> SpeedrunChallenge | None:
        if self.is_finished or self._round_index >= len(self.challenges):
            return None
        return self.challenges[self._round_index]

    @property
    def is_finished(self) -> bool:
        return self._aborted or self._round_index >= len(self.challenges)

    @property
    def elapsed_total_s(self) -> float:
        """Total time across completed rounds + the live current round."""
        live = 0.0
        if self._round_started_at is not None and not self.is_finished:
            live = max(0.0, self.clock() - self._round_started_at)
        return sum(r.elapsed_s for r in self._results) + live

    @property
    def results(self) -> tuple[RoundResult, ...]:
        return tuple(self._results)

    # ---- transitions -----------------------------------------------------

    def start_round(self) -> SpeedrunChallenge:
        """Begin timing the current round. Returns the active challenge."""
        if self.is_finished:
            raise SpeedrunError("speedrun is already finished")
        if self._round_started_at is not None:
            raise SpeedrunError("round already started")
        self._round_started_at = self.clock()
        return self.challenges[self._round_index]

    def submit(self, pattern: str) -> bool:
        """Try the supplied pattern against the current round.

        Returns ``True`` (and auto-advances) iff the pattern solves the
        round. A failed submit does not advance and does not stop the clock.
        """
        challenge = self.current_challenge
        if challenge is None:
            return False
        if self._round_started_at is None:
            # Lazy-start so callers that only know the pattern still work.
            self.start_round()
        if not pattern_solves(pattern, challenge):
            return False
        self._finish_current_round(solved=True)
        return True

    def _finish_current_round(self, *, solved: bool) -> None:
        assert self._round_started_at is not None
        elapsed = max(0.0, self.clock() - self._round_started_at)
        challenge = self.challenges[self._round_index]
        self._results.append(
            RoundResult(
                index=self._round_index + 1,
                name=challenge.name,
                elapsed_s=elapsed,
                solved=solved,
            )
        )
        self._round_started_at = None
        self._round_index += 1

    def abort(self) -> SpeedrunResult:
        """Stop the run; partial round (if any) is discarded."""
        self._round_started_at = None
        self._aborted = True
        return self.result()

    def result(self) -> SpeedrunResult:
        return SpeedrunResult(
            pack_id=self.pack.id,
            count=self.count,
            seed=self.seed,
            rounds=list(self._results),
            aborted=self._aborted,
        )


# ---- PR persistence --------------------------------------------------------


def pr_key(pack_id: str, count: int, seed: int) -> str:
    """The state-file key used for the personal record of this configuration."""
    return f"{pack_id}|{count}|{seed}"


def _coerce_pr_map(raw: Any) -> dict[str, float]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for k, v in raw.items():
        if isinstance(k, str) and isinstance(v, (int, float)):
            out[k] = float(v)
    return out


def load_prs(state_path: Path | None = None) -> dict[str, float]:
    """Read the speedrun PR table from disk; returns ``{}`` if missing."""
    from .state import default_state_path

    path = state_path or default_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return _coerce_pr_map(data.get("speedrun_prs"))


def save_pr(
    pack_id: str,
    count: int,
    seed: int,
    elapsed_s: float,
    *,
    state_path: Path | None = None,
) -> tuple[bool, float | None]:
    """Persist ``elapsed_s`` as the PR for the (pack, count, seed) config.

    Returns ``(updated, previous_best)``. The PR is only written when the new
    time strictly improves on the previous one (or none was set).
    """
    from .state import default_state_path

    path = state_path or default_state_path()
    # Read whatever is on disk so we don't clobber unrelated DojoState fields.
    try:
        on_disk: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        on_disk = {}
    except json.JSONDecodeError:
        on_disk = {}
    if not isinstance(on_disk, dict):
        on_disk = {}

    prs = _coerce_pr_map(on_disk.get("speedrun_prs"))
    key = pr_key(pack_id, count, seed)
    previous = prs.get(key)
    updated = previous is None or elapsed_s < previous
    if updated:
        prs[key] = float(elapsed_s)
        on_disk["speedrun_prs"] = prs
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(on_disk, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    return updated, previous


# ---- formatting helpers ----------------------------------------------------


def format_split(seconds: float) -> str:
    """Render a duration in mm:ss.mmm (or seconds.mmm if under a minute)."""
    if seconds < 0:
        seconds = 0.0
    minutes, rem = divmod(seconds, 60)
    if minutes:
        return f"{int(minutes):d}:{rem:06.3f}"
    return f"{rem:.3f}s"


def render_summary(result: SpeedrunResult, *, previous_pr: float | None) -> str:
    """Build the end-of-run summary lines used by the CLI and TUI."""
    lines: list[str] = []
    header = f"speedrun · pack={result.pack_id} count={result.count} seed={result.seed}"
    lines.append(header)
    if result.aborted:
        lines.append("aborted — PR not updated")
    for r in result.rounds:
        dot = "✓" if r.solved else "✗"
        lines.append(f"  {dot} round {r.index:>2} {r.name:<24} {format_split(r.elapsed_s)}")
    total = result.total_elapsed_s
    lines.append(f"total: {format_split(total)}")
    if not result.aborted and result.all_solved:
        if previous_pr is None:
            lines.append("🥇 new PR (no prior record)")
        elif total < previous_pr:
            delta = previous_pr - total
            lines.append(f"🥇 new PR — beat {format_split(previous_pr)} by {format_split(delta)}")
        else:
            lines.append(f"PR stands: {format_split(previous_pr)}")
    return "\n".join(lines)


# ---- top-level convenience -------------------------------------------------


def build_run(
    *,
    count: int = 10,
    seed: int | None = None,
    pack_source: str | Path = "speedrun_default",
    clock: Clock | None = None,
) -> SpeedrunRun:
    """Helper: load the pack, pick challenges, and return a fresh ``SpeedrunRun``."""
    if seed is None:
        seed = random.randrange(1, 2**31 - 1)
    pack = load_pack(pack_source)
    chosen = select_challenges(pack, count=count, seed=seed)
    return SpeedrunRun(
        pack=pack,
        challenges=chosen,
        count=count,
        seed=seed,
        clock=clock or _time.monotonic,
    )


__all__ = [
    "Clock",
    "RoundResult",
    "SpeedrunChallenge",
    "SpeedrunError",
    "SpeedrunPack",
    "SpeedrunResult",
    "SpeedrunRun",
    "build_run",
    "format_split",
    "load_pack",
    "load_prs",
    "pattern_solves",
    "pr_key",
    "render_summary",
    "save_pr",
    "select_challenges",
]

