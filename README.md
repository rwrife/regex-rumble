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

### Speedrun mode

Race the clock through N regex challenges:

```bash
regex-rumble speedrun                       # 10 rounds from the built-in pack
regex-rumble speedrun --count 20 --seed 42  # deterministic gauntlet
regex-rumble speedrun --bundle my-pack.json # a custom pack
regex-rumble speedrun --headless --seed 1   # print the lineup without the TUI
```

Each round shows allies + enemies; the run auto-advances the moment your
pattern classifies them all correctly. Aborts (`q`) don't overwrite your
personal record. PRs are keyed by `(pack id, count, seed)` and persisted
alongside the dojo state in `~/.regex-rumble/state.json`.

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

### Run offline with Ollama (or any local LLM)

The sensei doesn't need a cloud API key. Point it at a local model and it'll
forge adversarial examples on your own hardware — works on planes, airgapped
boxes, and "my company won't let me ship prompts to OpenAI" laptops.

**Ollama (3 lines):**

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1
REGEX_RUMBLE_PROVIDER=ollama regex-rumble
```

**Any OpenAI-compatible local server** (LM Studio, vLLM, llama.cpp's server,
Ollama's `/v1` shim):

```bash
export REGEX_RUMBLE_PROVIDER=openai-compatible
export REGEX_RUMBLE_BASE_URL=http://localhost:1234/v1   # LM Studio default
export REGEX_RUMBLE_MODEL=your-local-model
regex-rumble
```

**Env knobs:**

| Var | Values | Default |
| --- | --- | --- |
| `REGEX_RUMBLE_PROVIDER` | `openai`, `ollama`, `openai-compatible` | `openai` |
| `REGEX_RUMBLE_BASE_URL` | base URL for ollama / openai-compatible | provider default |
| `REGEX_RUMBLE_MODEL` | model name | `gpt-4o-mini` (openai) / `llama3.1` (ollama) |
| `OPENAI_API_KEY` | API key (only required for hosted `openai`) | unset |

If the local endpoint is unreachable, the sensei prints a one-line toast and
falls back to the canned offline attack list so the dojo stays playable.

Check what's configured (and whether the endpoint is alive):

```bash
regex-rumble doctor
```

### Know your weaknesses (heatmap analytics)

Every sensei attack tags the example strings it throws with a feature vector
(whitespace, unicode, regex metacharacters, mixed case, long strings, etc.).
Mis-classifications bump a per-feature miss counter so you can see where your
regex skills actually leak — not just "I lost a round", but *why*.

```bash
regex-rumble stats              # ASCII heatmap, color-graded by miss rate
regex-rumble stats --no-color   # plain output (great for piping)
regex-rumble stats --json       # machine-readable payload
regex-rumble stats --reset      # wipe counters (confirm prompt)
```

Example:

```
Regex weakness heatmap (miss rate per feature)
────────────────────────────────────────────────────────
  feature                 bar                   rate    n
  boundary-whitespace     ████████████████████  100.0%   3
  whitespace              █████████████░······   66.7%   6
  unicode                 █████████··········    45.0%   8
  digit                   ██·················     7.5%  20
```

Counters live alongside the dojo state in `~/.regex-rumble/state.json`.

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

### ReDoS dojo

Dedicated mode for hunting **catastrophic backtracking**. Static heuristics
flag classic shapes (`(a+)+`, `(a|a)+`, `.*.*`, `(a?)+`) and a pump-string
generator times the pattern against inputs of growing length in a watchdog
subprocess so you can *see* the exponential curve:

```
regex-rumble redos '(a+)+$' --timeout 1 --max-len 28
# static check: 1 suspicious construct(s)
#   - [nested-quantifier sev=3] 0:5 `(a+)+` — nested quantifiers...
# pump trace:
#    len          ms  graph
#      8        2.41  ███
#     16      612.30  ██████████████████████████████
#     20     TIMEOUT  ██████████████████████████████ ⏱
```

Exit code is `1` when the pattern times out or a high-severity construct is
found, `0` otherwise — handy for CI gates. The same primitives are exposed
as `regex_rumble.redos.detect`, `pump_strings`, and `trace` for programmatic
use.

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
