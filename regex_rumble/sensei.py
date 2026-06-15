"""The sensei: an adversarial example generator.

Given the user's current pattern plus the allies/enemies they've already
listed, the sensei produces a small batch of new edge-case strings labeled
``should-match`` or ``should-not-match``. Those examples are then re-fed
through :mod:`regex_rumble.engine`; anything the pattern mis-classifies
counts as damage taken.

Providers
---------
* :class:`OpenAIProvider` — talks to any OpenAI-compatible chat-completions
  endpoint via ``httpx``. Configured from env (``OPENAI_API_KEY``,
  ``OPENAI_BASE_URL``, ``REGEX_RUMBLE_MODEL``).
* :class:`CannedProvider` — deterministic, offline fallback. Used when no
  API key is configured or the network call fails. Also the default in
  tests.
* :class:`MockProvider` — tests inject a fixed list of attacks.

The module never raises on a failed LLM call: it logs and degrades to the
canned attack list so the dojo stays playable offline.
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

import httpx

log = logging.getLogger(__name__)

Label = Literal["should-match", "should-not-match"]

MAX_ATTACKS = 5
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"


# ---- data shapes -----------------------------------------------------------


@dataclass(frozen=True)
class Attack:
    """One adversarial example produced by the sensei."""

    text: str
    label: Label
    rationale: str = ""

    @property
    def should_match(self) -> bool:
        return self.label == "should-match"


@dataclass(frozen=True)
class AttackReport:
    """Outcome of running a batch of attacks through the user's pattern."""

    pattern: str
    attacks: tuple[Attack, ...]
    correct: tuple[Attack, ...]   # pattern classified these correctly → XP
    misses: tuple[Attack, ...]    # pattern mis-classified these → damage
    provider: str
    used_fallback: bool

    @property
    def xp(self) -> int:
        return len(self.correct)

    @property
    def damage(self) -> int:
        return len(self.misses)

    def summary(self) -> str:
        if not self.attacks:
            return f"sensei ({self.provider}) had nothing to throw"
        return (
            f"sensei ({self.provider}) threw {len(self.attacks)} — "
            f"+{self.xp} XP, -{self.damage} HP"
            + (" [offline canned attacks]" if self.used_fallback else "")
        )


# ---- providers -------------------------------------------------------------


class AttackProvider(Protocol):
    name: str

    def attack(
        self, pattern: str, allies: Sequence[str], enemies: Sequence[str]
    ) -> list[Attack]: ...


class MockProvider:
    """Returns a fixed list. For tests."""

    name = "mock"

    def __init__(self, attacks: Iterable[Attack]) -> None:
        self._attacks = list(attacks)

    def attack(
        self, pattern: str, allies: Sequence[str], enemies: Sequence[str]
    ) -> list[Attack]:
        return list(self._attacks)


class CannedProvider:
    """Offline fallback. Mutates known examples into plausible edge cases."""

    name = "canned"

    # Generic edge-case strings that defeat naive patterns of many shapes.
    _GENERIC = (
        ("", "should-not-match"),
        (" ", "should-not-match"),
        ("\t", "should-not-match"),
        ("\n", "should-not-match"),
        ("AAAA", "should-not-match"),
        ("0", "should-not-match"),
        ("null", "should-not-match"),
        ("undefined", "should-not-match"),
        ("'; DROP TABLE--", "should-not-match"),
        ("😀", "should-not-match"),
    )

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)

    def attack(
        self, pattern: str, allies: Sequence[str], enemies: Sequence[str]
    ) -> list[Attack]:
        candidates: list[Attack] = []

        # Mutate each ally by trimming, casing, padding.
        for ally in allies:
            if ally:
                candidates.append(
                    Attack(ally.upper(), "should-match", "ally with case flipped")
                )
                candidates.append(
                    Attack(f" {ally} ", "should-match", "ally with whitespace padding")
                )
                if len(ally) > 1:
                    candidates.append(
                        Attack(ally[:-1], "should-not-match", "ally with last char stripped")
                    )

        # Sprinkle in generic adversarial strings the pattern probably hasn't seen.
        seen = set(enemies)
        for text, label in self._GENERIC:
            if text not in seen:
                candidates.append(Attack(text, label, "canned edge case"))  # type: ignore[arg-type]

        self._rng.shuffle(candidates)
        return candidates[:MAX_ATTACKS]


