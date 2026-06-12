# regex-rumble — PLAN

## 1. Pitch
A terminal dojo where you train your regex skills against an AI sensei. You write a pattern that must match a set of "allies" and reject a set of "enemies"; the sensei then forges adversarial edge-case strings designed to defeat your pattern. Win streaks, shameful losses, and belts (white → black) make practice addictive.

## 2. Trend inspiration
- **AI agent infrastructure boom** on Product Hunt May 2026 (Shadow 2.0, Kilo Code v7) — adversarial-loop UX is having a moment. https://www.shareuhack.com/en/posts/product-hunt-weekly-2026-05-07
- **TUI renaissance** — Terminal Trove and r/commandline keep upvoting Bubble Tea / Textual apps that gamify everyday work. https://terminaltrove.com/new/
- **MCP everywhere** — the trend of "small focused tools that any LLM agent can call" (mcptoplist.com lists 59k servers). regex-rumble v0.3 can ship an MCP server so coding agents can request a fuzzed regex test before merging.
- Long-tail evergreen pain: regex bugs cause CVEs (ReDoS) and prod incidents. Adversarial generation is the right frame.

## 3. Why it's different
Most regex tools (regex101, regexr, scunner, grex) are **passive** — you give them text, they show matches. A few generators (grex) infer a regex from samples. **None** play the role of a opponent that tries to defeat *your* regex with strings you didn't think of. The closest analog is property-based testing libs (Hypothesis), but those target functions, not regex patterns, and they aren't a game.

Other tool-lab repos:
- `commit-roast` — git commit critic. Different domain.
- `schema-seance` — data file analysis. Different domain.

## 4. MVP scope (v0.1)
- Single binary CLI: `regex-rumble` opens a TUI.
- Three panes: **Pattern** (your regex), **Allies** (must match), **Enemies** (must not match).
- Live evaluation: green/red dots next to each example as you type.
- "Sensei attack" button (default `s`): asks an LLM to generate up to 5 new edge-case strings labeled `should-match` or `should-not-match` based on the user's apparent intent. New strings are added to the lists and re-evaluated. If any are mis-classified by your pattern, you take damage.
- HP bar, win/loss counter, belt level persisted to `~/.regex-rumble/state.json`.
- Pure stdlib regex (Python `re` for MVP); show a warning + linter note if pattern is catastrophic-backtracking-prone (basic heuristic).

## 5. Tech stack
- **Python 3.11+** with **Textual** for the TUI — fastest path to a polished terminal UI, great theming, easy to extend.
- **httpx** for LLM calls (OpenAI-compatible endpoint configurable via `OPENAI_API_KEY` + `REGEX_RUMBLE_MODEL`).
- **typer** for CLI flags.
- **pytest** + **textual.pilot** for tests.
- Packaged via `uv` / `pyproject.toml`; installable with `pipx install regex-rumble` (or `uvx`).

Boring, fast, ubiquitous. No frontend build step, runs everywhere a terminal exists.

## 6. Architecture
```
regex_rumble/
  __init__.py
  cli.py            # typer entrypoint
  app.py            # Textual App, screens, key bindings
  engine.py         # pattern evaluation, ReDoS heuristic, scoring
  sensei.py         # LLM client, prompt templates, adversarial loop
  state.py          # belt/HP/streak persistence
  themes.py         # color/dojo themes
  widgets/          # custom Textual widgets (HPBar, BeltStripe, ExampleList)
```

Key flows:
- `cli.py` → `app.run()`
- On user keystroke in Pattern pane → `engine.evaluate(pattern, allies, enemies)` → diff results, paint UI.
- On `s` → `sensei.attack(pattern, allies, enemies)` → returns labeled examples → engine re-evaluates → HP/score updated.

## 7. Milestones
1. **M1 — scaffold + hello-world** — Python package, `pyproject.toml`, `regex-rumble` entrypoint prints a banner. CI: `ruff` + `pytest` smoke test. README quickstart.
2. **M2 — core TUI shell** — Three-pane Textual layout, focus management, basic theming, empty state. No evaluation yet.
3. **M3 — live evaluation engine** — `engine.py` matches/non-matches with live red/green dots; status bar shows pass/fail counts. Unit tests.
4. **M4 — sensei attack loop** — LLM client + prompt; `s` key fetches adversarial examples; HP bar drops on mis-classification. Mock provider for offline tests.
5. **M5 — scoring, belts, persistence** — `state.json`, streaks, belt promotions, end-of-round summary screen. Daily challenge mode (`--daily`).
6. **M6 — distribution polish** — `pipx`/`uvx` install docs, screenshots/gif in README, GitHub release workflow, ReDoS warning banner, error handling for missing API key (fall back to canned attack list).

## 8. Backlog (v0.2+)
- **Multiplayer dojo** — share a challenge link; friends submit patterns; scoreboard.
- **Language packs** — switch regex flavor (PCRE, RE2, JS, Go, Rust, .NET) and lint accordingly.
- **ReDoS dojo** — dedicated mode that explicitly hunts catastrophic-backtracking patterns; show pump-string trace.
- **Import from regex101** — paste a regex101 link, auto-load tests.
- **MCP server mode** — `regex-rumble --serve-mcp` exposes `evaluate` and `attack` tools so coding agents can fuzz patterns before commit.
- **Replay mode** — record sensei attacks; replay them as a learning montage.
- **VS Code extension** — selection → "send to dojo".
- **Pattern library** — community-contributed dojo packs (emails, URLs, IPv6, IBANs).
- **Belt certificates** — exportable SVG/PNG belt cards to share on socials.
- **Speedrun mode** — solve N challenges, race the clock.
- **Local LLM provider** — Ollama/llama.cpp backend.
- **Heatmap analytics** — which character classes you keep getting wrong.

## 9. Out of scope
- A general-purpose regex visualizer (railroad diagrams, etc.) — leave that to regexper.
- A regex inference tool (grex already nailed it).
- A full IDE/editor — we are a focused dojo, not a workbench.
- A web app (v0.1) — TUI first; web mirror is a maybe for v0.x but not the bet.
- Mobile.
