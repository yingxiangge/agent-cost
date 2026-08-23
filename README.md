# agent-cost

[![CI](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml/badge.svg)](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Token, cache and context observability for AI coding agents.**

AI coding agents are expensive not because they have no cache — they usually
have too much of it. `agent-cost` is a read-only CLI that shows you, per
session or across multiple agents, how many tokens were really burned, where
the context went, and which agent delivers the best prompt-caching efficiency.

It was built from real-world usage across Codex, Hermes, and Claude Code. Across
72 real Claude Code sessions (63.7M characters of transcript), the context
attribution comes out as:

```text
tool_output   94.8%
assistant      4.3%
user           0.5%
tool_calls     0.1%
```

Those same sessions total 9.1B billed prompt tokens at a 98.7% cache hit rate —
a high hit rate does not protect you from unbounded context growth, it only
changes the unit price.

## Install

```bash
git clone https://github.com/yingxiangge/agent-cost.git
cd agent-cost
pip install -e .
```

Requires Python 3.10+.

Not on PyPI yet — `pip install agent-cost` and `pipx run agent-cost` start
working with the first tagged release.

## Usage

```bash
# Compare usage, cache efficiency, and cost across multiple agents or sessions
agent-cost compare ~/.claude/projects/ ~/.codex/sessions/ ./hermes/

# Output structured JSON for analysis pipelines
agent-cost compare --json ~/.claude/projects/ ~/.codex/sessions/

# Inspect one session (Claude Code, Hermes, OpenCode, Codex, or a folder)
agent-cost inspect ~/.codex/sessions/2026/08/11/rollout-*.jsonl

# Context growth and actionable recommendations
agent-cost analyze ~/.codex/sessions/2026/08/11/

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
- [x] Claude Code / Codex / Hermes session parsing
- [x] OpenCode: SQLite database (`opencode.db`) and JSON export parsing
- [ ] Support Cursor (`composer.json` / workspace state) log formats
- [ ] Support Cline / Roo Code conversation history formats
- [ ] `agent-cost watch`: budget thresholds with warnings before a session blows up
- [ ] Tool-call-level cost attribution when providers expose per-request usage

## Contributing

Bug reports are especially welcome — particularly a session that parses
incorrectly. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and how to
add support for a new session format. Please never attach a raw session file to
an issue; strip it first.

## Security

See [SECURITY.md](SECURITY.md). Session files are untrusted input; this tool
never executes them, never renders them, and never sends data anywhere.
