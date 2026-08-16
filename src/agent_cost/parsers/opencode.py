from __future__ import annotations

import json
from pathlib import Path

from agent_cost.models import SessionStats


def _chars(text: object) -> int:
    return len(str(text or ""))


def _read_usage(usage: dict) -> tuple[int, int, int, int]:
    """Normalise a usage dict to (uncached_input, output, cache_read, cache_write).

    Field names carry different semantics and must not be mixed:

    - OpenAI style: `prompt_tokens` ALREADY INCLUDES `cached_tokens`, so the
      uncached input is `prompt_tokens - cached_tokens`. Adding both would
      double-count the cached prefix and understate the cache hit rate.
    - Anthropic style: `input_tokens` EXCLUDES `cache_read_tokens`, so it is
      used as-is.
    """
    cached = int(usage.get("cached_tokens") or usage.get("cache_read_tokens") or 0)
    cache_write = int(usage.get("cache_write_tokens") or 0)
    out = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)

    if "prompt_tokens" in usage:
        # OpenAI semantics: subtract the cached prefix out of the prompt total.
        inp = max(0, int(usage.get("prompt_tokens") or 0) - cached)
    else:
        # Anthropic semantics: input is already the uncached remainder.
        inp = int(usage.get("input_tokens") or 0)

    return inp, out, cached, cache_write


def parse_opencode_session(path: str | Path) -> SessionStats:
    """Parse an OpenCode session log (JSON or JSONL) into SessionStats.

    OpenCode logs session steps, tool executions, and turn token counts.
    """
    p = Path(path)
    stats = SessionStats(agent="opencode", session_key=p.stem)

    if p.suffix == ".json":
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return _parse_opencode_dict(data, stats)
            elif isinstance(data, list):
                return _parse_opencode_records(data, stats)
        except json.JSONDecodeError:
            pass

    # JSONL format
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            _process_opencode_event(event, stats)

    return stats


def _process_opencode_event(event: dict, stats: SessionStats) -> None:
    if "session_id" in event or "sessionId" in event:
        stats.session_key = str(event.get("session_id") or event.get("sessionId") or stats.session_key)
    if "model" in event and not stats.model:
        stats.model = str(event.get("model") or "")
    if "created_at" in event or "timestamp" in event:
        ts = str(event.get("created_at") or event.get("timestamp") or "")
        if not stats.created_at:
            stats.created_at = ts
        stats.updated_at = ts

    # Step or turn level parsing
    if event.get("type") in ("tool_call", "action") or "tool" in event:
        stats.tool_calls += 1
        tool = event.get("tool") or event.get("action") or ""
        stats.source_chars["tool_calls"] = stats.source_chars.get("tool_calls", 0) + _chars(tool)

    if event.get("type") == "compaction":
        stats.compaction_events += 1

    usage = event.get("usage")
    if isinstance(usage, dict):
        inp, out, cached, cache_write = _read_usage(usage)

        stats.input_tokens += inp
        stats.output_tokens += out
        stats.cache_read_tokens += cached
        stats.cache_write_tokens += cache_write
        stats.turns += 1

        stats.context_samples.append({
            "turn": stats.turns,
            "estimated_prompt_tokens": inp + cached + cache_write,
        })


def _parse_opencode_dict(data: dict, stats: SessionStats) -> SessionStats:
    stats.session_key = str(data.get("session_id") or data.get("id") or stats.session_key)
    stats.model = str(data.get("model") or stats.model)
    stats.created_at = str(data.get("created_at") or "")
    stats.updated_at = str(data.get("updated_at") or "")

    steps = data.get("steps") or data.get("history") or data.get("messages") or []
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                _process_opencode_event(step, stats)

    # Top-level aggregate usage fallback if steps didn't have per-turn usage
    if stats.input_tokens == 0 and "usage" in data and isinstance(data["usage"], dict):
        inp, out, cached, cache_write = _read_usage(data["usage"])
        stats.input_tokens = inp
        stats.output_tokens = out
        stats.cache_read_tokens = cached
        stats.cache_write_tokens = cache_write
        if stats.turns == 0:
            stats.turns = len(steps) if steps else 1
    return stats


def _parse_opencode_records(records: list[dict], stats: SessionStats) -> SessionStats:
    for rec in records:
        if isinstance(rec, dict):
            _process_opencode_event(rec, stats)
    return stats
