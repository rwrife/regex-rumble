"""Textual App for the regex-rumble dojo (M2: shell only, no evaluation)."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static, TextArea

from . import __version__

EMPTY_PATTERN = "# Write your regex here.\n# (Live evaluation arrives in M3.)\n"
EMPTY_ALLIES = "# One ally string per line — must MATCH.\n"
EMPTY_ENEMIES = "# One enemy string per line — must NOT match.\n"


class DojoPane(Vertical):
    """A titled pane wrapping a TextArea editor."""

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
    DojoPane > TextArea {
        height: 1fr;
        border: none;
    }
    """

    def __init__(self, title: str, placeholder: str, pane_id: str) -> None:
        super().__init__(id=pane_id)
        self._title = title
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        yield Static(self._title, classes="pane-title")
        yield TextArea(self._placeholder, id=f"{self.id}-editor")

    def focus_editor(self) -> None:
        editor = self.query_one(TextArea)
        editor.focus()


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
    """Three-pane dojo shell. Evaluation logic lands in M3."""

    CSS = """
    Screen {
        background: $background;
    }
    #panes {
        height: 1fr;
    }
    """

    TITLE = "regex-rumble"
    SUB_TITLE = f"dojo shell · v{__version__}"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("question_mark", "help", "Help"),
        Binding("tab", "focus_next_pane", "Next pane", show=False),
        Binding("shift+tab", "focus_prev_pane", "Prev pane", show=False),
        Binding("1", "focus_pane('pattern-pane')", "Pattern", show=False),
        Binding("2", "focus_pane('allies-pane')", "Allies", show=False),
        Binding("3", "focus_pane('enemies-pane')", "Enemies", show=False),
    ]

    PANE_ORDER = ("pattern-pane", "allies-pane", "enemies-pane")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="panes"):
            yield DojoPane("⛩  Pattern", EMPTY_PATTERN, "pattern-pane")
            yield DojoPane("🟢 Allies (must match)", EMPTY_ALLIES, "allies-pane")
            yield DojoPane("🔴 Enemies (must NOT match)", EMPTY_ENEMIES, "enemies-pane")
        yield Footer()

    def on_mount(self) -> None:
        self.action_focus_pane("pattern-pane")

    # --- focus helpers ---

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


def run() -> None:
    """Launch the dojo."""
    RegexRumbleApp().run()
