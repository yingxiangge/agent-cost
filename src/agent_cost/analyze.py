from __future__ import annotations

from agent_cost.models import SessionStats

_TOOL_CATEGORIES = {
    "web": ("web", "Web / Browser"),
    "search": ("search", "Search / Grep"),
    "file_edit": ("file_edit", "File Edit"),
    "file_read": ("file_read", "File Read"),
    "shell": ("shell", "Shell / Command"),
    "subagent": ("subagent", "Subagent"),
    "other": ("other", "Other"),
}


def classify_tool(tool_name: str) -> tuple[str, str]:
    """Classify a tool name into a standard category key and readable label."""
    n = str(tool_name or "").lower().replace("-", "_").strip()
    if not n or n in ("unknown", "tool"):
        return _TOOL_CATEGORIES["other"]

    # Web & network
    if any(k in n for k in ("web", "url", "browser", "scrape", "fetch", "http", "curl")):
        return _TOOL_CATEGORIES["web"]

    # Search & pattern matching
    if any(k in n for k in ("grep", "glob", "find", "search", "locate")) or n in ("rg", "ripgrep"):
        return _TOOL_CATEGORIES["search"]

    # File edit & modification
    if any(k in n for k in ("edit", "write", "patch", "replace", "create_file")):
        return _TOOL_CATEGORIES["file_edit"]

    # File read & inspection
    if any(k in n for k in ("read", "view", "cat", "notebook", "open_file", "show_file")):
        return _TOOL_CATEGORIES["file_read"]

    # Shell & command execution
    if (
        n in ("bash", "sh", "zsh", "cmd", "terminal", "powershell", "shell")
        or any(k in n for k in ("shell", "bash", "exec", "command", "terminal", "powershell", "run_command"))
    ):
        return _TOOL_CATEGORIES["shell"]

    # Subagents & multi-agent delegation
    if any(k in n for k in ("subagent", "spawn", "manage_task", "send_message")) or n in ("agent", "task"):
        return _TOOL_CATEGORIES["subagent"]

    return _TOOL_CATEGORIES["other"]


def _format_type_suggestion(cat_key: str, tool_desc: str, pct: float, chars: int, calls: int) -> str:
    """Generate actionable, type-specific optimization suggestions."""
    if cat_key == "shell":
        return (
            f"Shell/command output ({tool_desc}: {pct}% of tool output, {chars:,} chars): "
            "filter stdout with head/tail/grep, silence verbose flags (e.g. --quiet, -q), "
            "or redirect bulky build/test logs to a file."
        )
    elif cat_key == "file_read":
        return (
            f"File read output ({tool_desc}: {pct}% of tool output, {chars:,} chars): "
            "use line-range / windowed reads (StartLine/EndLine, offset/limit) "
            "or symbol outlines instead of loading full files."
        )
    elif cat_key == "search":
        return (
            f"Search/grep output ({tool_desc}: {pct}% of tool output, {chars:,} chars): "
            "narrow search paths, add file extension filters (e.g. Includes), "
            "or refine regex patterns to avoid dumping large match sets."
        )
    elif cat_key == "web":
        return (
            f"Web/browser output ({tool_desc}: {pct}% of tool output, {chars:,} chars): "
            "extract distilled markdown text or query-focused snippets "
            "rather than ingesting full web pages or raw DOM trees."
        )
    elif cat_key == "file_edit":
        return (
            f"File edit output ({tool_desc}: {pct}% of tool output, {chars:,} chars): "
            "prefer targeted diff/patch replacements over full-file overwrites "
            "to minimize tool result payload size."
        )
    elif cat_key == "subagent":
        return (
            f"Subagent output ({tool_desc}: {pct}% of tool output, {chars:,} chars): "
            "prompt subagents to return concise structured findings "
            "rather than echoing full task transcripts."
        )
    else:
        return (
            f"Tool output from '{tool_desc}' ({pct}% of tool output, {chars:,} chars across {calls} calls): "
            "review verbosity or truncate output for this tool."
        )


