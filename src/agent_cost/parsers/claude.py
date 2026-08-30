from __future__ import annotations

import json
from pathlib import Path

from agent_cost.media import estimate_image_tokens
from agent_cost.models import SessionStats


def _chars(text: object) -> int:
    return len(str(text or ""))


def _result_chars(result: object) -> tuple[int, int, int]:
    """Split a tool_result payload into (text chars, image count, image tokens).

    An image block carries its pixels as base64 under `source.data`. Stringifying
    that block would charge a screenshot hundreds of thousands of characters and
    bury every text tool underneath it, so images are counted separately and
    priced on their dimensions instead.
    """
    if not isinstance(result, list):
        return _chars(result), 0, 0

    chars = images = image_tokens = 0
    for block in result:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "image":
            source = block.get("source")
            data = source.get("data") if isinstance(source, dict) else ""
            images += 1
            image_tokens += estimate_image_tokens(str(data or ""))
            continue
        chars += _chars(block.get("text") or block.get("content") or block)
    return chars, images, image_tokens


def parse_claude_session(path: str | Path) -> SessionStats:
    """Parse a Claude Code session log (JSON or JSONL) into SessionStats.

    Claude Code logs interactions and Anthropic API usage objects:
    - input_tokens, output_tokens, cache_read_input_tokens, cache_creation_input_tokens
    - tool_use content blocks (Bash, FileEdit, GlobTool, etc.)
    """
    p = Path(path)
    stats = SessionStats(agent="claude-code", session_key=p.stem)

    if p.suffix == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _parse_claude_dict(data, stats)
            elif isinstance(data, list):
                return _parse_claude_records(data, stats)
        except json.JSONDecodeError:
            pass

    # Process JSONL format (standard Claude Code transcript)
    turns = 0
    cumulative_chars = 0
    tool_map: dict[str, str] = {}
    last_tool: list[str] = ["tool"]
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            _process_claude_event(event, stats, tool_map=tool_map, last_tool=last_tool)

    if stats.turns == 0 and turns > 0:
        stats.turns = turns
    return stats


def _process_claude_event(
    event: dict,
    stats: SessionStats,
    tool_map: dict[str, str] | None = None,
    last_tool: list[str] | None = None,
) -> None:
    # Session metadata if present
    if "session_id" in event or "sessionId" in event:
        stats.session_key = str(event.get("session_id") or event.get("sessionId") or stats.session_key)
    if "cwd" in event:
        stats.cwd = str(event.get("cwd") or stats.cwd)
    if "platform" in event or "origin" in event:
        stats.platform = str(event.get("platform") or event.get("origin") or stats.platform)
    if "created_at" in event or "timestamp" in event:
        ts = str(event.get("created_at") or event.get("timestamp") or "")
        if not stats.created_at:
            stats.created_at = ts
        stats.updated_at = ts

    # Check for model
    model = event.get("model") or (event.get("message", {}) if isinstance(event.get("message"), dict) else {}).get("model")
    if model and not stats.model:
        stats.model = str(model)

    # Check for compaction or context prune events
    etype = event.get("type") or ""
    if etype in ("compacted", "context_pruned", "summary"):
        stats.compaction_events += 1

    # Extract usage
    usage = event.get("usage")
    if not usage and isinstance(event.get("message"), dict):
        usage = event.get("message", {}).get("usage")

    if isinstance(usage, dict):
        inp = int(usage.get("input_tokens") or 0)
        out = int(usage.get("output_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or usage.get("cache_read_tokens") or 0)
        cache_write = int(usage.get("cache_creation_input_tokens") or usage.get("cache_write_tokens") or 0)

        # `speed` and `inference_geo` decide which rate card this turn is billed
        # on, and both can change between turns, so they are recorded per turn.
        stats.add_usage(
            inp,
            out,
            cache_read,
            cache_write,
            speed=str(usage.get("speed") or "standard"),
            inference_geo=str(usage.get("inference_geo") or ""),
        )

        stats.turns += 1
        prompt_tokens_this_turn = inp + cache_read + cache_write
        stats.context_samples.append({
            "turn": stats.turns,
            "estimated_prompt_tokens": prompt_tokens_this_turn,
        })

    # Count tool uses & source chars
    content = event.get("content")
    if not content and isinstance(event.get("message"), dict):
        content = event.get("message", {}).get("content")

    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                btype = block.get("type")
                if btype == "tool_use":
                    tool_name = str(block.get("name") or "tool")
                    tool_id = block.get("id")
                    if tool_id and tool_map is not None:
                        tool_map[str(tool_id)] = tool_name
                    if last_tool is not None:
                        last_tool[0] = tool_name
                    stats.record_tool_call(tool_name, _chars(tool_name), block.get("input"))
                elif btype == "tool_result":
                    tool_use_id = block.get("tool_use_id")
                    tool_name = (
                        (tool_map.get(str(tool_use_id)) if tool_map and tool_use_id else None)
                        or block.get("name")
                        or (last_tool[0] if last_tool else "tool")
                    )
                    res_text = block.get("content") or block.get("text") or ""
                    chars, images, image_tokens = _result_chars(res_text)
                    stats.record_tool_output(tool_name, chars, images, image_tokens, res_text)
                elif btype == "text":
                    text = block.get("text") or ""
                    stats.source_chars["assistant"] = stats.source_chars.get("assistant", 0) + _chars(text)
    if etype == "tool_result" and not isinstance(content, list):
        tool_use_id = event.get("tool_use_id")
        tool_name = (
            (tool_map.get(str(tool_use_id)) if tool_map and tool_use_id else None)
            or event.get("name")
            or (last_tool[0] if last_tool else "tool")
        )
        res_text = event.get("content") or event.get("text") or ""
        chars, images, image_tokens = _result_chars(res_text)
        stats.record_tool_output(tool_name, chars, images, image_tokens, res_text)
    elif isinstance(content, str):
        role = event.get("role") or event.get("type") or "user"
        stats.source_chars[role] = stats.source_chars.get(role, 0) + _chars(content)


def _parse_claude_dict(data: dict, stats: SessionStats) -> SessionStats:
    stats.session_key = str(data.get("session_id") or data.get("id") or stats.session_key)
    stats.model = str(data.get("model") or stats.model)
    stats.created_at = str(data.get("created_at") or "")
    stats.updated_at = str(data.get("updated_at") or "")

    tool_map: dict[str, str] = {}
    last_tool: list[str] = ["tool"]
    messages = data.get("messages") or data.get("transcript") or []
    if isinstance(messages, list):
        for item in messages:
            if isinstance(item, dict):
                _process_claude_event(item, stats, tool_map=tool_map, last_tool=last_tool)
    return stats


def _parse_claude_records(records: list[dict], stats: SessionStats) -> SessionStats:
    tool_map: dict[str, str] = {}
    last_tool: list[str] = ["tool"]
    for rec in records:
        if isinstance(rec, dict):
            _process_claude_event(rec, stats, tool_map=tool_map, last_tool=last_tool)
    return stats
