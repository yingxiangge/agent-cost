# Title: [Good First Issue] Add friendly validation for custom pricing JSON

## Description
When a user supplies a custom pricing card via `--pricing '<json>'` or `AGENT_COST_PRICING`, if a key or number format is invalid, we should provide clear, human-readable error messages pointing to the exact offending key.

## Requirements
- Validate that rate card entries have `input`, `output`, `cache_read`, `cache_write` (or standard subsets).
- Raise a friendly CLI error if values are non-numeric or negative.
- Add unit tests in `tests/test_pricing.py`.

Good first issue for anyone looking to contribute!
