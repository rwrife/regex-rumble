"""Live regex evaluation for the dojo.

Given a user pattern plus lists of "allies" (should match) and "enemies"
(should NOT match), produce per-example results and a summary tally so the
TUI can paint red/green dots and a status bar.

Compiled patterns are cached on a small LRU so re-evaluating on every
keystroke stays cheap.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache

# ---- public data shapes ----------------------------------------------------


@dataclass(frozen=True)
class ExampleResult:
    """Outcome of running one example string through the pattern."""

    text: str
    matched: bool   # did the pattern match this text?
    passed: bool    # did the example meet its expectation (ally→match, enemy→not)?


@dataclass(frozen=True)
class EvaluationResult:
    """Full evaluation of pattern + allies + enemies."""

    pattern: str
    valid: bool
    error: str | None
    allies: tuple[ExampleResult, ...] = field(default_factory=tuple)
    enemies: tuple[ExampleResult, ...] = field(default_factory=tuple)
    redos_warning: str | None = None

    @property
    def ally_pass_count(self) -> int:
        return sum(1 for r in self.allies if r.passed)

    @property
    def enemy_pass_count(self) -> int:
        return sum(1 for r in self.enemies if r.passed)

    @property
    def total_examples(self) -> int:
        return len(self.allies) + len(self.enemies)

    @property
    def total_passed(self) -> int:
        return self.ally_pass_count + self.enemy_pass_count

    def status_line(self) -> str:
        """Compact one-liner suitable for the status bar."""
        if not self.valid:
            return f"⚠ invalid regex: {self.error}"
        if self.total_examples == 0:
            return "no examples yet — add allies and enemies"
        return (
            f"allies {self.ally_pass_count}/{len(self.allies)} · "
            f"enemies {self.enemy_pass_count}/{len(self.enemies)} · "
            f"total {self.total_passed}/{self.total_examples}"
        )


# ---- internals -------------------------------------------------------------


@lru_cache(maxsize=128)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


# Catastrophic-backtracking heuristics.  We can't prove ReDoS in the general
# case (it's basically undecidable) but a handful of patterns are notorious
# for triggering exponential blow-up in PCRE-style engines.  Flag those so
# the dojo can show a banner before the user gets bitten in prod.
_REDOS_PATTERNS: tuple[tuple[str, str], ...] = (
    # (a+)+ , (a*)*, (.+)+ etc. — quantified group with an inner quantifier.
    (
        r"\((?:\?[:=!])?[^()]*[+*][^()]*\)[+*]",
        "nested quantifiers like (a+)+ can backtrack exponentially",
    ),
    # Overlapping alternation: (a|a)+, (a|ab)+, (.|.)+
    (
        r"\((?:\?[:=!])?[^()|]+\|[^()]*\)[+*]",
        "alternation with overlapping branches inside a quantifier is a classic ReDoS trap",
    ),
    # .*.* or .+.+ — adjacent greedy wildcards
    (r"\.[+*]\.[+*]", "adjacent greedy wildcards (.*.*) can backtrack badly"),
)
_REDOS_COMPILED: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p), msg) for p, msg in _REDOS_PATTERNS
)


def redos_risk(pattern: str) -> str | None:
    """Return a human-readable warning if ``pattern`` smells ReDoS-prone.

    Returns ``None`` when nothing obvious trips.  This is a heuristic, not
    a proof — false positives and false negatives both happen.  The goal is
    to nudge the user, not to gate execution.
    """
    if not pattern:
        return None
    for rx, msg in _REDOS_COMPILED:
        if rx.search(pattern):
            return msg
    return None


def split_examples(blob: str) -> list[str]:
    """Split a multi-line example pane into individual non-empty examples.

    Lines starting with ``#`` are treated as comments (the panes ship with
    placeholder hints).  Surrounding whitespace on each line is preserved so
    "the space matters" stays honest, but the line separator itself is not.
    """
    examples: list[str] = []
    for raw in blob.splitlines():
        if not raw.strip():
            continue
        if raw.lstrip().startswith("#"):
            continue
        examples.append(raw)
    return examples


def _score(
    pattern: re.Pattern[str],
    texts: Iterable[str],
    *,
    should_match: bool,
) -> tuple[ExampleResult, ...]:
    out: list[ExampleResult] = []
    for text in texts:
        matched = pattern.search(text) is not None
        passed = matched if should_match else not matched
        out.append(ExampleResult(text=text, matched=matched, passed=passed))
    return tuple(out)


# ---- public API ------------------------------------------------------------


def evaluate(
    pattern: str,
    allies: str | Iterable[str],
    enemies: str | Iterable[str],
) -> EvaluationResult:
    """Evaluate ``pattern`` against allies and enemies.

    ``allies`` / ``enemies`` may be a newline-blob from the TUI panes or an
    already-split iterable.  Empty / commented lines are ignored.

    Invalid regex never raises — the result is marked ``valid=False`` and
    every example is reported as ``passed=False`` so the UI can show the user
    that nothing scored.
    """
    ally_list = split_examples(allies) if isinstance(allies, str) else [s for s in allies if s]
    enemy_list = split_examples(enemies) if isinstance(enemies, str) else [s for s in enemies if s]

    warning = redos_risk(pattern)

    if not pattern:
        return EvaluationResult(
            pattern=pattern,
            valid=False,
            error="empty pattern",
            allies=tuple(ExampleResult(t, False, False) for t in ally_list),
            enemies=tuple(ExampleResult(t, False, False) for t in enemy_list),
            redos_warning=warning,
        )

    try:
        compiled = _compile(pattern)
    except re.error as exc:
        return EvaluationResult(
            pattern=pattern,
            valid=False,
            error=str(exc),
            allies=tuple(ExampleResult(t, False, False) for t in ally_list),
            enemies=tuple(ExampleResult(t, False, False) for t in enemy_list),
            redos_warning=warning,
        )

    return EvaluationResult(
        pattern=pattern,
        valid=True,
        error=None,
        allies=_score(compiled, ally_list, should_match=True),
        enemies=_score(compiled, enemy_list, should_match=False),
        redos_warning=warning,
    )