class OpenAIProvider:
    """Calls an OpenAI-compatible chat-completions endpoint."""

    name = "openai"

    SYSTEM_PROMPT = (
        "You are the sensei in a regex training dojo. The student gives you "
        "their current regex pattern plus the example strings they consider "
        "allies (must match) and enemies (must not match). Produce up to "
        f"{MAX_ATTACKS} NEW adversarial example strings that probe the edges "
        "of their pattern. Mix should-match and should-not-match cases. "
        "Respond with strict JSON of the form "
        '{"attacks":[{"text":"...","label":"should-match","rationale":"..."}]}. '
        "No prose outside the JSON object."
    )

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._client = client

    def _build_user_prompt(
        self, pattern: str, allies: Sequence[str], enemies: Sequence[str]
    ) -> str:
        return (
            f"PATTERN:\n{pattern}\n\n"
            f"ALLIES (must match):\n" + ("\n".join(allies) or "(none)") + "\n\n"
            "ENEMIES (must not match):\n" + ("\n".join(enemies) or "(none)") + "\n\n"
            f"Generate up to {MAX_ATTACKS} new adversarial examples."
        )

    def attack(
        self, pattern: str, allies: Sequence[str], enemies: Sequence[str]
    ) -> list[Attack]:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": self._build_user_prompt(pattern, allies, enemies)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.9,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        url = f"{self._base_url}/chat/completions"

        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            resp = client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        finally:
            if self._client is None:
                client.close()

        content = data["choices"][0]["message"]["content"]
        return _parse_attacks(content)


# ---- parsing / selection helpers ------------------------------------------


def _parse_attacks(blob: str) -> list[Attack]:
    """Best-effort parse of the LLM JSON response."""
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        # Some models wrap in code fences despite instructions.
        m = re.search(r"\{.*\}", blob, re.DOTALL)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []

    raw = data.get("attacks") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return []

    out: list[Attack] = []
    for item in raw[:MAX_ATTACKS]:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        label = item.get("label")
        if not isinstance(text, str) or label not in ("should-match", "should-not-match"):
            continue
        rationale = item.get("rationale") if isinstance(item.get("rationale"), str) else ""
        out.append(Attack(text=text, label=label, rationale=rationale or ""))
    return out


def select_provider(*, env: dict[str, str] | None = None) -> AttackProvider:
    """Pick an LLM provider based on env vars, falling back to canned."""
    e = env if env is not None else os.environ
    api_key = e.get("OPENAI_API_KEY")
    if not api_key:
        return CannedProvider()
    return OpenAIProvider(
        api_key=api_key,
        base_url=e.get("OPENAI_BASE_URL", DEFAULT_BASE_URL),
        model=e.get("REGEX_RUMBLE_MODEL", DEFAULT_MODEL),
    )


# ---- the attack loop -------------------------------------------------------


def _classify(pattern: str, attacks: Sequence[Attack]) -> tuple[list[Attack], list[Attack]]:
    """Split attacks into (correct, misses) by running them through ``pattern``."""
    try:
        compiled = re.compile(pattern) if pattern else None
    except re.error:
        compiled = None
    correct: list[Attack] = []
    misses: list[Attack] = []
    for a in attacks:
        if compiled is None:
            # Invalid / empty pattern matches nothing → only should-not-match attacks pass.
            matched = False
        else:
            matched = compiled.search(a.text) is not None
        ok = matched == a.should_match
        (correct if ok else misses).append(a)
    return correct, misses


def run_attack(
    pattern: str,
    allies: Sequence[str],
    enemies: Sequence[str],
    *,
    provider: AttackProvider | None = None,
) -> AttackReport:
    """Run one full sensei attack and tally damage/XP.

    Never raises. On network or provider failure, falls back to the canned
    provider so the dojo stays playable.
    """
    primary = provider or select_provider()
    used_fallback = False
    provider_name = primary.name
    failed = False

    try:
        attacks = primary.attack(pattern, allies, enemies)
    except Exception as exc:  # noqa: BLE001 — provider-agnostic safety net
        log.warning("sensei provider %s failed: %s", primary.name, exc)
        attacks = []
        failed = True

    if failed and not isinstance(primary, CannedProvider):
        log.info("falling back to canned sensei attacks")
        fallback = CannedProvider()
        try:
            attacks = fallback.attack(pattern, allies, enemies)
        except Exception as exc:  # noqa: BLE001
            log.warning("canned provider also failed: %s", exc)
            attacks = []
        used_fallback = True
        provider_name = f"{primary.name}→canned"

    correct, misses = _classify(pattern, attacks)
    return AttackReport(
        pattern=pattern,
        attacks=tuple(attacks),
        correct=tuple(correct),
        misses=tuple(misses),
        provider=provider_name,
        used_fallback=used_fallback,
    )
