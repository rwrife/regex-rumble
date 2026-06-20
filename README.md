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

### Keys
- `s` — sensei attack
- `r` — reset round (refills HP, keeps XP/belt)
- `e` — end-of-round summary (belt, streaks, totals)
- `?` — help
- `q` — quit

### Belts & progression
XP accumulates across sessions and promotes you through the belt ranks
(white → yellow → orange → green → blue → purple → brown → black).
Wins (an attack you survived with zero misses) build a streak; one miss
resets it. Progress lives in `~/.regex-rumble/state.json` (override with
the `REGEX_RUMBLE_HOME` env var).

### Daily challenge
```bash
regex-rumble --daily
```
Loads a seeded challenge — same allies/enemies for everyone, every day.

### Shareable challenge bundles

Build a challenge once, ship it everywhere:

```bash
regex-rumble export-bundle ipv4.json \
  --name ipv4-strict --hint "dotted-quad IPv4" \
  -a 1.2.3.4 -a 127.0.0.1 \
  -e 256.1.1.1 -e 1.2.3 \
  --goal '^\d{1,3}(\.\d{1,3}){3}$' --print-url

regex-rumble --bundle ipv4.json          # load from file
regex-rumble --bundle 'regex-rumble://challenge/...'   # load from URL
```

Bundles are stdlib JSON; the `regex-rumble://` URL is just compact base64
so it survives chat clients. Goal patterns are optional — leave them out
for blind multiplayer challenges where each player invents their own.

### ReDoS warning banner

If your pattern matches a known catastrophic-backtracking shape (nested
quantifiers like `(a+)+`, overlapping alternation like `(a|ab)*`, or
adjacent greedy wildcards like `.*.*`), a yellow banner appears above the
status bar. It's a heuristic, not a proof — but it flags the patterns
most likely to bite you in production.

### Regex flavor lint

Different regex flavors disagree on the fun bits — RE2/Go reject
lookaround and backreferences, JavaScript uses `(?<name>...)` instead of
Python's `(?P<name>...)`, only .NET supports conditional `(?(cond)yes|no)`,
etc. Run the linter before pasting a pattern into a foreign codebase:

```
regex-rumble lint '(?=foo)\1' --flavor re2
# - [re2] lookaround assertions are not supported (near '(?=')
# - [re2] backreferences are not supported (near '\1')
```

Supported flavors: `python` (default), `pcre`, `re2`, `js`, `go`, `rust`,
`dotnet`. Exit code is `0` when clean, `1` when warnings fire.

### MCP server mode

Expose the dojo as a [Model Context Protocol](https://modelcontextprotocol.io)
server so coding agents (Claude, Cursor, OpenAI Agents SDK, etc.) can fuzz
your regex before you commit it:

```bash
regex-rumble --serve-mcp
```

This speaks newline-delimited JSON-RPC 2.0 over stdio and ships two tools:

- **`evaluate`** — run a pattern against ally/enemy example lists, returning
  per-example pass/fail, totals, and a ReDoS warning when the pattern looks
  risky.
- **`attack`** — let the sensei generate adversarial examples and report
  which ones the pattern misclassifies. Falls back to canned attacks when
  no LLM API key is configured.

Example agent config (Claude Desktop / Codex CLI style):

```json
{
  "mcpServers": {
    "regex-rumble": {
      "command": "regex-rumble",
      "args": ["--serve-mcp"]
    }
  }
}
```

## Why
Most regex tools are passive testers. `regex-rumble` is adversarial — it actively hunts the cases you forgot.

## License
MIT (TBD).
