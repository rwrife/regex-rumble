"""Sensei attack analytics: tag examples with feature vectors and surface
a heatmap of where the player's regex skills leak.

Each adversarial example is classified into a small set of *features* — broad
buckets like ``whitespace``, ``unicode``, ``boundary-whitespace``,
``regex-meta``, ``long-string`` etc. Counters live in ``state.json`` under
``analytics.misses`` and ``analytics.totals`` so we can compute miss-rates
across many sessions.

The classifier is intentionally a tiny stdlib heuristic — it doesn't try to
parse the *pattern* (that's harder and the user's job to learn). It looks at
the *example string* the sensei threw and asks: which regex features did this
string exercise? That's the dimension a player learns to harden.

Public API:
* :func:`feature_tags` — tag a single text.
* :func:`record_outcome` — bump misses/totals counters in a ``DojoState``.
* :func:`render_heatmap` — ASCII heatmap of miss-rates, color-graded.
* :func:`heatmap_payload` — JSON-friendly dict for ``--json``.
* :func:`reset_analytics` — wipe counters.

The module is pure stdlib (so it imports without textual/httpx).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid an import cycle with state.py at runtime
    from .state import DojoState

# Canonical feature list (display order). Keeping this stable keeps the
# heatmap rows deterministic across runs.
FEATURES: tuple[str, ...] = (
    "empty",
    "whitespace",
    "boundary-whitespace",
    "newline",
    "unicode",
    "digit",
    "alpha",
    "mixed-case",
    "punctuation",
    "regex-meta",
    "long-string",
    "ascii-only",
)

_PUNCT = set("!@#%&-_=:;,/.")
_META = set(r".^$*+?()[]{}|\\")


def feature_tags(text: str) -> frozenset[str]:
    """Classify ``text`` into the active feature buckets.

    Stable, deterministic, side-effect-free.
    """
    feats: set[str] = set()
    if text == "":
        feats.add("empty")
        return frozenset(feats)
    if any(c.isspace() for c in text):
        feats.add("whitespace")
    if "\n" in text or "\r" in text:
        feats.add("newline")
    if text[0].isspace() or text[-1].isspace():
        feats.add("boundary-whitespace")
    if any(ord(c) > 127 for c in text):
        feats.add("unicode")
    else:
        feats.add("ascii-only")
    if any(c.isdigit() for c in text):
        feats.add("digit")
    if any(c.isalpha() for c in text):
        feats.add("alpha")
    if any(c.isupper() for c in text) and any(c.islower() for c in text):
        feats.add("mixed-case")
    if any(c in _PUNCT for c in text):
        feats.add("punctuation")
    if any(c in _META for c in text):
        feats.add("regex-meta")
    if len(text) >= 20:
        feats.add("long-string")
    return frozenset(feats)


# ---- state helpers ----------------------------------------------------------


def _ensure_analytics(state: DojoState) -> dict[str, dict[str, int]]:
    """Return ``state.analytics`` after ensuring its sub-dicts exist."""
    a = state.analytics
    a.setdefault("misses", {})
    a.setdefault("totals", {})
    return a


def record_outcome(state: DojoState, text: str, *, missed: bool) -> frozenset[str]:
    """Bump per-feature counters for one classified example.

    Returns the feature set that was credited (handy for tests/UI).
    """
    tags = feature_tags(text)
    a = _ensure_analytics(state)
    totals = a["totals"]
    misses = a["misses"]
    for f in tags:
        totals[f] = totals.get(f, 0) + 1
        if missed:
            misses[f] = misses.get(f, 0) + 1
    return tags


def record_batch(
    state: DojoState,
    correct: Iterable[str],
    missed: Iterable[str],
) -> None:
    """Bulk version of :func:`record_outcome` for a whole attack batch."""
    for t in correct:
        record_outcome(state, t, missed=False)
    for t in missed:
        record_outcome(state, t, missed=True)


def reset_analytics(state: DojoState) -> None:
    """Wipe miss/total counters but leave HP/XP/belt alone."""
    state.analytics = {"misses": {}, "totals": {}}


# ---- heatmap rendering ------------------------------------------------------


@dataclass(frozen=True)
class HeatRow:
    feature: str
    misses: int
    totals: int

    @property
    def rate(self) -> float:
        return (self.misses / self.totals) if self.totals else 0.0


def _rows(state: DojoState) -> list[HeatRow]:
    a = _ensure_analytics(state)
    misses = a["misses"]
    totals = a["totals"]
    rows: list[HeatRow] = []
    for f in FEATURES:
        t = int(totals.get(f, 0))
        m = int(misses.get(f, 0))
        if t == 0 and m == 0:
            continue
        rows.append(HeatRow(feature=f, misses=m, totals=t))
    # Highest miss-rate first; break ties on raw misses then sample count.
    rows.sort(key=lambda r: (-r.rate, -r.misses, -r.totals, r.feature))
    return rows


# ANSI color buckets for the heatmap. Higher rate → hotter.
_COLOR_BUCKETS: tuple[tuple[float, str, str], ...] = (
    (0.0,  "\x1b[38;5;46m", "cool"),    # green
    (0.10, "\x1b[38;5;226m", "warm"),   # yellow
    (0.25, "\x1b[38;5;208m", "hot"),    # orange
    (0.50, "\x1b[38;5;196m", "blazing"),  # red
)
_RESET = "\x1b[0m"
_BAR_WIDTH = 20


def _bucket(rate: float) -> tuple[str, str]:
    pick = _COLOR_BUCKETS[0]
    for entry in _COLOR_BUCKETS:
        if rate >= entry[0]:
            pick = entry
    return pick[1], pick[2]


def _bar(rate: float) -> str:
    filled = int(round(rate * _BAR_WIDTH))
    filled = max(0, min(_BAR_WIDTH, filled))
    return "█" * filled + "·" * (_BAR_WIDTH - filled)


def render_heatmap(state: DojoState, *, color: bool = True) -> str:
    """Render an ASCII heatmap. Stable output for fixed counters."""
    rows = _rows(state)
    if not rows:
        return "no sensei attacks recorded yet — go fight some regex 🥋"

    lines = [
        "Regex weakness heatmap (miss rate per feature)",
        "─" * 56,
        f"  {'feature':<22}  {'bar':<20}  rate    n",
    ]
    for r in rows:
        rate_pct = f"{r.rate * 100:5.1f}%"
        bar = _bar(r.rate)
        if color:
            col, _ = _bucket(r.rate)
            bar = f"{col}{bar}{_RESET}"
        lines.append(
            f"  {r.feature:<22}  {bar}  {rate_pct}  {r.totals:>4}"
        )
    return "\n".join(lines)


def heatmap_payload(state: DojoState) -> dict[str, Any]:
    """JSON-friendly summary for ``regex-rumble stats --json``."""
    rows = _rows(state)
    return {
        "rows": [
            {
                "feature": r.feature,
                "misses": r.misses,
                "totals": r.totals,
                "rate": round(r.rate, 4),
            }
            for r in rows
        ],
        "features_known": list(FEATURES),
    }


# Convenience for the app: take a sensei AttackReport-shaped pair.
def record_attack_texts(
    state: DojoState,
    correct_texts: Sequence[str],
    missed_texts: Sequence[str],
) -> None:
    record_batch(state, correct_texts, missed_texts)


__all__ = [
    "FEATURES",
    "HeatRow",
    "feature_tags",
    "heatmap_payload",
    "record_attack_texts",
    "record_batch",
    "record_outcome",
    "render_heatmap",
    "reset_analytics",
]


# Silence "unused import" linters in environments without re — kept for future use.
_ = re
