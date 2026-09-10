# agent-cost

[![CI](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml/badge.svg)](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Token, cache and context observability — find and stop context bloat in AI coding agents.**

**A 98.9% cache hit rate did not make my coding agent cheap.** Measured across
88 real Claude Code sessions on one machine (2026-09-10):

```text
Prompt tokens     3,942,280,650
  cache read      3,900,634,875    98.9%
  cache write        41,615,749
  genuinely new          30,026    0.0008%
Output               13,094,861
Turns                     12,937
```

**Every turn drags ~305K tokens of context to produce ~1.0K of output — a
301:1 ratio.** The cache is doing its job; it discounts that prompt rather
than shrinking it. A high hit rate does not protect you from unbounded context
growth, it only changes the unit price.

Where the bulk comes from, over 15.2M characters of transcript:

```text
tool_output   76.2%
assistant     18.5%
user           3.8%
tool_calls     0.3%
```

`agent-cost` is a read-only CLI that measures this for you, per session or
across agents: how many tokens were really burned, where the context went, and
which agent delivers the best prompt-caching efficiency. It reads Codex,
Hermes, Claude Code and OpenCode sessions.

The figures above are one developer's machine, not a study, and they move as
sessions accumulate — run it on your own and see what you get.

## ⚡ 3-Minute Quickstart

No configuration required. Run it directly without installation via `pipx`:

```bash
# 1. Zero-install instant analysis (auto-detects local agent transcripts)
pipx run agent-cost-tracker analyze

# 2. Or install globally
pip install agent-cost-tracker

# 3. Compare all agents and sessions side-by-side
agent-cost compare
```

### What `agent-cost` tells you immediately

1. **Context Drag Ratio**: Are you dragging 300K tokens of history to generate 1K of code? (The 301:1 ratio problem).
2. **Context Anatomy**: Is 90%+ of your context eaten by large tool/bash outputs rather than actual instructions?
3. **Hidden Waste**: Exact list of files repeatedly read in the same session and duplicate tool outputs.

---

## Install & Agent Setup

```bash
pip install agent-cost-tracker
```

> **Note**: The package distribution is named `agent-cost-tracker` on PyPI; the binary command installed is `agent-cost`.

### Zero-Config Auto Detection

`agent-cost` automatically scans default session paths for installed agents on your system:

| Agent / Tool | Default Monitored Path | What is Measured |
| :--- | :--- | :--- |
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | Turn-by-turn input/output tokens, cache read/write, tool output breakdown |
| **OpenCode** | `~/.local/share/opencode/opencode.db` | Turn-level tokens, SQLite cache stats (`cache.read`, `cache.write`), tool calls |
| **Hermes** | `sessions.json` | Real input/output/cache totals + finalized costs |
| **Codex** | `~/.codex/sessions/**/*.jsonl` | Turns, compactions, prompt growth curves, context sources |

```bash
# Analyze specific project or session directory
agent-cost analyze ~/.claude/projects/my-repo/
```

## Usage

Run it with no arguments and it finds the agents installed on this machine
(`~/.claude/projects`, `~/.codex/sessions`, `~/.local/share/opencode/opencode.db`)
and rolls them all up into one screen:

```bash
agent-cost analyze
```

```text
227 sessions · claude-code, codex, opencode · 19,712 turns
──────────────────────────────
Prompt tokens        4,654,537,756
  cache read         4,465,569,133    95.9%
  cache write           41,889,961
  new                  147,078,662
Output                  15,267,511
Per turn        236,127 prompt -> 775 output  (305:1)
Context growth  22,245 -> 185,206 tokens (x8.3, avg first vs last turn over 206 sessions)

Where the context comes from
  tool_output       76.2%
  assistant         17.9%
  user               4.0%

Tools producing that output
  Bash              85.3%  (10,716 calls)
  Read               8.3%  (470 calls)

Waste signals
  repeated file reads    78 files across 25 sessions
  duplicate tool output  72 outputs across 52 sessions
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

### Which turn blew up the context, and what did it?

A prompt curve tells you the session got expensive. It does not tell you when,
or what to stop doing. `--budget` marks the crossings and names the call that
carried the most output into the worst turn:

```bash
agent-cost analyze --per-session --budget warning:100k,critical:150k
```

```text
Context budget: warning 100K | critical 150K
  turn    1      27K    +27,363
  ...
  turn   50     100K       +898  [warning]
  ...
  turn   76     150K       +919  [critical]
  ...
  turn  104     232K    +43,493  [critical] biggest jump by Read `notes/BUG_LOG.md`
  ...
  turn  282     458K       +724  [critical]
```

That is one real session, unedited apart from the file path. One full-file
read of a long append-only log cost more than the previous twenty-five turns
combined — a habit worth changing, and one nothing in the session surfaced at
the time.

Only the turns that carry the story are printed: the ends, each first
crossing, and the biggest jump. Turn 1 is never the biggest jump — its delta
is the session preamble, which no tool caused and no habit can shrink.

A jump with no tool output behind it is reported as such rather than left
blank; on this project's own transcripts those turns are per-turn injected
context and long pasted messages, which is worth knowing too.

Budgets default to `warning:100k,critical:150k` and also read
`AGENT_COST_BUDGET`. A spec that would set warning at or above critical is
rejected rather than quietly ignored.

### What a call actually costs

A tool result is paid for more than once. It enters the prompt on the turn that
asked for it, and **every later turn carries it again** — prompt caching
discounts that repeat, it does not remove it. So the cost of a call is not its
size, it is its size multiplied by how much session is left after it:

```text
Costliest calls (output x turns that carried it after, est. tokens)
     3.1M   25,751 chars x  488 later turns  Read `notes/BUG_LOG.md`
     2.9M   19,586 chars x  585 later turns  Read `notes/TODO.md`
     2.7M   18,791 chars x  585 later turns  Read `notes/journal.md`
     1.9M   14,128 chars x  541 later turns  Bash `grep -rn "..." --include="*.md" .`
```

Real output from one machine, paths shortened. **A single 25K-character file
read on turn 21 was carried by 488 later turns — an estimated 3.1M tokens
after the turn that needed it.**

This changes what is worth fixing. Ranked by size, tool output looks flat:
across 12,345 real calls the median is 386 characters, and calls over 10K
characters are 0.55% of them and 9.4% of the output. Ranked by carried cost,
the top 1% of calls account for 20% of it — and a 4K-character command on turn
15 outranks a 20K one on turn 400.

The practical rule it implies is not "avoid big output". It is **narrow the
call early**: the same `sed -n '1,80p'` instead of a full read is worth fifty
times more on turn 10 than on turn 500.

### Did your change actually help?

Measuring once tells you where the context went. It cannot tell you whether the
fix worked. Record a baseline, change something, and compare:

```bash
agent-cost baseline --label before-rtk   # snapshot how things are now
# ...install a tool-output compressor, rewrite CLAUDE.md, move work to subagents...
agent-cost diff --against before-rtk     # only sessions started since the baseline
```

```text
before-rtk (saved 2026-08-20, 216 sessions, 35,228 turns)
  vs since then (44 sessions, 9,327 turns)
──────────────────────────────
                            BEFORE       AFTER    CHANGE
Per-turn prompt            239,055     213,264    -10.8%
Context:output ratio         250.9       192.1    -23.4%
Cache hit                    97.1%       98.4%    +1.3pt

Tool output                 BEFORE       AFTER    CHANGE
  Bash                       73.9%       96.3%     22.4pt
  Read                       17.7%        0.5%    -17.1pt

Waste per session           BEFORE       AFTER    CHANGE
  repeated file reads         0.78        0.14    -82.5%
```

That run is real: the reads collapsed because the sessions after 08-20 pushed
log reading and directory scans into subagents. The comparison is rates only —
the two windows cover different spans, so totals are not comparable — and
sessions with no timestamp are excluded and counted rather than folded into
either side. Baselines are plain JSON under `~/.agent-cost/baselines/`;
`agent-cost baseline --list` shows what you have.

That baseline predates the usage de-duplication fix in 0.6.0, which cut
Claude Code token and turn counts by roughly half (see CHANGELOG). Both are
counts, and the rates above divide one by the other, so the percentages here
still hold to within ~2.4%; only the absolute session and turn totals a
pre-0.6.0 baseline reports are inflated.

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
- [x] `agent-cost baseline` / `agent-cost diff`: did the change actually help?
- [x] Budget thresholds, and the tool call behind the worst turn ([#7](https://github.com/yingxiangge/agent-cost/issues/7))
- [x] Carried cost: rank calls by output size x turns that carried it after
- [ ] Warn while the session is running, not after it — as a `PostToolUse`
  hook. Gated on carried cost, not output size: measurement says size alone
  flags the wrong 9.4% and would need an exception every time a full read was
  the right call
- [ ] Task-level efficiency metrics (useful code changes vs. tool overhead) —
  needs design ([#8](https://github.com/yingxiangge/agent-cost/issues/8))

## Contributing

Bug reports are especially welcome — particularly a session that parses
incorrectly. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and how to
add support for a new session format. Please never attach a raw session file to
an issue; strip it first.

## Security

See [SECURITY.md](SECURITY.md). Session files are untrusted input; this tool
never executes them, never renders them, and never sends data anywhere.
