"""Textual App for the regex-rumble dojo.

M2: three-pane shell with focus management.
M3: live regex evaluation — red/green dots next to each example, status bar
with pass/fail tallies, graceful handling of invalid patterns.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static, TextArea

from . import __version__
from .bundle import ChallengeBundle, load_bundle
from .engine import EvaluationResult, ExampleResult, evaluate
from .sensei import AttackProvider, AttackReport, run_attack
from .state import (
    DailyChallenge,
    DojoState,
    load_state,
    save_state,
)

EMPTY_PATTERN = ""
EMPTY_ALLIES = "# One ally string per line — must MATCH.\n"
EMPTY_ENEMIES = "# One enemy string per line — must NOT match.\n"

PASS_DOT = "🟢"
FAIL_DOT = "🔴"


def _format_results(results: tuple[ExampleResult, ...], *, valid: bool) -> str:
    if not results:
        return "(no examples yet)"
    lines: list[str] = []
    for r in results:
        if not valid:
            dot = "·"
        else:
            dot = PASS_DOT if r.passed else FAIL_DOT
        # Trim long lines so the side column stays readable.
        text = r.text if len(r.text) <= 40 else r.text[:37] + "…"
        lines.append(f"{dot} {text}")
    return "\n".join(lines)


class DojoPane(Vertical):
    """A titled pane wrapping a TextArea editor, optionally with a results column."""

    DEFAULT_CSS = """
    DojoPane {
        border: round $primary;
        padding: 0 1;
        width: 1fr;
        height: 1fr;
    }
    DojoPane.-focused {
        border: round $accent;
    }
    DojoPane > .pane-title {
        color: $accent;
        text-style: bold;
        padding: 0 0 1 0;
    }
    DojoPane > .pane-body {
        height: 1fr;
    }
    DojoPane TextArea {
        height: 1fr;
        border: none;
    }
    DojoPane .results-col {
        width: 24;
        padding: 0 0 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        title: str,
        placeholder: str,
        pane_id: str,
        *,
        with_results: bool = False,
    ) -> None:
        super().__init__(id=pane_id)
        self._title = title
        self._placeholder = placeholder
        self._with_results = with_results

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="pane-title")
        with Horizontal(classes="pane-body"):
            yield TextArea(self._placeholder, id=f"{self.id}-editor")
            if self._with_results:
                yield Static("(no examples yet)", id=f"{self.id}-results", classes="results-col")

    def focus_editor(self) -> None:
        editor = self.query_one(TextArea)
        editor.focus()

    def editor_text(self) -> str:
        return self.query_one(TextArea).text

    def set_results(self, text: str) -> None:
        if not self._with_results:
            return
        self.query_one(f"#{self.id}-results", Static).update(text)


