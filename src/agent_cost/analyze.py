from __future__ import annotations

from agent_cost.models import SessionStats


def analyze(stats: SessionStats) -> dict:
    """Derive actionable signals from session statistics."""
    signals: dict = {"recommendations": [], "context_growth": None, "largest_sources": []}

    samples = [s["estimated_prompt_tokens"] for s in stats.context_samples]
    if len(samples) >= 4:
        half = len(samples) // 2
        first = sum(samples[:half]) / half
        second = sum(samples[half:]) / (len(samples) - half)
        ratio = second / first if first else 0.0
        signals["context_growth"] = {
            "first_half_avg": round(first),
            "second_half_avg": round(second),
            "growth_ratio": round(ratio, 2),
        }
        if ratio >= 2.5:
            signals["recommendations"].append(
                "Prompt size is growing steeply; start a fresh session instead of continuing."
            )
        elif ratio >= 1.6:
            signals["recommendations"].append(
                "Context is growing steadily; budget a /compact or a new session soon."
            )

    if stats.compaction_events:
        signals["recommendations"].append(
            f"Session was already compacted {stats.compaction_events}x; further work belongs in a new session."
        )

    if stats.turns >= 25 and not stats.context_samples:
        signals["recommendations"].append("High turn count; review whether a new session would be cheaper.")

    has_cache_data = bool(stats.cache_read_tokens or stats.cache_write_tokens)
    if has_cache_data and stats.cache_hit_rate < 0.4 and stats.prompt_tokens:
        signals["recommendations"].append(
            "Low cache hit rate; same-prefix reuse is low, which usually inflates input cost."
        )

    total_chars = sum(stats.source_chars.values())
    if total_chars:
        ranked = sorted(stats.source_chars.items(), key=lambda kv: kv[1], reverse=True)[:4]
        signals["largest_sources"] = [
            {"source": k, "percent": round(v * 100 / total_chars, 1)} for k, v in ranked
        ]
        if any(k == "tool_output" for k, _ in ranked[:2]):
            signals["recommendations"].append(
                "Tool output dominates context; consider truncating or filtering large command output."
            )

    return signals
