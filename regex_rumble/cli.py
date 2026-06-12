"""Typer entrypoint for regex-rumble."""

from __future__ import annotations

import typer

from . import __version__

app = typer.Typer(
    add_completion=False,
    help="A terminal dojo for regex training. Write a pattern. The sensei tries to defeat it.",
)

BANNER = r"""
                                                _     _
  _ __ ___  __ _  _____  __      _ __ _   _ _ __ ___ | |__ | | ___
 | '__/ _ \/ _` |/ _ \ \/ /_____| '__| | | | '_ ` _ \| '_ \| |/ _ \
 | | |  __/ (_| |  __/>  <______| |  | |_| | | | | | | |_) | |  __/
 |_|  \___|\__, |\___/_/\_\     |_|   \__,_|_| |_| |_|_.__/|_|\___|
           |___/                                                    🥋
"""


def _print_banner() -> None:
    typer.echo(BANNER)
    typer.echo(f"  regex-rumble v{__version__} — pre-alpha")
    typer.echo("  Dojo not built yet. Track progress: https://github.com/rwrife/regex-rumble")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", help="Print version and exit.", is_eager=True
    ),
) -> None:
    """Run the regex-rumble dojo (or show version)."""
    if version:
        typer.echo(f"regex-rumble {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        _print_banner()


if __name__ == "__main__":  # pragma: no cover
    app()
