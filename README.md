# agent-cost

[![CI](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml/badge.svg)](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Token, cache and context observability for AI coding agents.**

AI coding agents are expensive not because they have no cache — they usually
have too much of it. `agent-cost` is a read-only CLI that shows you, per
session or across multiple agents, how many tokens were really burned, where
the context went, and which agent delivers the best prompt-caching efficiency.

It was built from real-world usage across Codex, Hermes, Claude Code, and OpenCode:
sessions that grew from 18K to 380K+ tokens, tool output consuming more than 80%
of the prompt, and cache-hit bills that still reached millions of tokens.

## Install

```bash
pip install -e .
```

Requires Python 3.10+.

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
```

### Real example (`agent-cost compare`)

```text
Agent Comparison Report
══════════════════════════════════════════════════════════════════════════════
AGENT          SESSIONS   TOTAL TOKENS  CACHED %   TOOLS   EST. USD  AVG $/SESS
-------------------------------------------------------------------------------
hermes                2      2,071,557     89.9%       0       0.84        0.42
claude-code           1         12,590     76.2%       1       0.02        0.02
opencode              1         14,530     45.4%       2       0.00        0.00
codex                 1            111      0.0%       1       0.00        0.00
-------------------------------------------------------------------------------
TOTAL                 5      2,098,788                         0.86

Key Insights:
  • Highest cache efficiency: hermes (89.9% hit rate).
  • Most tool intensive: opencode (2 total tool calls).
  • Prompt caching saved approx. $0.03 across analyzed sessions.
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
- **OpenCode** (`.json` or `.jsonl`): step-by-step token usage, tool
  executions, and prompt cache hit rates.
- **Codex rollouts** (`~/.codex/sessions/**/*.jsonl`): turns, tool calls,
  compaction events, prompt-size curve and context-source attribution.
  Rollouts usually have no token counters, so prompt sizes are estimated from
  content length (approx. 4 chars/token) and reported as estimates.

Parsing is intentionally read-only: files are only opened and counted, never
executed or modified.

## Pricing

Costs are estimated from a built-in price table covering Claude 3.5/3.7 Sonnet,
Opus, Haiku, GPT-4o, o1, o3-mini, DeepSeek V3/R1, Qwen 2.5 Coder, and Gemini (see `pricing.py`).
Prices change often and contracts differ, so set your own table with `--pricing '<json>'`
or the `AGENT_COST_PRICING` environment variable before trusting dollar figures.

## Roadmap

- [x] `agent-cost compare`: side-by-side agent comparison with `--by-agent` and `--json`
- [x] OpenCode / Claude Code session parsing
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
