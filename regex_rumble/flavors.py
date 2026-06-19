"""Regex flavor registry + per-flavor footgun linter.

A first slice of issue #8 (language packs). We don't yet shell out to native
runtimes — Python's ``re`` keeps doing the actual matching — but we expose
the *language* of the user's target regex flavor so the dojo can:

* warn about constructs that don't exist (or behave differently) in that
  flavor (e.g. lookbehind in RE2, possessive quantifiers in JS, ``\\K`` in
  Python/RE2…),
* lay the groundwork for native evaluators in a follow-up slice.

The catalog below is intentionally conservative: each rule covers a
well-known compatibility footgun, not every edge case. False positives are
worse than no warning here, because they undermine trust in the dojo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

FlavorName = Literal["python", "pcre", "re2", "js", "go", "rust", "dotnet"]

# Order matters: the first entry is the default and is what the picker shows
# at the top.
FLAVORS: tuple[FlavorName, ...] = (
    "python",
    "pcre",
    "re2",
    "js",
    "go",
    "rust",
    "dotnet",
)

_ALIASES: dict[str, FlavorName] = {
    "py": "python",
    "python": "python",
    "pcre": "pcre",
    "pcre2": "pcre",
    "perl": "pcre",
    "re2": "re2",
    "google-re2": "re2",
    "js": "js",
    "javascript": "js",
    "ecmascript": "js",
    "node": "js",
    "go": "go",
    "golang": "go",
    "rust": "rust",
    "regex-rs": "rust",
    "dotnet": "dotnet",
    ".net": "dotnet",
    "csharp": "dotnet",
    "c#": "dotnet",
}


def normalize(name: str | None) -> FlavorName:
    """Return the canonical flavor name, defaulting to ``python``.

    Accepts common aliases (``perl``, ``js``, ``.NET``…). Unknown names
    raise ``ValueError`` so the CLI can surface a clear error rather than
    silently downgrading.
    """
    if name is None:
        return "python"
    key = name.strip().lower()
    if not key:
        return "python"
    try:
        return _ALIASES[key]
    except KeyError as exc:
        choices = ", ".join(sorted(set(_ALIASES.values())))
        raise ValueError(f"unknown regex flavor {name!r}; try one of: {choices}") from exc


@dataclass(frozen=True)
class FlavorWarning:
    """One linter finding."""

    flavor: FlavorName
    message: str
    snippet: str  # the offending substring, for highlighting

    def format(self) -> str:
        return f"[{self.flavor}] {self.message} (near {self.snippet!r})"


@dataclass(frozen=True)
class _Rule:
    pattern: re.Pattern[str]
    message: str
    flavors: frozenset[FlavorName]


def _rule(pat: str, message: str, *flavors: FlavorName) -> _Rule:
    return _Rule(re.compile(pat), message, frozenset(flavors))


# Each rule says: "if the user's pattern contains <regex>, warn that <flavor(s)>
# will reject or mis-handle it." Keep these surgical.
_RULES: tuple[_Rule, ...] = (
    # RE2 / Go are RE2-based: no backreferences, no lookaround, no
    # possessive quantifiers, no atomic groups.
    _rule(r"\\[1-9]", "backreferences are not supported", "re2", "go"),
    _rule(r"\(\?<?[=!]", "lookaround assertions are not supported", "re2", "go"),
    _rule(r"\(\?>", "atomic groups are not supported", "re2", "go", "js", "rust", "python"),
    _rule(r"[+*?}]\+", "possessive quantifiers are not supported", "re2", "go", "js", "python"),
    # Rust's `regex` crate also rejects lookaround/backrefs by default.
    _rule(r"\\[1-9]", "backreferences are not supported by the default `regex` crate", "rust"),
    _rule(
        r"\(\?<?[=!]",
        "lookaround assertions are not supported by the default `regex` crate",
        "rust",
    ),
    # JavaScript: no \K, no named-capture with the Python `(?P<name>...)` form,
    # no inline flag groups `(?i:...)`.
    _rule(r"\\K", r"`\K` is not supported", "js", "re2", "go", "python", "dotnet", "rust"),
    _rule(r"\(\?P<", "use `(?<name>...)` instead of `(?P<name>...)`", "js", "dotnet", "rust"),
    _rule(r"\(\?[a-zA-Z]+:", "inline flag groups `(?i:...)` are not supported", "js"),
    # .NET supports most things; flag conditional `(?(name)yes|no)` is .NET-only.
    _rule(r"\(\?\(", "conditional patterns `(?(cond)yes|no)` are a .NET / PCRE extension",
          "re2", "go", "js", "rust", "python"),
    # Python: no possessive quantifiers in stdlib `re` until 3.11 — already covered.
    # PCRE / Python differ on `\A`/`\Z` semantics rarely; not lintable cheaply.
)


def lint(pattern: str, flavor: str | FlavorName | None = None) -> list[FlavorWarning]:
    """Return per-flavor compatibility warnings for ``pattern``.

    Empty pattern → empty list. Unknown flavor → ``ValueError`` (via
    :func:`normalize`).
    """
    if not pattern:
        return []
    target = normalize(flavor) if not isinstance(flavor, str) or flavor not in FLAVORS else flavor  # type: ignore[comparison-overlap]
    # Re-normalize once more so callers can pass aliases through.
    target = normalize(target)

    out: list[FlavorWarning] = []
    seen: set[tuple[str, str]] = set()  # (message, snippet) — de-dupe overlapping rules
    for rule in _RULES:
        if target not in rule.flavors:
            continue
        for m in rule.pattern.finditer(pattern):
            key = (rule.message, m.group(0))
            if key in seen:
                continue
            seen.add(key)
            out.append(FlavorWarning(flavor=target, message=rule.message, snippet=m.group(0)))
    return out


def describe(flavor: str | FlavorName | None) -> str:
    """Human-readable label for a flavor (used in the status bar)."""
    target = normalize(flavor)
    labels: dict[FlavorName, str] = {
        "python": "Python re",
        "pcre": "PCRE / Perl",
        "re2": "Google RE2",
        "js": "JavaScript",
        "go": "Go regexp",
        "rust": "Rust regex",
        "dotnet": ".NET Regex",
    }
    return labels[target]
