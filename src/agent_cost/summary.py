"""Cross-session rollup: the whole machine on one screen.

`analyze` answers "what happened in this session". Run it over a few dozen
sessions and the answer scrolls past. This rolls the same signals up into the
handful of numbers that tell you whether you have a context problem at all.
"""

from __future__ import annotations

from agent_cost.models import SessionStats


def _prompt_tokens(stats: SessionStats) -> int:
    return stats.input_tokens + stats.cache_read_tokens + stats.cache_write_tokens


def summarize(pairs: list[tuple[SessionStats, dict]]) -> dict:
    """Roll up sessions and their analyze() signals into one report.

    `pairs` carries the signals alongside each session so the waste counts come
    from the same analysis the per-session view would print, rather than a
    second implementation that could drift from it.
    """
    sessions = [stats for stats, _ in pairs]
    agents = sorted({s.agent for s in sessions})

    totals = {
        "sessions": len(sessions),
        "agents": agents,
        "turns": sum(s.turns for s in sessions),
        "input_tokens": sum(s.input_tokens for s in sessions),
        "output_tokens": sum(s.output_tokens for s in sessions),
        "cache_read_tokens": sum(s.cache_read_tokens for s in sessions),
        "cache_write_tokens": sum(s.cache_write_tokens for s in sessions),
    }
    prompt = sum(_prompt_tokens(s) for s in sessions)
    totals["prompt_tokens"] = prompt
    totals["cache_hit_rate"] = (
        totals["cache_read_tokens"] / prompt if prompt else 0.0
    )

    turns = totals["turns"]
    per_turn_prompt = prompt / turns if turns else 0.0
    per_turn_output = totals["output_tokens"] / turns if turns else 0.0
    totals["prompt_per_turn"] = round(per_turn_prompt)
    totals["output_per_turn"] = round(per_turn_output)
    totals["context_to_output_ratio"] = (
        round(per_turn_prompt / per_turn_output, 1) if per_turn_output else None
    )

    # Context growth: average first turn against average last turn. Sessions
    # with a single sample have nothing to grow from and are left out.
    firsts, lasts = [], []
    for stats in sessions:
        samples = [s["estimated_prompt_tokens"] for s in stats.context_samples]
        if len(samples) >= 2:
            firsts.append(samples[0])
            lasts.append(samples[-1])
    growth = None
    if firsts:
        first_avg = sum(firsts) / len(firsts)
        last_avg = sum(lasts) / len(lasts)
        growth = {
            "sessions": len(firsts),
            "first_turn_avg": round(first_avg),
            "last_turn_avg": round(last_avg),
            "growth_ratio": round(last_avg / first_avg, 1) if first_avg else None,
        }

    # Where the characters came from, and which tools produced the output.
    sources: dict[str, int] = {}
    for stats in sessions:
        for key, chars in stats.source_chars.items():
            sources[key] = sources.get(key, 0) + chars
    source_total = sum(sources.values())

    tools: dict[str, dict[str, int]] = {}
    for stats in sessions:
        for name, entry in stats.tool_stats.items():
            agg = tools.setdefault(name, {"calls": 0, "output_chars": 0})
            agg["calls"] += entry.get("calls", 0)
            agg["output_chars"] += entry.get("output_chars", 0)
    tool_total = sum(t["output_chars"] for t in tools.values())

    # Waste: how much of it, and how widespread. A signal in 1 session of 80 is
    # a bad session; the same signal in 60 of 80 is how you work.
    repeated_reads = sum(len(sig["repeated_file_reads"]) for _, sig in pairs)
    repeated_outputs = sum(len(sig["repeated_tool_output"]) for _, sig in pairs)

    return {
        "totals": totals,
        "context_growth": growth,
        "sources": _ranked(sources, source_total),
        "tools": [
            {
                "tool": name,
                "calls": agg["calls"],
                "output_chars": agg["output_chars"],
                "pct": agg["output_chars"] / tool_total if tool_total else 0.0,
            }
            for name, agg in sorted(
                tools.items(), key=lambda kv: kv[1]["output_chars"], reverse=True
            )
        ],
        "waste": {
            "repeated_file_reads": repeated_reads,
            "repeated_file_read_sessions": sum(
                1 for _, sig in pairs if sig["repeated_file_reads"]
            ),
            "repeated_tool_outputs": repeated_outputs,
            "repeated_tool_output_sessions": sum(
                1 for _, sig in pairs if sig["repeated_tool_output"]
            ),
            "compaction_events": sum(s.compaction_events for s in sessions),
        },
    }


def _ranked(counts: dict[str, int], total: int) -> list[dict]:
    return [
        {"source": key, "chars": chars, "pct": chars / total if total else 0.0}
        for key, chars in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    ]