def analyze(stats: SessionStats) -> dict:
    """Derive actionable signals from session statistics."""
    signals: dict = {
        "recommendations": [],
        "context_growth": None,
        "largest_sources": [],
        "tool_breakdown": [],
        "tool_categories": {},
    }

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

    # 1. Source breakdown
    total_chars = sum(stats.source_chars.values())
    if total_chars:
        ranked = sorted(stats.source_chars.items(), key=lambda kv: kv[1], reverse=True)[:4]
        signals["largest_sources"] = [
            {"source": k, "percent": round(v * 100 / total_chars, 1)} for k, v in ranked
        ]

    # 2. Tool output breakdown by tool and call type / category
    total_tool_output = sum(info.get("output_chars", 0) for info in stats.tool_stats.values())
    if total_tool_output == 0 and stats.source_chars.get("tool_output", 0) > 0:
        total_tool_output = stats.source_chars["tool_output"]

    tool_breakdown = []
    category_stats: dict[str, dict] = {}

    if stats.tool_stats:
        for tool_name, info in sorted(
            stats.tool_stats.items(), key=lambda kv: kv[1].get("output_chars", 0), reverse=True
        ):
            out_chars = info.get("output_chars", 0)
            calls = info.get("calls", 0)
            pct = round(out_chars * 100 / total_tool_output, 1) if total_tool_output else 0.0
            avg_chars = round(out_chars / calls) if calls else 0
            cat_key, cat_label = classify_tool(tool_name)

            tool_breakdown.append({
                "tool": tool_name,
                "category": cat_key,
                "category_label": cat_label,
                "calls": calls,
                "output_chars": out_chars,
                "percent": pct,
                "avg_chars_per_call": avg_chars,
            })

            cat = category_stats.setdefault(
                cat_key, {"label": cat_label, "output_chars": 0, "calls": 0, "tools": []}
            )
            cat["output_chars"] += out_chars
            cat["calls"] += calls
            if tool_name not in cat["tools"]:
                cat["tools"].append(tool_name)

        for c in category_stats.values():
            c["percent"] = round(c["output_chars"] * 100 / total_tool_output, 1) if total_tool_output else 0.0

        signals["tool_breakdown"] = tool_breakdown
        signals["tool_categories"] = category_stats

    # 3. Tool-specific and type-specific optimization suggestions
    tool_output_dominates = bool(
        total_chars
        and any(k == "tool_output" for k, _ in ranked[:2])
    )

    if tool_output_dominates:
        if not category_stats:
            signals["recommendations"].append(
                "Tool output dominates context; consider truncating or filtering large command output."
            )
        else:
            signals["recommendations"].append(
                "Tool output dominates context; optimize high-output tool invocations to keep prompt growth under control."
            )
            # Rank categories by output chars
            sorted_cats = sorted(
                category_stats.items(), key=lambda kv: kv[1]["output_chars"], reverse=True
            )
            for cat_key, cat_info in sorted_cats:
                # Suggest when category produces notable output (>=10% of tool output or >0 chars)
                if cat_info["output_chars"] > 0 and (cat_info["percent"] >= 10.0 or len(sorted_cats) == 1):
                    tools_str = ", ".join(cat_info["tools"][:3])
                    sug = _format_type_suggestion(
                        cat_key,
                        tools_str,
                        cat_info["percent"],
                        cat_info["output_chars"],
                        cat_info["calls"],
                    )
                    signals["recommendations"].append(sug)

    # 4. Check for high call frequency with small/repetitive calls
    for item in tool_breakdown:
        if item["calls"] >= 12 and item["avg_chars_per_call"] < 500:
            signals["recommendations"].append(
                f"High call frequency for '{item['tool']}' ({item['calls']} calls, ~{item['avg_chars_per_call']:,} chars/call); "
                "consider batching operations into fewer calls."
            )

    return signals
