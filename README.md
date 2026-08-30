# agent-cost

[![CI](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml/badge.svg)](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Token, cache and context observability — find and stop context bloat in AI coding agents.**

**A 98.7% cache hit rate did not make my coding agent cheap.** Measured across
82 real Claude Code sessions on one machine (2026-08-23):

```text
Prompt tokens     8,690,279,614
  cache read      8,579,120,394    98.7%
  cache write       111,034,321
  genuinely new         124,899    0.0014%
Output               33,139,293
Turns                     29,791
```

**Every turn drags ~292K tokens of context to produce ~1.1K of output — a
262:1 ratio.** The cache is doing its job; it discounts that prompt rather
than shrinking it. A high hit rate does not protect you from unbounded context
growth, it only changes the unit price.

Where the bulk comes from, over 54.3M characters of transcript:

```text
tool_output   93.9%
assistant      4.9%
user           0.8%
tool_calls     0.1%
```

`agent-cost` is a read-only CLI that measures this for you, per session or
across agents: how many tokens were really burned, where the context went, and
which agent delivers the best prompt-caching efficiency. It reads Codex,
Hermes, Claude Code and OpenCode sessions.

The figures above are one developer's machine, not a study, and they move as
sessions accumulate — run it on your own and see what you get.

## Install

```bash
pip install agent-cost-tracker
```

The distribution is named `agent-cost-tracker` because `agent-cost` is taken
on PyPI; the command it installs is `agent-cost`.

```bash
# Run it without installing
pipx run --spec agent-cost-tracker agent-cost compare ~/.claude/projects/

# Or from source
git clone https://github.com/yingxiangge/agent-cost.git
cd agent-cost
pip install -e .
```

Requires Python 3.10+.

## Usage

Run it with no arguments and it finds the agents installed on this machine
(`~/.claude/projects`, `~/.codex/sessions`, `~/.local/share/opencode/opencode.db`)
and rolls them all up into one screen:

```bash
agent-cost analyze
```

```text
216 sessions · claude-code, codex, opencode · 35,170 turns
──────────────────────────────
Prompt tokens        8,412,964,990
  cache read         8,167,485,671    97.1%
  cache write           98,321,928
  new                  147,157,391
Output                  33,501,731
Per turn        239,209 prompt -> 953 output  (251:1)
Context growth  19,101 -> 172,630 tokens (x9.0, avg first vs last turn over 198 sessions)

Where the context comes from
  tool_output       77.9%
  assistant         16.9%
  user               3.3%

Tools producing that output
  Bash              73.9%  (9,722 calls)
  Read              17.7%  (958 calls)

Waste signals
  repeated file reads    168 files across 42 sessions
  duplicate tool output  97 outputs across 58 sessions
```

Every subcommand takes explicit paths too, and every one of them falls back to
those same default locations when you give it none:

```bash
# Compare usage, cache efficiency, and cost across multiple agents or sessions
agent-cost compare ~/.claude/projects/ ~/.codex/sessions/ ./hermes/

# Output structured JSON for analysis pipelines
agent-cost compare --json ~/.claude/projects/ ~/.codex/sessions/

# Inspect one session (Claude Code, Hermes, OpenCode, Codex, or a folder)
agent-cost inspect ~/.codex/sessions/2026/08/11/rollout-*.jsonl

# One analysis per session instead of the rollup
agent-cost analyze --per-session ~/.codex/sessions/2026/08/11/

# Aggregate totals across sessions
agent-cost stats ~/.codex/sessions/2026/08/

# On a Claude Pro/Max subscription: report API-equivalent value, not spend
agent-cost --subscription compare ~/.claude/projects/
```

### Real example (`agent-cost compare`)

```text
Agent Comparison Report
══════════════════════════════════════════════════════════════════════════════
AGENT          SESSIONS   TOTAL TOKENS  CACHED %   TOOLS   EST. USD  AVG $/SESS
-------------------------------------------------------------------------------
hermes                2      2,071,557     89.9%       0      0.82*        0.41
claude-code           1         12,590     76.2%       1       0.02        0.02
opencode              1          8,130     83.1%       2       0.00        0.00
codex                 1            111      0.0%       1       0.00        0.00
-------------------------------------------------------------------------------
TOTAL                 5      2,092,388                        0.84*

n/a / * = model has no rate card, excluded from dollar totals (1 of 5 sessions).

Key Insights:
  • Highest cache efficiency: hermes (89.9% hit rate).
  • Most tool intensive: opencode (2 total tool calls).
  • Prompt caching saved approx. $0.03 across analyzed sessions.
  • 1 of 5 sessions have no rate card and are excluded from every dollar
    figure above. Supply rates with --pricing to include them.
```

### Real example (`agent-cost analyze`)

```text
Analysis: 019feec8-4ee1-7560-9a9f-89952d1af2d3
──────────────────────────────
Context growth: 24,072 -> 70,609 tokens (x2.93)
Largest context sources:
  tool_output         83.6%
  base_instructions    5.3%
  assistant            4.5%
  developer            3.3%
Compactions: 1
Prompt curve: 65K -> 66K -> 66K -> 70K -> 74K -> 80K

Recommendations:
  - Prompt size is growing steeply; start a fresh session instead of continuing.
  - Session was already compacted 1x; further work belongs in a new session.
  - Tool output dominates context; consider truncating or filtering large command output.
```

## Supported data sources

- **Claude Code** (`~/.claude/projects/**/*.jsonl` or `.json`): real turn-by-turn
  token usage with `input`, `output`, `cache_read_input_tokens`, and
  `cache_creation_input_tokens` breakdown, plus tool calls.
- **Hermes** (`sessions.json`): real `input/output/cache_read/cache_write`
  totals plus estimated cost when the agent has finalized them.
- **OpenCode** (`~/.local/share/opencode/opencode.db` SQLite database, or `.json` / `.jsonl` exports):
  real turn-by-turn token usage, tool calls, and cache stats (`input`, `output`,
  `cache.read`, `cache.write`).
- **Codex rollouts** (`~/.codex/sessions/**/*.jsonl`): turns, tool calls,
  compaction events, prompt-size curve and context-source attribution.
  Rollouts usually have no token counters, so prompt sizes are estimated from
  content length (approx. 4 chars/token) and reported as estimates.

Parsing is intentionally read-only: files are only opened and counted, never
executed or modified. Database connections use read-only SQLite URIs.

## Pricing

Costs are estimated from a built-in price table (see `pricing.py`) covering the
Claude family (Fable 5, Opus 5/4.8/4.7/4.6/4.5/4.1, Sonnet 5/4.6/4.5, Haiku 4.5,
plus the Claude 3.x generation), GPT-4o, GPT-5, o1, o3-mini, DeepSeek V3/R1,
Qwen 2.5 Coder, and Gemini. Anthropic rates are from the
[official pricing page](https://platform.claude.com/docs/en/about-claude/pricing)
as of 2026-08-16.

**A model that is not in the table is reported as `n/a`, never guessed.** It is
excluded from every dollar total, and the report says how many sessions that
covers. A wrong cost number is worse than no cost number, so there is no
default rate card to fall back on.

**Billing modes are priced per turn, not per session.** Fast mode and US-pinned
inference cost more and can be toggled mid-session, so usage is split into
`(speed, inference_geo)` buckets and each bucket is priced on its own card:

| Mode | Effect | Source |
|:---|:---|:---|
| `speed: "fast"` | Opus 5 / Opus 4.8 billed at **$10 / $50** instead of $5 / $25. Other models fall back to standard rates, matching the API. | `usage.speed` |
| `inference_geo: "us"` | **1.1x** on every token category. `global` / `not_available` are standard priced. | `usage.inference_geo` |

The two stack. `agent-cost inspect` lists the modes when a session used more
than one.

**On a subscription, pass `--subscription`.** Claude Pro/Max sessions do not
generate per-token charges, so the transcript's dollar value is what those
tokens *would* have cost on metered API billing — useful for comparing agents
and deciding when to restart a session, useless as a bill. The flag relabels
every figure as API-equivalent value. It has to be explicit: the transcript
carries no field distinguishing subscription from API usage.

One remaining approximation: `cache_write` uses the 5-minute rate (1.25x input),
because the usage payload does not record which cache TTL was used — sessions
on the 1-hour cache (2x input) are undercounted.

Supply your own rates to override any of this:

```bash
agent-cost --pricing "$(cat my-pricing.json)" compare ~/.claude/projects/
export AGENT_COST_PRICING="$(cat my-pricing.json)"
```

Your entries are merged over the built-in table, so overriding one model leaves
the rest intact. Copy [`pricing.example.json`](pricing.example.json) as a
starting template. Note that `--pricing` is a global flag and must come *before*
the subcommand.

Model names resolve by exact match first, then by longest matching prefix, so a
`claude-opus-4-5` entry also covers `claude-opus-4-5-20260101`, and `gpt-5-mini`
is never priced as `gpt-5`.

## Roadmap

- [x] `agent-cost compare`: side-by-side agent comparison with `--by-agent` and `--json`
- [x] Claude Code / Codex / Hermes / OpenCode session parsing
- [x] Tool output attribution by call type & type-specific optimization suggestions
- [x] Detect repeated file reads and duplicated tool output ([#6](https://github.com/yingxiangge/agent-cost/issues/6))
- [ ] Session context growth curve and budget threshold alerts ([#7](https://github.com/yingxiangge/agent-cost/issues/7))
- [ ] Task-level efficiency metrics (useful code changes vs. tool overhead) ([#8](https://github.com/yingxiangge/agent-cost/issues/8))
- [ ] Support Cursor (`composer.json` / workspace state) log formats ([#2](https://github.com/yingxiangge/agent-cost/issues/2))
- [ ] Support Cline / Roo Code conversation history formats ([#1](https://github.com/yingxiangge/agent-cost/issues/1))

## Contributing

Bug reports are especially welcome — particularly a session that parses
incorrectly. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and how to
add support for a new session format. Please never attach a raw session file to
an issue; strip it first.

## Security

See [SECURITY.md](SECURITY.md). Session files are untrusted input; this tool
never executes them, never renders them, and never sends data anywhere.