class HelpScreen(ModalScreen):
    """Tiny modal listing key bindings."""

    BINDINGS = [Binding("escape,question_mark,q", "dismiss", "Close")]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > Vertical {
        width: 60;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    HelpScreen .help-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    """

    HELP_TEXT = (
        "tab          cycle focus forward\n"
        "shift+tab    cycle focus backward\n"
        "1 / 2 / 3    jump to Pattern / Allies / Enemies\n"
        "s            sensei attack (adversarial examples)\n"
        "r            reset round (full HP, keep XP/belt)\n"
        "e            end-of-round summary\n"
        "?            toggle this help\n"
        "q            quit\n"
    )

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("regex-rumble — key bindings", classes="help-title")
            yield Static(self.HELP_TEXT)
            yield Static("\n(press esc, ?, or q to close)")

    def action_dismiss(self, result: object | None = None) -> None:  # type: ignore[override]
        self.app.pop_screen()


class BeltPromotionScreen(ModalScreen):
    """Tiny celebratory modal shown when the player crosses a belt threshold."""

    BINDINGS = [Binding("escape,enter,space,q", "dismiss", "Close")]

    DEFAULT_CSS = """
    BeltPromotionScreen {
        align: center middle;
    }
    BeltPromotionScreen > Vertical {
        width: 50;
        height: auto;
        border: thick $success;
        background: $surface;
        padding: 1 2;
    }
    BeltPromotionScreen .belt-title {
        text-style: bold;
        color: $success;
        padding-bottom: 1;
    }
    """

    def __init__(self, old_belt: str, new_belt: str) -> None:
        super().__init__()
        self._old = old_belt
        self._new = new_belt

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("🎉  BELT PROMOTION  🎉", classes="belt-title")
            yield Static(f"{self._old} → {self._new}")
            yield Static("\nKeep training. (press any key)")

    def action_dismiss(self, result: object | None = None) -> None:  # type: ignore[override]
        self.app.pop_screen()


class EndOfRoundScreen(ModalScreen):
    """Round summary: belt, HP, XP, streaks, totals."""

    BINDINGS = [Binding("escape,enter,space,q", "dismiss", "Close")]

    DEFAULT_CSS = """
    EndOfRoundScreen {
        align: center middle;
    }
    EndOfRoundScreen > Vertical {
        width: 60;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    EndOfRoundScreen .summary-title {
        text-style: bold;
        color: $accent;
        padding-bottom: 1;
    }
    """

    def __init__(self, state: DojoState, *, outcome: object | None = None) -> None:
        super().__init__()
        self._state = state
        self._outcome = outcome

    def compose(self) -> ComposeResult:
        s = self._state
        belt = s.belt
        nxt = s.xp_to_next()
        belt_line = (
            f"{belt.emoji} {belt.name} belt (max rank)"
            if nxt is None
            else f"{belt.emoji} {belt.name} belt — {nxt} XP to next"
        )
        lines = [
            belt_line,
            f"HP {s.hp}/{s.max_hp}    XP {s.xp}",
            f"wins {s.total_wins} · losses {s.total_losses}",
            f"streak {s.current_streak} (best {s.best_streak})",
        ]
        with Vertical():
            yield Static("⚔️  end of round  ⚔️", classes="summary-title")
            for line in lines:
                yield Static(line)
            yield Static("\n(press any key to keep training)")

    def action_dismiss(self, result: object | None = None) -> None:  # type: ignore[override]
        self.app.pop_screen()


class RegexRumbleApp(App):
    """Three-pane dojo with live regex evaluation."""

    CSS = """
    Screen {
        background: $background;
    }
    #panes {
        height: 1fr;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text;
    }
    #status-bar.-invalid {
        background: $error;
        color: $text;
    }
    #hp-bar {
        dock: bottom;
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $accent;
        text-style: bold;
    }
    #redos-banner {
        dock: bottom;
        height: 0;
        padding: 0 1;
        background: $warning;
        color: $text;
        text-style: bold;
    }
    #redos-banner.-visible {
        height: 1;
    }
    """

    TITLE = "regex-rumble"
    SUB_TITLE = f"dojo · v{__version__}"

    MAX_HP = 100

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("s", "sensei_attack", "Sensei attack"),
        Binding("r", "reset_round", "Reset round"),
        Binding("e", "end_of_round", "Summary"),
        Binding("tab", "focus_next_pane", "Next pane", show=False),
        Binding("shift+tab", "focus_prev_pane", "Prev pane", show=False),
        Binding("1", "focus_pane('pattern-pane')", "Pattern", show=False),
        Binding("2", "focus_pane('allies-pane')", "Allies", show=False),
        Binding("3", "focus_pane('enemies-pane')", "Enemies", show=False),
    ]

    PANE_ORDER = ("pattern-pane", "allies-pane", "enemies-pane")

    def __init__(
        self,
        *,
        sensei_provider: AttackProvider | None = None,
        state: DojoState | None = None,
        state_path: object | None = None,
        daily: DailyChallenge | None = None,
        bundle: ChallengeBundle | None = None,
    ) -> None:
        super().__init__()
        self._sensei_provider = sensei_provider
        self._state_path = state_path
        self._state: DojoState = state if state is not None else load_state(state_path)
        self._daily = daily
        self._bundle = bundle
        self._last_attack: AttackReport | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="panes"):
            yield DojoPane("⛩  Pattern", EMPTY_PATTERN, "pattern-pane")
            yield DojoPane(
                "🟢 Allies (must match)", EMPTY_ALLIES, "allies-pane", with_results=True
            )
            yield DojoPane(
                "🔴 Enemies (must NOT match)", EMPTY_ENEMIES, "enemies-pane", with_results=True
            )
        yield Static(self._hp_line(), id="hp-bar")
        yield Static("", id="redos-banner")
        yield Static("no examples yet — add allies and enemies", id="status-bar")
        yield Footer()

    def _hp_line(self) -> str:
        s = self._state
        belt = s.belt
        nxt = s.xp_to_next()
        if nxt is None:
            belt_part = f"{belt.emoji} {belt.name} belt (max)"
        else:
            belt_part = f"{belt.emoji} {belt.name} belt · {nxt} XP to next"
        return (
            f"HP {s.hp}/{s.max_hp} · XP {s.xp} · {belt_part} · "
            f"streak {s.current_streak} (best {s.best_streak})"
        )

    def on_mount(self) -> None:
        if self._daily is not None:
            self._prefill_daily(self._daily)
        if self._bundle is not None:
            self._prefill_bundle(self._bundle)
        self.action_focus_pane("pattern-pane")
        self._refresh_evaluation()

    def _prefill_daily(self, daily: DailyChallenge) -> None:
        allies_pane = self.query_one("#allies-pane", DojoPane).query_one(TextArea)
        enemies_pane = self.query_one("#enemies-pane", DojoPane).query_one(TextArea)
        header = f"# daily {daily.iso_date} — {daily.name}\n# {daily.hint}\n"
        allies_pane.text = header + "\n".join(daily.allies) + "\n"
        enemies_pane.text = (
            f"# daily {daily.iso_date} — reject these\n"
            + "\n".join(daily.enemies)
            + "\n"
        )

    def _prefill_bundle(self, bundle: ChallengeBundle) -> None:
        pattern_pane = self.query_one("#pattern-pane", DojoPane).query_one(TextArea)
        allies_pane = self.query_one("#allies-pane", DojoPane).query_one(TextArea)
        enemies_pane = self.query_one("#enemies-pane", DojoPane).query_one(TextArea)
        hint = f" — {bundle.hint}" if bundle.hint else ""
        header = f"# bundle: {bundle.name}{hint}\n"
        if bundle.goal_pattern is not None:
            pattern_pane.text = bundle.goal_pattern
        allies_pane.text = header + "\n".join(bundle.allies) + ("\n" if bundle.allies else "")
        enemies_pane.text = header + "\n".join(bundle.enemies) + ("\n" if bundle.enemies else "")

    # --- evaluation -----------------------------------------------------

    def _gather_text(self) -> tuple[str, str, str]:
        return (
            self.query_one("#pattern-pane", DojoPane).editor_text(),
            self.query_one("#allies-pane", DojoPane).editor_text(),
            self.query_one("#enemies-pane", DojoPane).editor_text(),
        )

    def _refresh_evaluation(self) -> EvaluationResult:
        pattern, allies, enemies = self._gather_text()
        # The pattern pane is a single-line concept; collapse to first non-empty
        # non-comment line so users can leave hint text in the textarea later.
        pattern_line = _first_pattern_line(pattern)
        result = evaluate(pattern_line, allies, enemies)
        self.query_one("#allies-pane", DojoPane).set_results(
            _format_results(result.allies, valid=result.valid)
        )
        self.query_one("#enemies-pane", DojoPane).set_results(
            _format_results(result.enemies, valid=result.valid)
        )
        status = self.query_one("#status-bar", Static)
        status.update(result.status_line())
        status.set_class(not result.valid and bool(pattern_line), "-invalid")
        banner = self.query_one("#redos-banner", Static)
        if result.redos_warning:
            banner.update(f"⚠ ReDoS risk: {result.redos_warning}")
            banner.set_class(True, "-visible")
        else:
            banner.update("")
            banner.set_class(False, "-visible")
        return result

    def on_text_area_changed(self, event: TextArea.Changed) -> None:  # noqa: D401
        """Re-evaluate on any keystroke in any pane."""
        self._refresh_evaluation()

    # --- focus helpers ---------------------------------------------------

    def _current_pane_index(self) -> int:
        focused = self.focused
        if focused is None:
            return 0
        for pane_id in self.PANE_ORDER:
            try:
                pane = self.query_one(f"#{pane_id}", DojoPane)
            except Exception:
                continue
            if focused is pane or focused in pane.walk_children():
                return self.PANE_ORDER.index(pane_id)
        return 0

    def _highlight_focus(self, pane_id: str) -> None:
        for pid in self.PANE_ORDER:
            try:
                pane = self.query_one(f"#{pid}", DojoPane)
            except Exception:
                continue
            pane.set_class(pid == pane_id, "-focused")

    def action_focus_pane(self, pane_id: str) -> None:
        pane = self.query_one(f"#{pane_id}", DojoPane)
        pane.focus_editor()
        self._highlight_focus(pane_id)

    def action_focus_next_pane(self) -> None:
        idx = (self._current_pane_index() + 1) % len(self.PANE_ORDER)
        self.action_focus_pane(self.PANE_ORDER[idx])

    def action_focus_prev_pane(self) -> None:
        idx = (self._current_pane_index() - 1) % len(self.PANE_ORDER)
        self.action_focus_pane(self.PANE_ORDER[idx])

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    # --- sensei attack --------------------------------------------------

    def action_sensei_attack(self) -> AttackReport:
        pattern, allies_blob, enemies_blob = self._gather_text()
        pattern_line = _first_pattern_line(pattern)
        from .engine import split_examples

        allies = split_examples(allies_blob)
        enemies = split_examples(enemies_blob)

        report = run_attack(
            pattern_line, allies, enemies, provider=self._sensei_provider
        )
        self._last_attack = report

        outcome = self._state.apply_attack(xp_gained=report.xp, damage=report.damage)
        if self._daily is not None and outcome.won:
            self._state.record_daily(self._daily.iso_date)

        # Add the attack strings to the appropriate panes so the user can
        # see the new examples and the dots re-paint.
        if report.attacks:
            new_allies = [a.text for a in report.attacks if a.should_match]
            new_enemies = [a.text for a in report.attacks if not a.should_match]
            if new_allies:
                self._append_to_pane("allies-pane", new_allies)
            if new_enemies:
                self._append_to_pane("enemies-pane", new_enemies)
            self._refresh_evaluation()

        self.query_one("#hp-bar", Static).update(self._hp_line())
        suffix = outcome.headline()
        status = report.summary() + (f"  ·  {suffix}" if suffix != "no change" else "")
        self.query_one("#status-bar", Static).update(status)

        try:
            save_state(self._state, self._state_path)
        except OSError:  # pragma: no cover — disk hiccups shouldn't crash play
            pass

        if outcome.promoted:
            self.push_screen(
                BeltPromotionScreen(outcome.belt_before.name, outcome.belt_after.name)
            )
        elif outcome.knocked_out:
            self.push_screen(EndOfRoundScreen(self._state, outcome=outcome))
        return report

    def action_reset_round(self) -> None:
        self._state.reset_round()
        try:
            save_state(self._state, self._state_path)
        except OSError:  # pragma: no cover
            pass
        self.query_one("#hp-bar", Static).update(self._hp_line())
        self.query_one("#status-bar", Static).update("round reset — full HP, keep training")

    def action_end_of_round(self) -> None:
        self.push_screen(EndOfRoundScreen(self._state))

    def _append_to_pane(self, pane_id: str, lines: list[str]) -> None:
        editor = self.query_one(f"#{pane_id}", DojoPane).query_one(TextArea)
        existing = editor.text
        suffix = "\n".join(lines)
        if existing and not existing.endswith("\n"):
            existing += "\n"
        editor.text = existing + suffix + "\n"


def _first_pattern_line(blob: str) -> str:
    for raw in blob.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return raw
    return ""


def run(*, daily: bool = False, bundle: str | None = None) -> None:
    """Launch the dojo."""
    challenge: DailyChallenge | None = None
    if daily:
        from .state import daily_challenge
        challenge = daily_challenge()
    loaded_bundle: ChallengeBundle | None = None
    if bundle:
        loaded_bundle = load_bundle(bundle)
    RegexRumbleApp(daily=challenge, bundle=loaded_bundle).run()


class SpeedrunApp(App):
    """Minimal Textual app driving a :class:`SpeedrunRun`.

    The pattern input lives in a single TextArea; as soon as the typed
    pattern classifies the current round correctly, the run auto-advances.
    A live timer (refreshed twice per second) shows elapsed time.
    """

    CSS = """
    #speedrun-header { dock: top; height: 3; padding: 0 1; }
    #speedrun-body { padding: 0 1; }
    #speedrun-status { dock: bottom; height: 1; padding: 0 1; color: $accent; }
    .col { width: 1fr; padding: 0 1; }
    TextArea { height: 5; }
    """
    BINDINGS = [
        Binding("q", "abort", "abort"),
        Binding("ctrl+c", "abort", "abort", show=False),
    ]

    def __init__(self, speedrun_run) -> None:  # type: ignore[no-untyped-def]
        super().__init__()
        self.run_state = speedrun_run
        self.final_summary: str | None = None

    def compose(self) -> ComposeResult:  # pragma: no cover - UI plumbing
        yield Header()
        yield Static("", id="speedrun-header")
        with Horizontal(id="speedrun-body"):
            with Vertical(classes="col"):
                yield Static("Pattern (auto-advances on solve)", classes="pane-title")
                ta = TextArea("", id="speedrun-pattern")
                ta.show_line_numbers = False
                yield ta
                yield Static("", id="speedrun-examples")
        yield Static("q to abort", id="speedrun-status")
        yield Footer()

    def on_mount(self) -> None:  # pragma: no cover - UI plumbing
        self.run_state.start_round()
        self._refresh()
        self.set_interval(0.5, self._refresh)
        self.query_one("#speedrun-pattern", TextArea).focus()

    def on_text_area_changed(self, event) -> None:  # type: ignore[no-untyped-def]
        # pragma: no cover - UI plumbing
        pattern = event.text_area.text.splitlines()[0] if event.text_area.text else ""
        if self.run_state.is_finished:
            return
        if self.run_state.submit(pattern):
            event.text_area.text = ""
            if self.run_state.is_finished:
                self._end()
            else:
                self.run_state.start_round()
                self._refresh()

    def action_abort(self) -> None:  # pragma: no cover - UI plumbing
        self.run_state.abort()
        self._end()

    def _refresh(self) -> None:  # pragma: no cover - UI plumbing
        from .speedrun import format_split

        if self.run_state.is_finished:
            return
        challenge = self.run_state.current_challenge
        idx = self.run_state.current_index
        total = self.run_state.count
        elapsed = format_split(self.run_state.elapsed_total_s)
        head = (
            f"speedrun · round {idx}/{total} · elapsed {elapsed}\n"
            f"{challenge.name if challenge else ''} — {challenge.hint if challenge else ''}"
        )
        self.query_one("#speedrun-header", Static).update(head)
        if challenge is not None:
            allies = "\n".join(f"✓ {a}" for a in challenge.allies)
            enemies = "\n".join(f"✗ {e}" for e in challenge.enemies)
            self.query_one("#speedrun-examples", Static).update(
                f"allies must match:\n{allies}\n\nenemies must NOT match:\n{enemies}"
            )

    def _end(self) -> None:  # pragma: no cover - UI plumbing
        from .speedrun import load_prs, pr_key, render_summary, save_pr

        result = self.run_state.result()
        previous = load_prs().get(pr_key(result.pack_id, result.count, result.seed))
        if not result.aborted and result.all_solved:
            save_pr(result.pack_id, result.count, result.seed, result.total_elapsed_s)
        self.final_summary = render_summary(result, previous_pr=previous)
        self.exit()


def run_speedrun(speedrun_run) -> None:  # type: ignore[no-untyped-def]
    """Run a :class:`SpeedrunRun` in the TUI and print the summary on exit."""
    app = SpeedrunApp(speedrun_run)
    app.run()
    if app.final_summary:
        print(app.final_summary)
