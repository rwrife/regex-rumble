"""Tests for the regex-flavor compatibility linter."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from regex_rumble.cli import app
from regex_rumble.flavors import FLAVORS, describe, lint, normalize


def test_normalize_aliases() -> None:
    assert normalize("perl") == "pcre"
    assert normalize("JavaScript") == "js"
    assert normalize(".NET") == "dotnet"
    assert normalize(None) == "python"
    assert normalize("") == "python"


def test_normalize_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown regex flavor"):
        normalize("brainfuck")


def test_re2_rejects_lookaround_and_backrefs() -> None:
    warnings = lint(r"(?=foo)\1", "re2")
    msgs = [w.message for w in warnings]
    assert any("lookaround" in m for m in msgs)
    assert any("backreferences" in m for m in msgs)


def test_python_accepts_lookaround() -> None:
    # Python's `re` supports lookaround — no warning for that on the
    # python flavor.
    warnings = lint(r"(?=foo)bar", "python")
    assert all("lookaround" not in w.message for w in warnings)


def test_js_named_capture_warning() -> None:
    warnings = lint(r"(?P<year>\d{4})", "js")
    assert any("(?<name>...)" in w.message for w in warnings)


def test_empty_pattern_no_warnings() -> None:
    assert lint("", "python") == []


def test_every_flavor_has_a_label() -> None:
    for f in FLAVORS:
        assert describe(f)


def test_cli_lint_clean() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lint", r"^\d+$", "--flavor", "re2"])
    assert result.exit_code == 0, result.output
    assert "no compatibility issues" in result.output


def test_cli_lint_warns_and_exits_nonzero() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lint", r"(?=foo)bar", "--flavor", "re2"])
    assert result.exit_code == 1
    assert "lookaround" in result.output


def test_cli_lint_unknown_flavor() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lint", "x", "--flavor", "klingon"])
    assert result.exit_code == 2
    assert "unknown regex flavor" in result.output
