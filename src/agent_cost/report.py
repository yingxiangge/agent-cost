from __future__ import annotations

from agent_cost.models import SessionStats


def _num(value: int) -> str:
    return f"{value:,}"


def format_inspect(stats: SessionStats, cost_override: float | None = None) -> str:
    lines = [
        "Agent Session",
        "──────────────────────────────",
        f"Agent            {stats.agent}",
        f"Session          {stats.session_key}",
    ]
    if stats.model:
        lines.append(f"Model             {stats.model}")
    if stats.platform:
        lines.append(f"Origin            {stats.platform}")
    if stats.created_at:
        lines.append(f"Created           {stats.created_at}")
    if stats.updated_at:
        lines.append(f"Updated           {stats.updated_at}")
    lines += [
        "",
        f"Input             {_num(stats.input_tokens)}",
        f"Cached input      {_num(stats.cache_read_tokens)}  {stats.cache_hit_rate*100:.1f}%",
        f"Cache writes      {_num(stats.cache_write_tokens)}",
        f"Output            {_num(stats.output_tokens)}",
        f"Total             {_num(stats.total_tokens)}",
        "",
    ]
    if stats.turns:
        lines.append(f"Turns             {stats.turns}")
    elif stats.context_samples and not stats.total_tokens:
        lines.append(
            f"Last prompt       {stats.context_samples[-1]['estimated_prompt_tokens']:,} tokens"
        )
    if stats.tool_calls:
        lines.append(f"Tool calls        {stats.tool_calls}")
    if stats.compaction_events:
        lines.append(f"Compactions       {stats.compaction_events}")
    cost = cost_override if cost_override is not None else stats.estimated_cost_usd
    lines.append(f"Estimated Cost    ${cost:.2f}  ({stats.cost_status})")
    return "\n".join(lines)


def format_analyze(stats: SessionStats, signals: dict) -> str:
    lines = [f"Analysis: {stats.session_key}", "──────────────────────────────"]
    if signals.get("context_growth"):
        g = signals["context_growth"]
        lines.append(
            f"Context growth: {g['first_half_avg']:,} -> {g['second_half_avg']:,} tokens "
            f"(x{g['growth_ratio']})"
        )
    if signals.get("largest_sources"):
        lines.append("Largest context sources:")
        for item in signals["largest_sources"]:
            lines.append(f"  {item['source']:<18} {item['percent']:>5.1f}%")
    if stats.compaction_events:
        lines.append(f"Compactions: {stats.compaction_events}")
    if stats.context_samples:
        def fmt_tok(n: int) -> str:
            return f"{n // 1000}K" if n >= 1000 else str(n)

        curve = " -> ".join(fmt_tok(s["estimated_prompt_tokens"]) for s in stats.context_samples[-6:])
        lines.append(f"Prompt curve: {curve}")
    if signals.get("recommendations"):
        lines.append("")
        lines.append("Recommendations:")
        for rec in signals["recommendations"]:
            lines.append(f"  - {rec}")
    else:
        lines.append("No immediate action needed.")
    return "\n".join(lines)


def format_stats_table(rows: list[SessionStats]) -> str:
    header = f"{'AGENT':<8} {'TOTAL TOKENS':>14} {'CACHED %':>9} {'TOOL CALLS':>11} {'EST. USD':>10}  SESSION"
    lines = [header, "-" * len(header)]
    for r in sorted(rows, key=lambda x: x.total_tokens, reverse=True):
        key = r.session_key[:48] if r.session_key else "?"
        lines.append(
            f"{r.agent:<8} {_num(r.total_tokens):>14} {r.cache_hit_rate*100:>8.1f}% "
            f"{r.tool_calls:>11} {r.estimated_cost_usd:>10.2f}  {key}"
        )
    return "\n".join(lines)
