# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed
- **Unknown models are no longer priced as DeepSeek.** `estimate_cost` fell back
  to the DeepSeek rate card for any model missing from the table and still
  reported the result as `estimated`, so sessions on unlisted models — including
  every current Claude model — were understated by roughly 13x while looking
  authoritative. Unpriced sessions now report `unknown` / `n/a`, are excluded
  from dollar totals, and are counted in the report footer.
- **GPT-5 rates corrected** from $15/$60 to $1.25/$10 per 1M tokens. Anything
  resolving through that entry (`gpt-5-codex`) was overstated by about 17x.
- **Model resolution is deterministic.** The previous bidirectional substring
  match (`key in name or name in key`) returned whichever table entry came first
  in dict order. Resolution is now exact match, then longest prefix, so
  `gpt-5-mini` is never priced as `gpt-5`.
- **`--pricing` merges instead of replacing.** Overriding one model previously
  discarded the entire built-in table, leaving every other model unpriced.
- **OpenCode no longer double-counts cached tokens.** `prompt_tokens` (OpenAI
  semantics) already includes `cached_tokens`, but both were added to the totals.
  The bundled example reported 14,530 tokens at a 45.4% hit rate; the correct
  figures are 8,130 and 83.1%. `input_tokens` (Anthropic semantics) is still
  taken as-is. Two tests had this bug baked into their assertions and were
  corrected.

### Changed
- Price table refreshed from Anthropic's official pricing page (2026-08-16):
  added Fable 5, Opus 5/4.8/4.7/4.6/4.1, Sonnet 5, Sonnet 4.6, and Haiku 4.5.
  Claude Code writes model ids like `claude-opus-5`, none of which the previous
  table covered.
- OpenCode support is documented as **experimental**: it parses a JSON export
  shape, not the SQLite session store current OpenCode actually writes.
- Added `pricing.example.json` as a template for supplying your own rate cards.

### Known approximations
- `cache_write` is priced at the 5-minute rate (1.25x input). The usage payload
  does not record which cache TTL was used, so sessions relying on the 1-hour
  cache (2x input) are undercounted.
- On a Claude Pro/Max subscription the dollar figures are shadow costs — what
  the tokens would have cost on metered API billing — not an actual bill.

### Added
- `agent-cost compare` command for cross-agent and multi-session comparison,
  outputting side-by-side token totals, cache efficiency rates, tool calls, and
  estimated USD costs, plus structured `--json` output.
- Claude Code parser (`src/agent_cost/parsers/claude.py`) supporting Anthropic API
  prompt caching breakdown (`cache_read_input_tokens`, `cache_creation_input_tokens`)
  and tool call tracking.
- OpenCode parser (`src/agent_cost/parsers/opencode.py`) supporting step-by-step
  turn usage, tool actions, and cached token tracking.
- Automatic parser detection (`src/agent_cost/parsers/detect.py`) for directory
  scanning and heterogeneous session loading.
- Expanded model pricing table in `pricing.py` covering Claude 3.5/3.7 Sonnet,
  Haiku, Opus, GPT-4o, o1, o3-mini, DeepSeek V3/R1, Qwen 2.5 Coder, and Gemini 1.5/2.0.
- Unit and CLI smoke tests covering compare commands, Claude Code, and OpenCode parsers.

## [0.1.0] - 2026-08-13

First public release.

### Added
- GitHub Actions CI running pytest on Python 3.10 / 3.11 / 3.12, plus a CLI
  smoke test against the bundled example sessions.
- Contributor documentation (`CONTRIBUTING.md`), issue and pull request
  templates.
- `agent-cost inspect` — per-session token, cache and cost breakdown.
- `agent-cost analyze` — context growth curve, context-source attribution
  (tool output / instructions / assistant / developer), compaction detection,
  and actionable recommendations.
- `agent-cost stats` — aggregate totals across a folder of sessions.
- Codex rollout parser (`~/.codex/sessions/**/*.jsonl`). Rollouts carry no token
  counters, so prompt sizes are estimated from content length (~4 chars/token)
  and are reported as estimates.
- Hermes `sessions.json` parser using real input / output / cache-read /
  cache-write totals.
- Built-in pricing table (snapshot as of 2026-08), overridable via the
  `AGENT_COST_PRICING` environment variable.
- Read-only guarantee: session files are opened and counted, never executed,
  modified, or transmitted (see `SECURITY.md`).

[Unreleased]: https://github.com/yingxiangge/agent-cost/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/yingxiangge/agent-cost/releases/tag/v0.1.0
