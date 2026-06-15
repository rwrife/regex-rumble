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
from .engine import EvaluationResult, ExampleResult, evaluate
from .sensei import AttackProvider, AttackReport, run_attack

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
    """

    TITLE = "regex-rumble"
    SUB_TITLE = f"dojo · v{__version__}"

    MAX_HP = 100

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("s", "sensei_attack", "Sensei attack"),
        Binding("tab", "focus_next_pane", "Next pane", show=False),
        Binding("shift+tab", "focus_prev_pane", "Prev pane", show=False),
        Binding("1", "focus_pane('pattern-pane')", "Pattern", show=False),
        Binding("2", "focus_pane('allies-pane')", "Allies", show=False),
        Binding("3", "focus_pane('enemies-pane')", "Enemies", show=False),
    ]

    PANE_ORDER = ("pattern-pane", "allies-pane", "enemies-pane")

    def __init__(self, *, sensei_provider: AttackProvider | None = None) -> None:
        super().__init__()
        self._sensei_provider = sensei_provider
        self._hp = self.MAX_HP
        self._xp = 0
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
        yield Static("no examples yet — add allies and enemies", id="status-bar")
        yield Footer()

    def _hp_line(self) -> str:
        return f"HP {self._hp}/{self.MAX_HP} · XP {self._xp}"

    def on_mount(self) -> None:
        self.action_focus_pane("pattern-pane")
        self._refresh_evaluation()

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

        # Bank XP for correct classifications, drop HP for misses.
        self._xp += report.xp
        self._hp = max(0, self._hp - report.damage)

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
        self.query_one("#status-bar", Static).update(report.summary())
        return report

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


def run() -> None:
    """Launch the dojo."""
    RegexRumbleApp().run()
