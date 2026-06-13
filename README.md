# regex-rumble 🥋

> A terminal dojo for regex training. Write a pattern. The AI sensei tries to defeat it. Earn your belts.

**Status:** pre-alpha (M3 — live evaluation engine landed). See [PLAN.md](./PLAN.md).

## Install (planned)

```bash
pipx install regex-rumble
# or
uvx regex-rumble
```

## Quickstart

```bash
git clone https://github.com/rwrife/regex-rumble && cd regex-rumble
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
regex-rumble --version
regex-rumble            # launches the three-pane dojo TUI
regex-rumble --banner   # legacy banner output
```

Type a regex in the **Pattern** pane and example strings in the **Allies**
and **Enemies** panes. Each example is annotated live with 🟢 (pass) or
🔴 (fail) and the status bar shows a running tally. Invalid regex is
reported gracefully — no crashes.

The AI sensei (`s` to summon) arrives in M4.

## Develop

```bash
ruff check .
pytest
```

Three panes appear:
- **Pattern** — your regex.
- **Allies** — strings that must match.
- **Enemies** — strings that must not match.

Press `s` to summon the sensei. It will forge adversarial edge-case strings and try to break your pattern. If it does, you lose HP. Earn streaks, climb the belts.

## Why
Most regex tools are passive testers. `regex-rumble` is adversarial — it actively hunts the cases you forgot.

## License
MIT (TBD).
