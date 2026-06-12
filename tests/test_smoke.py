"""Smoke tests — make sure the package imports and the CLI prints something."""

from __future__ import annotations

from typer.testing import CliRunner

import regex_rumble
from regex_rumble.cli import app

runner = CliRunner()


def test_version_constant() -> None:
    assert isinstance(regex_rumble.__version__, str)
    assert regex_rumble.__version__.count(".") >= 1


def test_cli_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert regex_rumble.__version__ in result.stdout


def test_cli_banner() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "regex-rumble" in result.stdout
