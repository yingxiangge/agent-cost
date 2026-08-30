from __future__ import annotations

import json
from pathlib import Path

from agent_cost.models import SessionStats

_TOOL_TYPES = {"function_call", "tool_call", "local_shell_call", "shell_call", "apply_patch"}
_TOOL_OUTPUT_TYPES = {"function_call_output", "tool_result", "local_shell_call_output", "exec_output"}


def _chars(text: object) -> int:
    return len(str(text or ""))


def parse_codex_rollout(path: str | Path) -> SessionStats:
    """Parse a Codex rollout JSONL file into one SessionStats object.

    Rollout files usually do not carry token counters, so the parser derives a
    structural picture: turns, tool calls, compaction events and an estimated
    prompt-size curve from content lengths (approx. 4 chars per token).
    """
    stats = SessionStats(agent="codex", session_key="")
    base_chars = 0
    cumulative_chars = 0
    turn_idx = 0
    call_id_map: dict[str, str] = {}
    last_tool_name = "exec_command"

    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            payload = event.get("payload") or {}

            if etype == "session_meta":
                stats.session_key = payload.get("session_id") or payload.get("id") or ""
                stats.cli_version = payload.get("cli_version") or ""
                stats.cwd = payload.get("cwd") or ""
                provider = payload.get("model_provider") or ""
                model = payload.get("model") or ""
                stats.model = f"{provider}/{model}" if provider and model else (provider or model)
                stats.platform = payload.get("originator") or ""
                stats.created_at = payload.get("timestamp") or ""
                text = payload.get("base_instructions") or payload.get("instructions") or ""
                base_chars = _chars(text)
                stats.source_chars["base_instructions"] = base_chars
                cumulative_chars += base_chars

            elif etype == "turn_context":
                turn_idx += 1
                stats.turns = turn_idx
                stats.context_samples.append(
                    {"turn": turn_idx, "estimated_prompt_tokens": max(1, cumulative_chars // 4)}
                )

            elif etype == "compacted":
                stats.compaction_events += 1

            elif etype == "response_item":
                item_type = payload.get("type")
                if item_type in _TOOL_TYPES:
                    name = str(payload.get("name") or payload.get("tool") or item_type)
                    call_id = payload.get("id") or payload.get("call_id")
                    if call_id:
                        call_id_map[str(call_id)] = name
                    last_tool_name = name
                    stats.record_tool_call(name, _chars(name), payload.get("arguments") or payload.get("input"))
                elif item_type in _TOOL_OUTPUT_TYPES:
                    call_id = payload.get("id") or payload.get("call_id")
                    name = (
                        (call_id_map.get(str(call_id)) if call_id else None)
                        or payload.get("name")
                        or last_tool_name
                        or "exec_command"
                    )
                    text = payload.get("output") or payload.get("result") or payload.get("text") or ""
                    chars = _chars(text)
                    stats.record_tool_output(name, chars, content=text)
                    cumulative_chars += chars
                elif item_type == "message":
                    text = payload.get("text") or payload.get("content") or ""
                    role = payload.get("role") or "unknown"
                    stats.source_chars[role] = stats.source_chars.get(role, 0) + _chars(text)
                    cumulative_chars += _chars(text)

    stats.input_tokens = max(1, cumulative_chars // 4)
    stats.output_tokens = 0  # unknown for rollouts; message chars are counted above
    return stats
