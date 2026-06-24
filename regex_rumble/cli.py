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
    serve_mcp: bool = typer.Option(
        False,
        "--serve-mcp",
        help="Run as an MCP server on stdio (exposes `evaluate` + `attack` tools).",
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
    if serve_mcp:
        from .mcp import run_server

        run_server()
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


@app.command("lint")
def lint_pattern(
    pattern: str = typer.Argument(..., help="Regex pattern to lint."),
    flavor: str = typer.Option(
        "python",
        "--flavor",
        "-f",
        help="Target regex flavor: python, pcre, re2, js, go, rust, dotnet.",
    ),
) -> None:
    """Lint a pattern for compatibility footguns in a target regex flavor."""
    from .flavors import describe, lint

    try:
        warnings = lint(pattern, flavor)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"flavor: {describe(flavor)}")
    if not warnings:
        typer.echo("no compatibility issues found ✓")
        return
    for w in warnings:
        typer.echo("  - " + w.format())
    raise typer.Exit(code=1)


@app.command("redos")
def redos_dojo(
    pattern: str = typer.Argument(..., help="Regex pattern to probe for ReDoS."),
    timeout: float = typer.Option(
        1.0, "--timeout", "-t", help="Per-step watchdog timeout (seconds)."
    ),
    max_len: int = typer.Option(
        28, "--max-len", "-n", help="Largest pump length to try."
    ),
    step: int = typer.Option(
        4, "--step", "-s", help="Pump-length increment."
    ),
) -> None:
    """Hunt catastrophic backtracking: static scan + timed pump trace."""
    from .redos import detect, render_report, trace

    if step <= 0 or max_len <= 0:
        typer.echo("--step and --max-len must be positive", err=True)
        raise typer.Exit(code=2)
    lengths = tuple(range(step, max_len + 1, step))
    findings = detect(pattern)
    steps = trace(pattern, lengths=lengths, timeout_s=timeout)
    typer.echo(render_report(pattern, findings, steps))
    if any(s.timed_out for s in steps) or any(f.severity >= 3 for f in findings):
        raise typer.Exit(code=1)


@app.command("speedrun")
def speedrun_cmd(
    count: int = typer.Option(10, "--count", "-n", help="Number of rounds in the gauntlet."),
    bundle: str | None = typer.Option(
        None, "--bundle", "-b", help="Pack id or path to a JSON challenge pack."
    ),
    seed: int | None = typer.Option(
        None, "--seed", help="Deterministic challenge seed (also used for PR key)."
    ),
    headless: bool = typer.Option(
        False, "--headless", help="Print pack + selection without launching the TUI."
    ),
) -> None:
    """Race the clock through N regex challenges (M5 backlog item)."""
    from .speedrun import build_run, load_prs, pr_key

    if count <= 0:
        typer.echo("--count must be positive", err=True)
        raise typer.Exit(code=2)
    pack_source = bundle or "speedrun_default"
    try:
        run = build_run(count=count, seed=seed, pack_source=pack_source)
    except Exception as exc:  # pragma: no cover - defensive
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if headless:
        typer.echo(f"pack: {run.pack.name} ({run.pack.id})")
        typer.echo(f"count={run.count} seed={run.seed}")
        for i, c in enumerate(run.challenges, 1):
            typer.echo(f"  {i:>2}. {c.name} — {c.hint}")
        prs = load_prs()
        best = prs.get(pr_key(run.pack.id, run.count, run.seed))
        if best is not None:
            from .speedrun import format_split

            typer.echo(f"current PR: {format_split(best)}")
        return
    from .app import run_speedrun as _run

    _run(run)


@app.command("stats")
def stats_cmd(
    json_out: bool = typer.Option(
        False, "--json", help="Emit a JSON payload instead of the heatmap."
    ),
    no_color: bool = typer.Option(False, "--no-color", help="Disable ANSI colors in the heatmap."),
    reset: bool = typer.Option(False, "--reset", help="Wipe analytics counters (confirm prompt)."),
    force: bool = typer.Option(False, "--force", help="Skip the confirm prompt for --reset."),
) -> None:
    """Show a heatmap of which regex features you keep getting wrong."""
    from .analytics import heatmap_payload, render_heatmap, reset_analytics
    from .state import default_state_path, load_state, save_state

    path = default_state_path()
    state = load_state(path)

    if reset:
        if not force:
            typer.confirm(
                "Reset all heatmap analytics counters? This can't be undone.",
                abort=True,
            )
        reset_analytics(state)
        save_state(state, path)
        typer.echo("analytics counters reset ✓")
        return

    if json_out:
        import json as _json

        typer.echo(_json.dumps(heatmap_payload(state), indent=2, sort_keys=True))
        return

    typer.echo(render_heatmap(state, color=not no_color))


if __name__ == "__main__":  # pragma: no cover
    app()
