# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`agent-cost baseline` / `agent-cost diff`: did the change actually help?**
  `baseline` records the current rollup and a cutoff; `diff` re-reads only the
  sessions started after that cutoff and compares the two. The windows cover
  different spans, so the comparison is rates only — per turn, per session, and
  shares — and shares move in percentage points rather than percent-of-percent.
  Sessions with no readable timestamp are excluded and counted, never folded
  into the new window where they would flatter or spoil the result. Baselines
  are plain JSON under `~/.agent-cost/baselines/`, written and read locally.
- **Runs with no arguments.** Every subcommand now falls back to the locations
  the agents install into (`~/.claude/projects`, `~/.codex/sessions`,
  `~/.local/share/opencode/opencode.db`), so the first command after
  `pip install` is `agent-cost analyze` rather than a path you have to go find.
  When none of those exist, the error names the locations it looked in.
- **`analyze` rolls sessions up by default.** Over a few dozen sessions the
  per-session view scrolled past the answer; the rollup reports cache hit rate,
  prompt-to-output ratio per turn, context growth from first to last turn,
  where the context came from, which tools produced it, and how widespread the
  repeated reads and duplicate outputs are. `--per-session` prints the old
  per-session analyses, and `--json` follows whichever view is active.

### Fixed
- **OpenCode sessions had no timestamps.** The SQLite schema names them
  `time_created` / `time_updated` and stores epoch milliseconds; the parser
  read `created_at` / `updated_at`, which never matched, leaving every
  database-backed session undated. On one machine that was 119 of 216 sessions,
  all of which would have been excluded from baseline comparisons. JSON exports
  carrying ISO `created_at` keep working.

## [0.4.0] - 2026-08-30

