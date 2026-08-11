from __future__ import annotations

from typing import Optional

# USD per 1M tokens. Snapshot as of 2026-08; prices change frequently.
# Override with `agent-cost --pricing '{"model": {...}}'` or the PRICING_JSON
# environment variable when your contract differs from the public list price.
PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.55, "output": 2.19, "cache_read": 0.028, "cache_write": 0.55},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19, "cache_read": 0.14, "cache_write": 0.55},
    "gpt-5": {"input": 15.0, "output": 60.0, "cache_read": 1.5, "cache_write": 15.0},
    "gpt-5-mini": {"input": 0.25, "output": 2.0, "cache_read": 0.025, "cache_write": 0.25},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
}


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    model: str = "",
) -> tuple[Optional[float], str]:
    """Estimate session cost in USD. Returns (cost, status)."""
    key = (model or "").lower().split("/")[-1]
    table = PRICING.get(key) or PRICING.get("deepseek-chat")
    if not table:
        return None, "unknown"
    cost = (
        input_tokens * table["input"]
        + cache_read_tokens * table["cache_read"]
        + cache_write_tokens * table["cache_write"]
        + output_tokens * table["output"]
    ) / 1_000_000.0
    return cost, "estimated"
