# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
