**What this changes**

A short description of the change and why.

**Related issue**

Closes #

**Checklist**

- [ ] `pytest -q` passes locally
- [ ] CLI still runs against the bundled examples:
      `agent-cost inspect examples/codex_rollout.sanitized.jsonl`
- [ ] A test was added for any parsing bug fixed (ideally the fixture that broke it)
- [ ] No real session data committed — fixtures are sanitized and named `*.sanitized.*`
- [ ] No network calls, no writes to session files, no execution of session content
- [ ] `CHANGELOG.md` updated under `[Unreleased]`

**Pricing changes only**

If this touches the price table, say where the numbers came from and their date.
