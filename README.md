# regex-rumble 🥋

> A terminal dojo for regex training. Write a pattern. The AI sensei tries to defeat it. Earn your belts.

**Status:** pre-alpha (M1 scaffold). See [PLAN.md](./PLAN.md).

## Install (planned)

```bash
pipx install regex-rumble
# or
uvx regex-rumble
```

## Quickstart

Right now the CLI is a banner — the dojo is still being built. To try it locally:

```bash
git clone https://github.com/rwrife/regex-rumble && cd regex-rumble
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
regex-rumble --version
regex-rumble            # prints the banner
```

Once M3 lands:

```bash
export OPENAI_API_KEY=...
regex-rumble
```

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
