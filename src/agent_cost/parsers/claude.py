from __future__ import annotations

import json
from pathlib import Path

from agent_cost.models import SessionStats


def _chars(text: object) -> int:
    return len(str(text or ""))


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
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            _process_claude_event(event, stats)

    if stats.turns == 0 and turns > 0:
        stats.turns = turns
    return stats


def _process_claude_event(event: dict, stats: SessionStats) -> None:
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
                    stats.tool_calls += 1
                    tool_name = block.get("name") or "tool"
                    stats.source_chars["tool_calls"] = stats.source_chars.get("tool_calls", 0) + _chars(tool_name)
                elif btype == "tool_result":
                    res_text = block.get("content") or block.get("text") or ""
                    stats.source_chars["tool_output"] = stats.source_chars.get("tool_output", 0) + _chars(res_text)
                elif btype == "text":
                    text = block.get("text") or ""
                    stats.source_chars["assistant"] = stats.source_chars.get("assistant", 0) + _chars(text)
    elif isinstance(content, str):
        role = event.get("role") or event.get("type") or "user"
        stats.source_chars[role] = stats.source_chars.get(role, 0) + _chars(content)


def _parse_claude_dict(data: dict, stats: SessionStats) -> SessionStats:
    stats.session_key = str(data.get("session_id") or data.get("id") or stats.session_key)
    stats.model = str(data.get("model") or stats.model)
    stats.created_at = str(data.get("created_at") or "")
    stats.updated_at = str(data.get("updated_at") or "")

    messages = data.get("messages") or data.get("transcript") or []
    if isinstance(messages, list):
        for item in messages:
            if isinstance(item, dict):
                _process_claude_event(item, stats)
    return stats


def _parse_claude_records(records: list[dict], stats: SessionStats) -> SessionStats:
    for rec in records:
        if isinstance(rec, dict):
            _process_claude_event(rec, stats)
    return stats
