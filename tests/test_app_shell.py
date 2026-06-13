"""M2 — make sure the three-pane TUI shell mounts, focuses, and cycles."""

from __future__ import annotations

import pytest

from regex_rumble.app import RegexRumbleApp


@pytest.mark.asyncio
async def test_app_mounts_three_panes() -> None:
    app = RegexRumbleApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        pane_ids = {pane.id for pane in app.query("DojoPane")}
        assert pane_ids == {"pattern-pane", "allies-pane", "enemies-pane"}


@pytest.mark.asyncio
async def test_initial_focus_is_pattern_pane() -> None:
    app = RegexRumbleApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app._current_pane_index() == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_tab_cycles_focus_through_panes() -> None:
    app = RegexRumbleApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_focus_next_pane()
        await pilot.pause()
        assert app._current_pane_index() == 1  # noqa: SLF001
        app.action_focus_next_pane()
        await pilot.pause()
        assert app._current_pane_index() == 2  # noqa: SLF001
        app.action_focus_next_pane()
        await pilot.pause()
        assert app._current_pane_index() == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_help_screen_opens_and_closes() -> None:
    app = RegexRumbleApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_help()
        await pilot.pause()
        assert len(app.screen_stack) == 2
        await pilot.press("escape")
        await pilot.pause()
        assert len(app.screen_stack) == 1
