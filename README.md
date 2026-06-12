# regex-rumble 🥋

> A terminal dojo for regex training. Write a pattern. The AI sensei tries to defeat it. Earn your belts.

**Status:** pre-alpha. See [PLAN.md](./PLAN.md).

## Install (planned)

```bash
pipx install regex-rumble
# or
uvx regex-rumble
```

## Quickstart (planned)

```bash
export OPENAI_API_KEY=...
regex-rumble
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
