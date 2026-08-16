from __future__ import annotations

from typing import Optional

# USD per 1M tokens. Snapshot as of 2026-08; prices change frequently.
#
# This table is deliberately incomplete. A model that is not listed here is
# reported as `unknown` and gets NO dollar figure -- a wrong number is worse
# than no number. Supply your own rates for anything missing (or for a
# contract that differs from the public list price) with:
#
#     agent-cost --pricing '{"claude-opus-5": {"input": 5, "output": 25,
#                            "cache_read": 0.5, "cache_write": 6.25}}' compare ...
#
# or by exporting AGENT_COST_PRICING with the same JSON. Entries you supply are
# merged over this table, so overriding one model leaves the rest intact.
# See examples/pricing.example.json for a starting template.
PRICING: dict[str, dict[str, float]] = {
    # DeepSeek
    "deepseek-chat": {"input": 0.27, "output": 1.10, "cache_read": 0.07, "cache_write": 0.27},
    "deepseek-v3": {"input": 0.27, "output": 1.10, "cache_read": 0.07, "cache_write": 0.27},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19, "cache_read": 0.14, "cache_write": 0.55},
    "deepseek-r1": {"input": 0.55, "output": 2.19, "cache_read": 0.14, "cache_write": 0.55},

    # Anthropic -- from platform.claude.com/docs/en/about-claude/pricing (2026-08-16).
    # `cache_write` uses the 5-minute rate (1.25x input). One-hour cache writes
    # cost 2x input, but the usage payload does not say which TTL was used, so
    # sessions relying on the 1h cache are undercounted here.
    "claude-fable-5": {"input": 10.0, "output": 50.0, "cache_read": 1.0, "cache_write": 12.50},
    "claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-8": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-7": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0, "cache_read": 0.50, "cache_write": 6.25},
    "claude-opus-4-1": {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},
    "claude-sonnet-5": {"input": 2.0, "output": 10.0, "cache_read": 0.20, "cache_write": 2.50},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-haiku-4-5": {"input": 1.0, "output": 5.0, "cache_read": 0.10, "cache_write": 1.25},
    "claude-3-5-sonnet": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-7-sonnet": {"input": 3.0, "output": 15.0, "cache_read": 0.30, "cache_write": 3.75},
    "claude-3-5-haiku": {"input": 0.80, "output": 4.0, "cache_read": 0.08, "cache_write": 1.0},
    "claude-3-opus": {"input": 15.0, "output": 75.0, "cache_read": 1.50, "cache_write": 18.75},

    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.0, "cache_read": 1.25, "cache_write": 2.50},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60, "cache_read": 0.075, "cache_write": 0.15},
    "o1": {"input": 15.0, "output": 60.0, "cache_read": 7.5, "cache_write": 15.0},
    "o3-mini": {"input": 1.10, "output": 4.40, "cache_read": 0.55, "cache_write": 1.10},
    "gpt-5": {"input": 1.25, "output": 10.0, "cache_read": 0.125, "cache_write": 1.25},
    "gpt-5-mini": {"input": 0.25, "output": 2.0, "cache_read": 0.025, "cache_write": 0.25},

    # Qwen
    "qwen-2.5-coder": {"input": 0.30, "output": 1.20, "cache_read": 0.03, "cache_write": 0.30},
    "qwen-max": {"input": 1.60, "output": 6.40, "cache_read": 0.16, "cache_write": 1.60},

    # Google Gemini
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40, "cache_read": 0.025, "cache_write": 0.10},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00, "cache_read": 0.3125, "cache_write": 1.25},
    "gemini-1.5-flash": {"input": 0.075, "output": 0.30, "cache_read": 0.01875, "cache_write": 0.075},
}


# Fast mode (research preview) trades price for latency and is billed at its own
# rates across the full context window. Only these models support it; on every
# other model `speed: "fast"` is either rejected or billed at standard rates.
# Cache multipliers still apply on top (5m write 1.25x, read 0.1x of fast input).
FAST_PRICING: dict[str, dict[str, float]] = {
    "claude-opus-5": {"input": 10.0, "output": 50.0, "cache_read": 1.0, "cache_write": 12.50},
    "claude-opus-4-8": {"input": 10.0, "output": 50.0, "cache_read": 1.0, "cache_write": 12.50},
}

