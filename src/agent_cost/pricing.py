from __future__ import annotations

from typing import Optional

# USD per 1M tokens. Snapshot as of 2026-08; prices change frequently.
# Override with `agent-cost --pricing '{"model": {...}}'` or the AGENT_COST_PRICING
# environment variable when your contract differs from the public list price.
PRICING: dict[str, dict[str, float]] = {
    # DeepSeek
    "deepseek-chat": {"input": 0.27, "output": 1.10, "cache_read": 0.07, "cache_write": 0.27},
    "deepseek-v3": {"input": 0.27, "output": 1.10, "cache_read": 0.07, "cache_write": 0.27},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19, "cache_read": 0.14, "cache_write": 0.55},
    "deepseek-r1": {"input": 0.55, "output": 2.19, "cache_read": 0.14, "cache_write": 0.55},

    # Anthropic
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-7-sonnet": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-7-sonnet-20250219": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
    "claude-3-opus": {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},

    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.0, "cache_read": 1.25, "cache_write": 2.50},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": 0.15},
    "o1": {"input": 15.0, "output": 60.0, "cache_read": 7.5, "cache_write": 15.0},
    "o3-mini": {"input": 1.10, "output": 4.40, "cache_read": 0.55, "cache_write": 1.10},
    "gpt-5": {"input": 15.0, "output": 60.0, "cache_read": 1.5, "cache_write": 15.0},
    "gpt-5-mini": {"input": 0.25, "output": 2.0, "cache_read": 0.025, "cache_write": 0.25},

    # Qwen
    "qwen-2.5-coder": {"input": 0.30, "output": 1.20, "cache_read": 0.03, "cache_write": 0.30},
    "qwen-max": {"input": 1.60, "output": 6.40, "cache_read": 0.16, "cache_write": 1.60},

    # Google Gemini
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "cache_read": 0.025, "cache_write": 0.10},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00, "cache_read": 0.3125, "cache_write": 1.25},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30, "cache_read": 0.01875, "cache_write": 0.075},
}


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    model: str = "",
    custom_pricing: dict | None = None,
) -> tuple[Optional[float], str]:
    """Estimate session cost in USD. Returns (cost, status)."""
    prices = custom_pricing or PRICING
    key = (model or "").lower().split("/")[-1]

    # Prefix match if exact key not found (e.g. claude-3-5-sonnet matches claude-3-5-sonnet-...)
    table = prices.get(key)
    if not table:
        for k, v in prices.items():
            if key and (key in k or k in key):
                table = v
                break
    if not table:
        table = prices.get("deepseek-chat")

    if not table:
        return None, "unknown"
    cost = (
        input_tokens * table.get("input", 0.0)
        + cache_read_tokens * table.get("cache_read", 0.0)
        + cache_write_tokens * table.get("cache_write", 0.0)
        + output_tokens * table.get("output", 0.0)
    ) / 1_000_000.0
    return cost, "estimated"
