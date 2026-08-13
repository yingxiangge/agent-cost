# agent-cost

[![CI](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml/badge.svg)](https://github.com/yingxiangge/agent-cost/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Token, cache and context observability for AI coding agents.**

AI coding agents are expensive not because they have no cache — they usually
have too much of it. `agent-cost` is a read-only CLI that shows you, per
session, how many tokens were really burned, where the context went, and
when you should `/compact` or start a new session.

It was built from real-world usage of Codex and Hermes: sessions that grew
from 18K to 380K+ tokens, tool output consuming more than 80% of the prompt,
and cache-hit bills that still reached millions of tokens.

## Install

```bash
pip install -e .
```

Requires Python 3.10+.

## Usage

```bash
# Inspect one session (Hermes sessions.json, Codex rollout .jsonl, or a folder)
agent-cost inspect ~/.codex/sessions/2026/08/11/rollout-*.jsonl

# Context growth and actionable recommendations
agent-cost analyze ~/.codex/sessions/2026/08/11/

# Aggregate totals across sessions
agent-cost stats ~/.codex/sessions/2026/08/
```

### Real example (Codex rollout, deepseek provider)

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

### Example (Hermes sessions.json)

```text
Agent Session
──────────────────────────────
Input             151,127
Cached input      1,691,204  91.8%
Cache writes      0
Output            151,127
Total             1,993,458

Estimated Cost    $0.82  (estimated)
```

## Supported data sources

- **Codex rollouts** (`~/.codex/sessions/**/*.jsonl`): turns, tool calls,
  compaction events, prompt-size curve and context-source attribution.
  Rollouts usually have no token counters, so prompt sizes are estimated from
  content length (approx. 4 chars/token) and reported as estimates.
- **Hermes** (`sessions.json`): real `input/output/cache_read/cache_write`
  totals plus estimated cost when the agent has finalized them.

Parsing is intentionally read-only: files are only opened and counted, never
executed or modified.

## Pricing

Costs are estimated from a small built-in price table (see `pricing.py`,
snapshot as of 2026-08). Prices change often and contracts differ, so set
your own table with the `AGENT_COST_PRICING` environment variable or edit the
table locally before trusting dollar figures.

## Roadmap

- `agent-cost compare`: same task across agents/providers
- `agent-cost watch`: budget thresholds with warnings before a session blows up
- OpenCode / Claude Code session parsing
- Tool-call-level cost attribution when providers expose per-request usage

## Contributing

Bug reports are especially welcome — particularly a session that parses
incorrectly. See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, tests, and how to
add support for a new session format. Please never attach a raw session file to
an issue; strip it first.

## Security

See [SECURITY.md](SECURITY.md). Session files are untrusted input; this tool
never executes them, never renders them, and never sends data anywhere.