# Pinning inference to a single geography costs a premium on every token
# category. `global` (the default) and `not_available` are standard priced.
GEO_MULTIPLIER: dict[str, float] = {"us": 1.1}


def resolve_pricing(model: str, custom_pricing: dict | None = None) -> Optional[dict[str, float]]:
    """Look up the rate card for `model`, or None when it is not known.

    Resolution is deterministic and never guesses across model families:

    1. `provider/model` is reduced to `model`, lowercased.
    2. An exact table key wins.
    3. Otherwise the LONGEST table key that `model` starts with wins, so
       `claude-opus-4-5-20260101` resolves to `claude-opus-4-5`, and
       `gpt-5-mini` prefers `gpt-5-mini` over `gpt-5`.
    4. No match returns None. There is no default rate card -- an unpriced
       session is reported as `unknown`, not silently priced as something else.
    """
    prices = {**PRICING, **custom_pricing} if custom_pricing else PRICING
    key = (model or "").lower().split("/")[-1].strip()
    if not key:
        return None

    exact = prices.get(key)
    if exact:
        return exact

    best: Optional[dict[str, float]] = None
    best_len = -1
    for name, table in prices.items():
        if key.startswith(name) and len(name) > best_len:
            best, best_len = table, len(name)
    return best


def estimate_cost(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    model: str = "",
    custom_pricing: dict | None = None,
    speed: str = "standard",
    inference_geo: str = "",
) -> tuple[Optional[float], str]:
    """Estimate cost in USD for one billing mode. Returns (cost, status).

    Returns (None, "unknown") when the model has no rate card, rather than
    falling back to an unrelated model's prices.

    `speed="fast"` switches to the fast-mode rate card where the model has one;
    a model without fast rates falls back to its standard card, matching the API
    (Opus 4.6 runs fast requests at standard speed and standard rates).
    `inference_geo="us"` applies the 1.1x data-residency premium on every
    category. Both multipliers stack, exactly as the pricing docs describe.
    """
    table = None
    if speed == "fast":
        table = FAST_PRICING.get((model or "").lower().split("/")[-1].strip())
        if custom_pricing:
            # A caller-supplied card always wins, including over fast rates.
            table = resolve_pricing(model, custom_pricing) or table
    if not table:
        table = resolve_pricing(model, custom_pricing)
    if not table:
        return None, "unknown"

    geo = GEO_MULTIPLIER.get((inference_geo or "").lower(), 1.0)
    cost = (
        input_tokens * table.get("input", 0.0)
        + cache_read_tokens * table.get("cache_read", 0.0)
        + cache_write_tokens * table.get("cache_write", 0.0)
        + output_tokens * table.get("output", 0.0)
    ) * geo / 1_000_000.0
    return cost, "estimated"


def estimate_session_cost(
    stats,
    custom_pricing: dict | None = None,
) -> tuple[Optional[float], str]:
    """Price a whole session, respecting per-turn billing modes.

    Fast mode can be toggled mid-session, and each mode is billed differently,
    so a session is priced per (speed, inference_geo) bucket and summed rather
    than by applying one rate card to the session totals. Sessions whose parser
    records no buckets (Codex, Hermes, OpenCode) fall back to the flat totals.

    Returns (None, "unknown") if ANY bucket lacks a rate card -- a partially
    priced session would understate silently.
    """
    buckets = getattr(stats, "billing_buckets", None)
    if not buckets:
        return estimate_cost(
            stats.input_tokens,
            stats.output_tokens,
            stats.cache_read_tokens,
            stats.cache_write_tokens,
            stats.model,
            custom_pricing,
        )

    total = 0.0
    for key, tokens in buckets.items():
        speed, _, geo = key.partition("|")
        cost, status = estimate_cost(
            tokens.get("input", 0),
            tokens.get("output", 0),
            tokens.get("cache_read", 0),
            tokens.get("cache_write", 0),
            stats.model,
            custom_pricing,
            speed=speed,
            inference_geo=geo,
        )
        if cost is None:
            return None, status
        total += cost
    return total, "estimated"
