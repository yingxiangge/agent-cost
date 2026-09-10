from __future__ import annotations

from agent_cost.analyze import NO_TOOL_CULPRIT
from agent_cost.compare import CompareResult
from agent_cost.models import SessionStats


def _is_empty_session(stats: SessionStats) -> bool:
    """A session that recorded nothing: no tokens, no turns, no tool calls."""
    return stats.total_tokens == 0 and stats.turns == 0 and stats.tool_calls == 0


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
    elif stats.cost_status == "included":
        lines.append(f"API-equiv. Value  ${cost:.2f}  (included in subscription, not billed)")
    else:
        lines.append(f"Estimated Cost    ${cost:.2f}  ({stats.cost_status})")

    modes = [m for m in stats.billing_buckets if not m.startswith("standard|")]
    if modes and len(stats.billing_buckets) > 1:
        lines.append(f"Billing modes     {', '.join(sorted(stats.billing_buckets))}")
    return "\n".join(lines)


def _fmt_tokens(n: int) -> str:
    """Render a token count compactly: 168000 -> 168K."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n // 1000}K"
    return str(n)


def _budget_rows(tracked: dict) -> list[dict]:
    """Pick the turns worth printing: the ends, the crossings, the worst jump.

    A long session has hundreds of samples and printing them all buries the
    four that carry the story, so the curve is sampled rather than dumped.
    """
    curve = tracked["curve"]
    wanted = {curve[0]["turn"], curve[-1]["turn"]}
    for key in ("warning_turn", "critical_turn"):
        if tracked[key] is not None:
            wanted.add(tracked[key])
    if tracked["biggest_jump"]:
        wanted.add(tracked["biggest_jump"]["turn"])
    return [entry for entry in curve if entry["turn"] in wanted]


def _format_budget_block(tracked: dict | None) -> list[str]:
    """Render the prompt curve against its budget, naming what inflated it."""
    if not tracked or not tracked["curve"]:
        return []

    jump_turn = tracked["biggest_jump"]["turn"] if tracked["biggest_jump"] else None
    rows = _budget_rows(tracked)
    lines = [
        f"Context budget: warning {_fmt_tokens(tracked['warning'])} | "
        f"critical {_fmt_tokens(tracked['critical'])}"
    ]
    previous_turn = None
    for entry in rows:
        if previous_turn is not None and entry["turn"] not in (previous_turn, previous_turn + 1):
            lines.append("  ...")
        previous_turn = entry["turn"]

        delta = entry["delta"]
        delta_text = f"{delta:+,}" if delta is not None else ""
        marks = []
        if entry["level"] != "ok":
            marks.append(f"[{entry['level']}]")
        if entry["turn"] == jump_turn:
            culprit = tracked["biggest_jump"]["culprit"]
            if culprit == NO_TOOL_CULPRIT:
                marks.append(f"biggest jump, {culprit}")
            elif culprit:
                marks.append(f"biggest jump by {culprit}")
            else:
                marks.append("biggest jump")
        suffix = f"  {' '.join(marks)}" if marks else ""
        lines.append(
            f"  turn {entry['turn']:>4}  "
            f"{_fmt_tokens(entry['estimated_prompt_tokens']):>7}  "
            f"{delta_text:>9}{suffix}"
        )
    return lines


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
    if signals.get("tool_breakdown"):
        lines.append("Tool output breakdown:")
        for item in signals["tool_breakdown"][:6]:
            avg_str = f"~{item['avg_chars_per_call']:,} chars/call"
            img_str = (
                f" +{item['images']} img ~{item['image_tokens']:,} tok"
                if item.get("images")
                else ""
            )
            lines.append(
                f"  {item['tool']:<18} {item['percent']:>5.1f}%  "
                f"({item['output_chars']:,} chars, {item['calls']} calls, {avg_str}{img_str}) "
                f"[{item['category_label']}]"
            )
    if signals.get("repeated_file_reads"):
        lines.append("Repeated file reads:")
        for item in signals["repeated_file_reads"][:6]:
            lines.append(f"  {item['path']}  {item['reads']} reads")
    if signals.get("repeated_tool_output"):
        lines.append("Repeated tool output:")
        for item in signals["repeated_tool_output"][:6]:
            lines.append(
                f"  {item['tool']:<18} {item['duplicate_calls']} duplicate calls, "
                f"~{item['repeated_chars']:,} repeated chars"
            )
    if signals.get("image_summary"):
        summary = signals["image_summary"]
        via = ", ".join(
            f"{t['tool']} x{t['images']}" for t in summary["tools"][:3]
        )
        lines.append(
            f"Images: {summary['images']} attached, ~{summary['image_tokens']:,} tokens"
            + (f" (via {via})" if via else "")
        )
    if stats.compaction_events:
        lines.append(f"Compactions: {stats.compaction_events}")
    lines.extend(_format_budget_block(signals.get("context_budget")))
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

    # Key Insights sit above the per-session table: the table can run to dozens
    # of rows, and a reader who scrolls to the bottom of it should not have to
    # scroll back up to find what the numbers mean.
    if result.insights:
        lines.append("Key Insights:")
        for ins in result.insights:
            lines.append(f"  • {ins}")
        lines.append("")

    # Detailed session breakdown if multiple sessions
    if not by_agent or len(result.sessions) <= 10:
        lines.append("Session Details:")
        lines.append(f"{'AGENT':<12} {'MODEL':<20} {'TOTAL TOKENS':>12} {'CACHED %':>9} {'EST. USD':>9}  SESSION")
        lines.append("-" * 78)
        shown = [r for r in result.sessions if not _is_empty_session(r)]
        hidden = len(result.sessions) - len(shown)
        for r in sorted(shown, key=lambda x: x.total_tokens, reverse=True):
            m = r.model[:18] if r.model else "-"
            key = r.session_key[:24] if r.session_key else "?"
            lines.append(
                f"{r.agent:<12} {m:<20} {_num(r.total_tokens):>12} {r.cache_hit_rate*100:>8.1f}% "
                f"{_usd(r.estimated_cost_usd, r.cost_status, 9)}  {key}"
            )
        if hidden:
            # Empty sessions carry no information and are numerous enough to
            # fill the last screen with zeros, burying the totals above them.
            lines.append(
                f"({hidden} session(s) with no recorded usage omitted; --json lists every session)"
            )
        lines.append("")

    if result.unpriced_sessions:
        lines.append(
            f"n/a / * = model has no rate card, excluded from dollar totals "
            f"({result.unpriced_sessions} of {result.total_sessions} sessions)."
        )
        lines.append("")

    if any(s.cost_status == "included" for s in result.sessions):
        lines.append(
            "Dollar figures are API-equivalent value, not money spent: these sessions "
            "run on a subscription."
        )
        lines.append("")

    return "\n".join(lines)


def format_summary(summary: dict) -> str:
    """One screen for a whole machine: the rollup `analyze` prints by default."""
    t = summary["totals"]
    agents = ", ".join(t["agents"]) or "none"
    lines = [
        f"{_num(t['sessions'])} sessions · {agents} · {_num(t['turns'])} turns",
        "──────────────────────────────",
        f"Prompt tokens   {_num(t['prompt_tokens']):>18}",
        f"  cache read    {_num(t['cache_read_tokens']):>18}   {t['cache_hit_rate'] * 100:>5.1f}%",
        f"  cache write   {_num(t['cache_write_tokens']):>18}",
        f"  new           {_num(t['input_tokens']):>18}",
        f"Output          {_num(t['output_tokens']):>18}",
    ]
    if t["context_to_output_ratio"]:
        lines.append(
            f"Per turn        {_num(t['prompt_per_turn'])} prompt -> "
            f"{_num(t['output_per_turn'])} output  ({t['context_to_output_ratio']:.0f}:1)"
        )

    g = summary.get("context_growth")
    if g and g["growth_ratio"]:
        lines.append(
            f"Context growth  {_num(g['first_turn_avg'])} -> {_num(g['last_turn_avg'])} tokens "
            f"(x{g['growth_ratio']}, avg first vs last turn over {g['sessions']} sessions)"
        )

    if summary["sources"]:
        lines.append("")
        lines.append("Where the context comes from")
        for item in summary["sources"][:6]:
            lines.append(f"  {item['source']:<16} {item['pct'] * 100:>5.1f}%")

    tools = [item for item in summary["tools"] if item["output_chars"] > 0]
    if tools:
        lines.append("")
        lines.append("Tools producing that output")
        for item in tools[:5]:
            lines.append(
                f"  {item['tool']:<16} {item['pct'] * 100:>5.1f}%  "
                f"({_num(item['calls'])} calls)"
            )

    w = summary["waste"]
    waste_lines = []
    if w["repeated_file_reads"]:
        waste_lines.append(
            f"  repeated file reads    {_num(w['repeated_file_reads'])} files "
            f"across {w['repeated_file_read_sessions']} sessions"
        )
    if w["repeated_tool_outputs"]:
        waste_lines.append(
            f"  duplicate tool output  {_num(w['repeated_tool_outputs'])} outputs "
            f"across {w['repeated_tool_output_sessions']} sessions"
        )
    if w["compaction_events"]:
        waste_lines.append(f"  compactions            {_num(w['compaction_events'])}")
    if waste_lines:
        lines.append("")
        lines.append("Waste signals")
        lines.extend(waste_lines)

    lines.append("")
    lines.append("Run with --per-session for the per-session breakdown.")
    return "\n".join(lines)


def _delta_pct(value: float | None) -> str:
    if value is None:
        return "     —"
    return f"{value * 100:+6.1f}%"


def _metric_value(value: float, unit: str) -> str:
    if unit == "share":
        return f"{value * 100:.1f}%"
    if unit == "ratio":
        return f"{value:,.1f}"
    return f"{round(value):,}"


def format_diff(label: str, cutoff: str, diff: dict, undateable: int = 0) -> str:
    """Render a baseline comparison. Rates only — see agent_cost.baseline."""
    w = diff["windows"]
    lines = [
        f"{label} (saved {cutoff[:10]}, {_num(w['before_sessions'])} sessions, "
        f"{_num(w['before_turns'])} turns)",
        f"  vs since then ({_num(w['after_sessions'])} sessions, {_num(w['after_turns'])} turns)",
        "──────────────────────────────",
        f"{'':<22}{'BEFORE':>12}{'AFTER':>12}{'CHANGE':>10}",
    ]
    for m in diff["metrics"]:
        change = (
            f"{m['delta_pt'] * 100:+6.1f}pt"
            if "delta_pt" in m
            else _delta_pct(m["pct_change"])
        )
        lines.append(
            f"{m['name']:<22}"
            f"{_metric_value(m['before'], m['unit']):>12}"
            f"{_metric_value(m['after'], m['unit']):>12}"
            f"{change:>10}"
        )

    for title, key, name_key in (
        ("Context sources", "sources", "source"),
        ("Tool output", "tools", "tool"),
    ):
        rows = [r for r in diff[key] if abs(r["delta_pt"]) >= 0.001][:5]
        if not rows:
            continue
        lines.append("")
        lines.append(f"{title:<22}{'BEFORE':>12}{'AFTER':>12}{'CHANGE':>10}")
        for r in rows:
            lines.append(
                f"  {r[name_key]:<20}"
                f"{r['before_pct'] * 100:>11.1f}%"
                f"{r['after_pct'] * 100:>11.1f}%"
                f"{r['delta_pt'] * 100:>9.1f}pt"
            )

    if diff["waste"]:
        lines.append("")
        lines.append(f"{'Waste per session':<22}{'BEFORE':>12}{'AFTER':>12}{'CHANGE':>10}")
        for r in diff["waste"]:
            lines.append(
                f"  {r['name']:<22}{r['before']:>10.2f}{r['after']:>12.2f}"
                f"{_delta_pct(r['pct_change']):>10}"
            )

    lines.append("")
    lines.append(
        "Rates only: the two windows cover different spans, so totals are not comparable."
    )
    if undateable:
        tail = (
            "session carries no timestamp and is excluded."
            if undateable == 1
            else "sessions carry no timestamp and are excluded."
        )
        lines.append(f"{_num(undateable)} {tail}")
    return "\n".join(lines)