### Added
- **Repeated tool output & file read detection.** `agent-cost analyze` now detects
  files read multiple times across turns and exact duplicate command outputs via
  SHA-256 output fingerprints without retaining raw transcript payloads. Added
  type-specific mitigation suggestions and `agent-cost analyze --json` support (#9).
  Contributed by [@mikemikimike](https://github.com/mikemikimike).

### Fixed
- Custom pricing overrides now fail with a clear CLI error when a rate card has
  missing, unknown, non-numeric, or negative values (#5).
  Contributed by [@kkkhs](https://github.com/kkkhs).

## [0.3.1] - 2026-08-28

### Fixed
- **Screenshots are no longer counted as file-read text.** A `tool_result`
  image block carries its pixels as base64 under `source.data`, and the Claude
  parser stringified the whole block into its character count: a single 1080x1920
  screenshot was charged ~600,000 characters. On a real session that put `Read`
  at 97.5% of tool output with a bogus ~124,706 chars/call average, buried the
  actual top source (`Bash`), and produced the wrong advice ("use windowed
  reads") for a session whose context was really going to screenshots.
  Images are now counted apart from the character pools and priced on their
  pixel dimensions (`width * height / 750`, capped at the per-image ceiling,
  read from the PNG/JPEG header without decoding the body). `analyze` reports
  them on their own line with a suggestion of their own, and `tool_stats` gains
  `images` / `image_tokens` per tool. Codex and OpenCode read their tool output
  from string fields and were never affected.

## [0.3.0] - 2026-08-28

### Added
- **Per-tool output attribution & type-specific optimization suggestions.**
  - Parsers for Claude Code, Codex, and OpenCode now correlate `tool_result` / `function_call_output` payloads back to the originating tool name (`Bash`, `view_file`, `ripgrep`, `grep_search`, etc.).
  - `agent-cost analyze` breaks down tool output percentage, call count, and average payload size per tool.
  - Automatically classifies tools into 6 standard categories (Shell, File Read, Search/Grep, File Edit, Web/Browser, Subagents) and generates actionable, type-specific suggestions to curb context bloat.

## [0.2.1] - 2026-08-23

### Changed
- **The PyPI distribution is named `agent-cost-tracker`.** `agent-cost` is
  refused by PyPI: it already hosts `agentcost`, and PyPI compares names after
  stripping `.`/`_`/`-` and folding `l`/`i` to `1` and `o` to `0`, under which
  both collapse to `agentc0st`. Only the distribution name changes — the
  command installed is still `agent-cost`, and the repository keeps its name.

## [0.2.0] - 2026-08-23

### Added
- **Per-turn billing modes.** `usage.speed` and `usage.inference_geo` decide
  which rate card a turn is billed on and can change mid-session, so usage is
  now split into `(speed, inference_geo)` buckets and each is priced separately.
  Fast mode bills Opus 5 / Opus 4.8 at $10/$50 instead of $5/$25; US-pinned
  inference adds 1.1x on every category; the two stack. Parsers that cannot
  observe these modes (Codex, Hermes, OpenCode) record no buckets and are
  priced off the flat totals exactly as before.
- **OpenCode SQLite session store.** `~/.local/share/opencode/opencode.db` is
  read directly through a read-only URI, alongside the existing JSON/JSONL
  exports, giving real per-turn `input` / `output` / `cache.read` /
  `cache.write` counts instead of empty sessions.
- **PyPI release workflow** (`.github/workflows/publish.yml`): builds, runs
  `twine check`, and publishes through trusted publishing on a GitHub release.
- **`--subscription`** reports costs as API-equivalent value rather than money
  spent, for Claude Pro/Max sessions that generate no per-token charges. The
  flag is explicit because transcripts carry no field distinguishing
  subscription from metered API usage (`service_tier` is `standard` for both).

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

### Fixed
- **The build no longer fails on modern setuptools.** `license = "MIT"` is a
  PEP 639 expression, and setuptools >= 77 rejects a project that also carries
  a `License ::` classifier — which took down both CI (`pip install -e .`) and
  the publish workflow, since each resolves setuptools in an isolated build
  environment. The classifier is removed and `requires` raised to `>= 77`.
- **The OpenCode SQLite parser no longer under-reports silently.** A bare
  `except Exception: pass` around the message loop meant the first unreadable
  row ended the scan and the partial totals were returned as if complete
  (measured: 1 turn / 100 tokens instead of 2 / 200, nothing on stderr). Bad
  rows are now counted and reported; the rows after them still count. BLOB
  `data` columns are decoded rather than dropped, and the unreachable
  read-write connection fallback — which contradicted the read-only guarantee
  — is gone.
- **An unrelated SQLite database is no longer reported as OpenCode sessions.**
  `session` and `message` are generic table names; a database matching that
  shape with no usage payload at all is now ignored with a note on stderr,
  instead of contributing rows counted from whatever `tool` keys it happened
  to contain.
- **Tool calls in a `toolCalls` list are counted individually.** A single
  assistant message carrying three tool invocations was counted as one call,
  under-reporting every multi-tool turn, and `str()` on the list billed its
  brackets and quotes as tool content. An explicitly empty list now counts
  zero calls instead of one.
- **Format detection no longer stops after 15 lines.** It streams the file until
  a signature appears, so a transcript whose opening lines are metadata and user
  text is no longer misclassified. Five of 72 real Claude Code transcripts were
  being reported as OpenCode sessions.
- **Files that parse to zero usage are reported on stderr** instead of quietly
  joining the totals as zeros — the signature of a misdetected format is
  indistinguishable from a genuinely empty session otherwise.

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
- Added `pricing.example.json` as a template for supplying your own rate cards.

### Known approximations
- `cache_write` is priced at the 5-minute rate (1.25x input). The usage payload
  does not record which cache TTL was used, so sessions relying on the 1-hour
  cache (2x input) are undercounted.
- OpenCode's native `tokens.input` is assumed to exclude `cache.read`
  (Anthropic semantics). The AI SDK flattens every provider onto that one key,
  so an OpenAI-backed OpenCode session double-counts the cached prefix. Needs
  checking against a real OpenAI-backed `opencode.db`.
- On a Claude Pro/Max subscription the dollar figures are shadow costs — what
  the tokens would have cost on metered API billing — not an actual bill.

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

[Unreleased]: https://github.com/yingxiangge/agent-cost/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/yingxiangge/agent-cost/compare/v0.3.1...v0.4.0
[0.3.1]: https://github.com/yingxiangge/agent-cost/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/yingxiangge/agent-cost/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/yingxiangge/agent-cost/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/yingxiangge/agent-cost/compare/v0.1.1...v0.2.0
[0.1.0]: https://github.com/yingxiangge/agent-cost/releases/tag/v0.1.0
