from __future__ import annotations

import json
from pathlib import Path

from agent_cost.models import SessionStats
from agent_cost.parsers.claude import parse_claude_session
from agent_cost.parsers.codex import parse_codex_rollout
from agent_cost.parsers.hermes import parse_hermes_sessions
from agent_cost.parsers.opencode import parse_opencode_session


def load_path(path: str | Path) -> list[SessionStats]:
    """Auto-detect parser and load session stats from a file or directory."""
    p = Path(path)
    if not p.exists():
        return []

    if p.is_dir():
        results: list[SessionStats] = []
        for file in sorted(p.rglob("*")):
            if file.is_file() and file.suffix in (".json", ".jsonl"):
                try:
                    results.extend(parse_file(file))
                except Exception:
                    continue
        return results

    return parse_file(p)


def parse_file(path: str | Path) -> list[SessionStats]:
    """Detect the format of a file and parse it into a list of SessionStats."""
    p = Path(path)
    if not p.is_file():
        return []

    if p.name == "sessions.json":
        return parse_hermes_sessions(p)

    if p.suffix == ".json":
        return _parse_json_file(p)
    elif p.suffix == ".jsonl":
        return _parse_jsonl_file(p)

    # Unknown extension, try both
    try:
        return _parse_json_file(p)
    except Exception:
        try:
            return _parse_jsonl_file(p)
        except Exception:
            return []


def _parse_json_file(p: Path) -> list[SessionStats]:
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return _parse_jsonl_file(p)

    # Check for Hermes sessions structure
    if isinstance(data, dict):
        # Hermes sessions format or single hermes session
        if any("session_key" in str(v) for v in (data.values() if isinstance(data, dict) else [])):
            return parse_hermes_sessions(p)
        if "last_prompt_tokens" in data or "cache_hit_rate" in data:
            return parse_hermes_sessions(p)

        # Claude session format
        if "messages" in data or "transcript" in data:
            return [parse_claude_session(p)]

        # OpenCode session format
        if "steps" in data or "history" in data or data.get("agent") == "opencode":
            return [parse_opencode_session(p)]

    elif isinstance(data, list):
        if data and isinstance(data[0], dict):
            first = data[0]
            if "session_key" in first or "last_prompt_tokens" in first:
                return parse_hermes_sessions(p)
            if "messages" in first or "role" in first:
                return [parse_claude_session(p)]
            if "steps" in first or first.get("agent") == "opencode":
                return [parse_opencode_session(p)]

    # Default fallback attempts
    try:
        res = parse_hermes_sessions(p)
        if res:
            return res
    except Exception:
        pass

    try:
        return [parse_claude_session(p)]
    except Exception:
        return [parse_opencode_session(p)]


def _parse_jsonl_file(p: Path) -> list[SessionStats]:
    with p.open(encoding="utf-8") as fh:
        first_lines = []
        for _ in range(15):
            line = fh.readline()
            if not line:
                break
            line = line.strip()
            if line:
                first_lines.append(line)

    combined = "\n".join(first_lines)

    # Codex signatures
    if "session_meta" in combined or "turn_context" in combined or "response_item" in combined:
        return [parse_codex_rollout(p)]

    # Claude signatures
    if "cache_read_input_tokens" in combined or "tool_use" in combined or "claude" in combined.lower():
        return [parse_claude_session(p)]

    # OpenCode signatures
    if "opencode" in combined.lower() or "action" in combined:
        return [parse_opencode_session(p)]

    # Default: try codex -> claude -> opencode
    try:
        s = parse_codex_rollout(p)
        if s.turns > 0 or s.tool_calls > 0 or s.input_tokens > 1:
            return [s]
    except Exception:
        pass

    try:
        s = parse_claude_session(p)
        if s.turns > 0 or s.total_tokens > 0:
            return [s]
    except Exception:
        pass

    return [parse_opencode_session(p)]
