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
    banner: bool = typer.Option(
        False, "--banner", help="Print the banner and exit (skip the TUI)."
    ),
    daily: bool = typer.Option(
        False, "--daily", help="Load today's seeded daily challenge into the dojo."
    ),
    bundle: str | None = typer.Option(
        None,
        "--bundle",
        "-b",
        metavar="PATH_OR_URL",
        help="Load a shareable challenge bundle (file, regex-rumble:// URL, or https URL).",
    ),
) -> None:
    """Run the regex-rumble dojo (or show version)."""
    if version:
        typer.echo(f"regex-rumble {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is not None:
        return
    if banner:
        _print_banner()
        raise typer.Exit()
    # Default: launch the TUI dojo shell.
    from .app import run as _run_app

    _run_app(daily=daily, bundle=bundle)


@app.command("export-bundle")
def export_bundle(
    out: str = typer.Argument(..., help="Output path for the JSON bundle file."),
    name: str = typer.Option(..., "--name", help="Challenge name."),
    hint: str = typer.Option("", "--hint", help="One-line description / hint."),
    ally: list[str] = typer.Option(  # noqa: B008
        [], "--ally", "-a", help="Ally string (repeatable). Must match."
    ),
    enemy: list[str] = typer.Option(  # noqa: B008
        [], "--enemy", "-e", help="Enemy string (repeatable). Must NOT match."
    ),
    goal: str | None = typer.Option(
        None, "--goal", help="Optional goal pattern (leave unset for blind challenges)."
    ),
    author: str | None = typer.Option(None, "--author", help="Bundle author."),
    print_url: bool = typer.Option(
        False, "--print-url", help="Also print a shareable regex-rumble:// URL."
    ),
) -> None:
    """Write a shareable challenge bundle to disk."""
    from .bundle import ChallengeBundle

    challenge = ChallengeBundle(
        name=name,
        hint=hint,
        allies=tuple(ally),
        enemies=tuple(enemy),
        goal_pattern=goal,
        author=author,
    )
    path = challenge.write_file(out)
    typer.echo(f"wrote {path}")
    if print_url:
        typer.echo(challenge.to_url())


@app.command("share-bundle")
def share_bundle(
    source: str = typer.Argument(..., help="Bundle path or regex-rumble:// URL."),
) -> None:
    """Print a shareable regex-rumble:// URL for a bundle."""
    from .bundle import load_bundle

    typer.echo(load_bundle(source).to_url())


if __name__ == "__main__":  # pragma: no cover
    app()
