from __future__ import annotations

import json

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


# Defaults chosen to fire before the prompt curve is unrecoverable, not at the
# model's context limit: by the time a session is at its ceiling, the expensive
# turns have already been paid for.
DEFAULT_BUDGET = {"warning": 100_000, "critical": 150_000}


def parse_budget(raw: str) -> dict:
    """Parse a `warning:100k,critical:150k` budget spec into token counts.

    Either key may be omitted and keeps its default. Raises ValueError with a
    usable message rather than falling back to defaults silently -- a budget
    the user thought they set but did not is worse than no budget.
    """
    budget = dict(DEFAULT_BUDGET)
    for part in str(raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        key, _, value = part.partition(":")
        key = key.strip().lower()
        if key not in budget:
            raise ValueError(
                f"unknown budget key {key!r}; expected 'warning' or 'critical'"
            )
        text = value.strip().lower().replace("_", "")
        multiplier = 1
        if text.endswith("k"):
            multiplier, text = 1_000, text[:-1]
        elif text.endswith("m"):
            multiplier, text = 1_000_000, text[:-1]
        try:
            amount = float(text)
        except ValueError:
            raise ValueError(f"budget {key!r} is not a number: {value.strip()!r}") from None
        if amount <= 0:
            raise ValueError(f"budget {key!r} must be positive")
        budget[key] = int(amount * multiplier)
    if budget["warning"] >= budget["critical"]:
        raise ValueError(
            f"warning ({budget['warning']:,}) must be below critical ({budget['critical']:,})"
        )
    return budget


# Said when a jump has no tool output behind it: the prompt still grew, so the
# turn needs an explanation, and "we could not attribute this" is one. On this
# codebase's own transcripts these turns are per-turn injected context and long
# user messages -- real growth that naming no culprit would hide.
NO_TOOL_CULPRIT = "no tool output this turn"


def _describe_culprit(tools: list[dict]) -> str:
    """Name the tool call that carried the most output into a turn."""
    if not tools:
        return NO_TOOL_CULPRIT
    top = tools[0]
    name = top.get("tool") or "tool"
    detail = top.get("detail") or ""
    return f"{name} `{detail}`" if detail else str(name)


def context_budget(stats: SessionStats, budget: dict | None = None) -> dict | None:
    """Track the prompt curve against warning / critical budgets.

    Returns None when there is no curve to track. The first sample is excluded
    from the jump search: its delta is the whole session preamble, which no
    tool call caused and no user action can shrink.
    """
    samples = stats.context_samples
    if not samples:
        return None

    limits = dict(DEFAULT_BUDGET) if budget is None else dict(budget)
    warning, critical = limits["warning"], limits["critical"]

    curve = []
    warning_turn = critical_turn = None
    for sample in samples:
        tokens = int(sample.get("estimated_prompt_tokens") or 0)
        level = "ok"
        if tokens >= critical:
            level = "critical"
            if critical_turn is None:
                critical_turn = sample.get("turn")
        elif tokens >= warning:
            level = "warning"
            if warning_turn is None:
                warning_turn = sample.get("turn")
        curve.append({
            "turn": sample.get("turn"),
            "estimated_prompt_tokens": tokens,
            # Samples written before this field existed carry no delta; treat
            # them as unattributed rather than inventing a jump of zero.
            "delta": sample.get("delta"),
            "level": level,
            "tools": sample.get("tools") or [],
        })

    biggest_jump = None
    for entry in curve[1:]:
        delta = entry["delta"]
        if delta is None or delta <= 0:
            continue
        if biggest_jump is None or delta > biggest_jump["delta"]:
            biggest_jump = {
                "turn": entry["turn"],
                "delta": delta,
                "tools": entry["tools"],
                "culprit": _describe_culprit(entry["tools"]),
            }

    return {
        "warning": warning,
        "critical": critical,
        "warning_turn": warning_turn,
        "critical_turn": critical_turn,
        "peak_prompt_tokens": max((e["estimated_prompt_tokens"] for e in curve), default=0),
        "final_prompt_tokens": curve[-1]["estimated_prompt_tokens"],
        "biggest_jump": biggest_jump,
        "curve": curve,
    }


def analyze(stats: SessionStats, budget: dict | None = None) -> dict:
    """Derive actionable signals from session statistics."""
    signals: dict = {
        "recommendations": [],
        "context_growth": None,
        "context_budget": None,
        "largest_sources": [],
        "tool_breakdown": [],
        "tool_categories": {},
        "image_summary": None,
        "repeated_tool_output": [],
        "repeated_file_reads": [],
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

    tracked = context_budget(stats, budget)
    signals["context_budget"] = tracked
    if tracked:
        jump = tracked["biggest_jump"]
        culprit = ""
        if jump and jump["culprit"]:
            joiner = "," if jump["culprit"] == NO_TOOL_CULPRIT else " by"
            culprit = f"{joiner} {jump['culprit']}"
        jump_note = (
            f" The biggest single-turn jump was +{jump['delta']:,} tokens at turn {jump['turn']}{culprit}."
            if jump
            else ""
        )
        if tracked["critical_turn"] is not None:
            signals["recommendations"].append(
                f"Context crossed the critical budget ({tracked['critical']:,} tokens) at turn "
                f"{tracked['critical_turn']}, peaking at {tracked['peak_prompt_tokens']:,}."
                f"{jump_note} Compact the session or start a fresh one."
            )
        elif tracked["warning_turn"] is not None:
            signals["recommendations"].append(
                f"Context crossed the warning budget ({tracked['warning']:,} tokens) at turn "
                f"{tracked['warning_turn']}.{jump_note}"
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
    source_total_chars = sum(stats.source_chars.values())
    # Defined unconditionally: step 3 reads it, and a session can carry tool
    # fingerprints while `source_chars` is still empty.
    ranked: list[tuple[str, int]] = []
    if source_total_chars:
        ranked = sorted(stats.source_chars.items(), key=lambda kv: kv[1], reverse=True)[:4]
        signals["largest_sources"] = [
            {"source": k, "percent": round(v * 100 / source_total_chars, 1)} for k, v in ranked
        ]

    # 2. Tool output breakdown by tool and call type / category
    total_tool_output = sum(info.get("output_chars", 0) for info in stats.tool_stats.values())
    if total_tool_output == 0 and stats.source_chars.get("tool_output", 0) > 0:
        total_tool_output = stats.source_chars["tool_output"]

    tool_breakdown = []
    category_stats: dict[str, dict] = {}

    if stats.tool_stats:
        for tool_name, info in sorted(
            stats.tool_stats.items(),
            key=lambda kv: (kv[1].get("output_chars", 0), kv[1].get("image_tokens", 0)),
            reverse=True,
        ):
            out_chars = info.get("output_chars", 0)
            calls = info.get("calls", 0)
            images = info.get("images", 0)
            image_tokens = info.get("image_tokens", 0)
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
                "images": images,
                "image_tokens": image_tokens,
            })

            cat = category_stats.setdefault(
                cat_key,
                {"label": cat_label, "output_chars": 0, "calls": 0, "tools": [],
                 "images": 0, "image_tokens": 0},
            )
            cat["output_chars"] += out_chars
            cat["calls"] += calls
            cat["images"] += images
            cat["image_tokens"] += image_tokens
            if tool_name not in cat["tools"]:
                cat["tools"].append(tool_name)

        for c in category_stats.values():
            c["percent"] = round(c["output_chars"] * 100 / total_tool_output, 1) if total_tool_output else 0.0

        signals["tool_breakdown"] = tool_breakdown
        signals["tool_categories"] = category_stats

    repeated_outputs = []
    for tool_name, fingerprints in stats.tool_output_fingerprints.items():
        calls = sum(item["calls"] for item in fingerprints.values())
        fingerprint_chars = sum(item["output_chars"] for item in fingerprints.values())
        duplicate_chars = sum(
            item["output_chars"] - (item["output_chars"] // item["calls"])
            for item in fingerprints.values()
            if item["calls"] > 1
        )
        duplicate_calls = sum(
            item["calls"] - 1 for item in fingerprints.values() if item["calls"] > 1
        )
        if duplicate_calls:
            repeated_outputs.append({
                "tool": tool_name,
                "calls": calls,
                "total_chars": fingerprint_chars,
                "unique_chars": fingerprint_chars - duplicate_chars,
                "repeated_chars": duplicate_chars,
                "duplicate_calls": duplicate_calls,
            })
    signals["repeated_tool_output"] = sorted(
        repeated_outputs, key=lambda item: item["repeated_chars"], reverse=True
    )

    file_read_tools = {
        "read",
        "cat",
        "view_file",
        "read_file",
        "fileread",
        "readfile",
        "open_file",
    }
    repeated_files = {}
    for tool_name, inputs in stats.tool_call_inputs.items():
        if tool_name.lower().replace("-", "_") not in file_read_tools:
            continue
        for raw in inputs:
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                parsed = raw
            if isinstance(parsed, dict):
                path = parsed.get("path") or parsed.get("file") or parsed.get("file_path")
            else:
                path = parsed
            if path:
                key = str(path)
                repeated_files[key] = repeated_files.get(key, 0) + 1
    signals["repeated_file_reads"] = [
        {"path": path, "reads": reads}
        for path, reads in sorted(repeated_files.items(), key=lambda item: item[1], reverse=True)
        if reads > 1
    ]

    # 3. Tool-specific and type-specific optimization suggestions
    tool_output_dominates = bool(
        source_total_chars
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

    if signals["repeated_tool_output"]:
        top = signals["repeated_tool_output"][0]
        signals["recommendations"].append(
            f"Repeated output from '{top['tool']}' accounts for {top['repeated_chars']:,} repeated characters; "
            "filter or narrow the command output before sending it again."
        )
    if signals["repeated_file_reads"]:
        top = signals["repeated_file_reads"][0]
        signals["recommendations"].append(
            f"'{top['path']}' was read {top['reads']} times; prefer targeted line ranges after the first read."
        )

    # 4. Images ride on pixel dimensions, not character counts, so they are
    #    surfaced on their own rather than mixed into the tool output ranking.
    if stats.image_count:
        image_sources = [i for i in tool_breakdown if i["images"]]
        signals["image_summary"] = {
            "images": stats.image_count,
            "image_tokens": stats.image_tokens,
            "tools": [
                {"tool": i["tool"], "images": i["images"], "image_tokens": i["image_tokens"]}
                for i in sorted(image_sources, key=lambda i: i["image_tokens"], reverse=True)
            ],
        }
        if stats.image_tokens >= 10_000:
            via = ", ".join(i["tool"] for i in image_sources[:3]) or "tools"
            signals["recommendations"].append(
                f"Images are a major context source ({stats.image_count} images via {via}, "
                f"~{stats.image_tokens:,} tokens): they are billed on pixel dimensions, so crop or "
                "downscale before attaching, and avoid carrying old screenshots across turns."
            )

    # 5. Check for high call frequency with small/repetitive calls
    for item in tool_breakdown:
        if item["calls"] >= 12 and item["avg_chars_per_call"] < 500:
            signals["recommendations"].append(
                f"High call frequency for '{item['tool']}' ({item['calls']} calls, ~{item['avg_chars_per_call']:,} chars/call); "
                "consider batching operations into fewer calls."
            )

    return signals
