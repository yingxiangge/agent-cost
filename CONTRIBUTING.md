# Contributing to agent-cost

Thanks for taking a look. This is a small, focused tool and contributions of
any size are welcome — including bug reports with a session file that parses
incorrectly.

## Ground rules

**agent-cost is strictly read-only.** It opens session files, counts things,
and prints a report. It must never execute, modify, upload, or otherwise act on
the files it reads. Session files are treated as untrusted input (see
[SECURITY.md](SECURITY.md)). Any contribution that adds network calls, writes
to session files, or evaluates their content will be declined regardless of how
useful the feature is.

**Never commit real session data.** Session files contain prompts, code, and
sometimes credentials. The files in `examples/` are sanitized. If you need a
new fixture, strip it first and name it `*.sanitized.*`.

## Development setup

```bash
git clone https://github.com/yingxiangge/agent-cost
cd agent-cost
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install pytest
```

## Running tests

```bash
pytest -q
```

Also worth running the CLI against the bundled examples — this is what CI does:

```bash
agent-cost inspect examples/codex_rollout.sanitized.jsonl
agent-cost analyze examples/codex_rollout.sanitized.jsonl
agent-cost inspect examples/hermes_sessions.sanitized.json
```

## Adding a new session format

Parsers live in `src/agent_cost/`. A new one should:

1. Detect its own format rather than relying on the file extension.
2. Report token counts as **estimates** when the source has no real counters
   (Codex rollouts, for example, are estimated at ~4 chars/token). Never present
   an estimate as if it were a measured value.
3. Ship a sanitized fixture in `examples/` and a test in `tests/`.

## Pricing tables

The built-in price table is a snapshot and goes stale quickly. If you update it,
say in the PR where the numbers came from and when. Users who care about exact
figures should be setting `AGENT_COST_PRICING` themselves.

## Pull requests

- Keep the change focused; one concern per PR.
- Include a test when you fix a parsing bug — ideally the fixture that broke it.
- CI runs pytest on Python 3.10 / 3.11 / 3.12; all three must pass.
