from __future__ import annotations

from agent_cost.compare import CompareResult
from agent_cost.models import SessionStats


def _num(value: int) -> str:
    return f"{value:,}"


def _usd(cost: float, status: str, width: int = 0) -> str:
    """Render a dollar figure, or `n/a` when the model has no rate card.

    A session with an unknown model must never render as `0.00`: that reads as
    "this was free" instead of "this was not priced".
    """
    text = "n/a" if status == "unknown" else f"{cost:.2f}"
    return f"{text:>{width}}" if width else text


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
    if stats.cost_status == "unknown":
        hint = f"no rate card for model '{stats.model}'" if stats.model else "model not recorded in session"
        lines.append(f"Estimated Cost    n/a  ({hint}; set one with --pricing)")
    else:
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
    header = f"{'AGENT':<12} {'TOTAL TOKENS':>14} {'CACHED %':>9} {'TOOL CALLS':>11} {'EST. USD':>10}  SESSION"
    lines = [header, "-" * len(header)]
    for r in sorted(rows, key=lambda x: x.total_tokens, reverse=True):
        key = r.session_key[:48] if r.session_key else "?"
        lines.append(
            f"{r.agent:<12} {_num(r.total_tokens):>14} {r.cache_hit_rate*100:>8.1f}% "
            f"{r.tool_calls:>11} {_usd(r.estimated_cost_usd, r.cost_status, 10)}  {key}"
        )
    unpriced = sum(1 for r in rows if r.cost_status == "unknown")
    if unpriced:
        lines.append("")
        lines.append(f"n/a = no rate card for that model ({unpriced} of {len(rows)}); set one with --pricing.")
    return "\n".join(lines)


def format_compare(result: CompareResult, by_agent: bool = True) -> str:
    lines = [
        "Agent Comparison Report",
        "═" * 78,
    ]

    # Agent Summary Table
    header = f"{'AGENT':<14} {'SESSIONS':>8} {'TOTAL TOKENS':>14} {'CACHED %':>9} {'TOOLS':>7} {'EST. USD':>10} {'AVG $/SESS':>11}"
    lines.append(header)
    lines.append("-" * len(header))

    for name, s in sorted(result.agent_summaries.items(), key=lambda x: x[1].total_tokens, reverse=True):
        if s.unpriced_sessions >= s.session_count:
            cost_cell, avg_cell = f"{'n/a':>10}", f"{'n/a':>11}"
        elif s.unpriced_sessions:
            # Partial coverage: the total is real but incomplete.
            cost_cell, avg_cell = f"{s.estimated_cost_usd:>9.2f}*", f"{s.avg_cost_per_session:>11.2f}"
        else:
            cost_cell, avg_cell = f"{s.estimated_cost_usd:>10.2f}", f"{s.avg_cost_per_session:>11.2f}"
        lines.append(
            f"{name:<14} {s.session_count:>8} {_num(s.total_tokens):>14} {s.cache_hit_rate*100:>8.1f}% "
            f"{s.tool_calls:>7} {cost_cell} {avg_cell}"
        )

    lines.append("-" * len(header))
    if result.unpriced_sessions >= result.total_sessions:
        total_cell = f"{'n/a':>10}"
    elif result.unpriced_sessions:
        total_cell = f"{result.total_cost_usd:>9.2f}*"
    else:
        total_cell = f"{result.total_cost_usd:>10.2f}"
    lines.append(
        f"{'TOTAL':<14} {result.total_sessions:>8} {_num(result.total_tokens):>14} "
        f"{'':>9} {'':>7} {total_cell}"
    )
    lines.append("")

    # Detailed session breakdown if multiple sessions
    if not by_agent or len(result.sessions) <= 10:
        lines.append("Session Details:")
        lines.append(f"{'AGENT':<12} {'MODEL':<20} {'TOTAL TOKENS':>12} {'CACHED %':>9} {'EST. USD':>9}  SESSION")
        lines.append("-" * 78)
        for r in sorted(result.sessions, key=lambda x: x.total_tokens, reverse=True):
            m = r.model[:18] if r.model else "-"
            key = r.session_key[:24] if r.session_key else "?"
            lines.append(
                f"{r.agent:<12} {m:<20} {_num(r.total_tokens):>12} {r.cache_hit_rate*100:>8.1f}% "
                f"{_usd(r.estimated_cost_usd, r.cost_status, 9)}  {key}"
            )
        lines.append("")

    if result.unpriced_sessions:
        lines.append(
            f"n/a / * = model has no rate card, excluded from dollar totals "
            f"({result.unpriced_sessions} of {result.total_sessions} sessions)."
        )
        lines.append("")

    # Key Insights
    if result.insights:
        lines.append("Key Insights:")
        for ins in result.insights:
            lines.append(f"  • {ins}")

    return "\n".join(lines)
