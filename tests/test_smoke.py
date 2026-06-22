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
    result = runner.invoke(app, ["--banner"])
    assert result.exit_code == 0
    assert "regex-rumble" in result.stdout


def test_cli_speedrun_headless() -> None:
    result = runner.invoke(app, ["speedrun", "--count", "3", "--seed", "7", "--headless"])
    assert result.exit_code == 0
    assert "pack:" in result.stdout
    assert "seed=7" in result.stdout
    # Three numbered lineup entries.
    assert " 1." in result.stdout
    assert " 3." in result.stdout
