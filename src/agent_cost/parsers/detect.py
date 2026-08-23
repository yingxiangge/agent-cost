from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_cost.models import SessionStats
from agent_cost.parsers.claude import parse_claude_session
from agent_cost.parsers.codex import parse_codex_rollout
from agent_cost.parsers.hermes import parse_hermes_sessions
from agent_cost.parsers.opencode import parse_opencode_session, parse_opencode_sqlite


def load_path(path: str | Path, warn: bool = True) -> list[SessionStats]:
    """Auto-detect parser and load session stats from a file or directory.

    Files that yield no usage at all are reported on stderr instead of quietly
    joining the totals as zeros: that is the signature of a misdetected format,
    and a silent zero is indistinguishable from a genuinely empty session.
    """
    p = Path(path)
    if not p.exists():
        return []

    results: list[SessionStats] = []
    empty: list[str] = []

    if p.is_dir():
        for file in sorted(p.rglob("*")):
            if file.is_file() and file.suffix in (".json", ".jsonl", ".db", ".sqlite", ".sqlite3"):
                try:
                    loaded = parse_file(file)
                except Exception as exc:  # noqa: BLE001 - one bad file must not abort a scan
                    if warn:
                        print(f"agent-cost: skipped {file.name}: {exc}", file=sys.stderr)
                    continue
                results.extend(loaded)
                empty.extend(file.name for s in loaded if _is_empty(s))
    else:
        results = parse_file(p)
        empty = [p.name for s in results if _is_empty(s)]

    if warn and empty:
        shown = ", ".join(empty[:3]) + (f" (+{len(empty) - 3} more)" if len(empty) > 3 else "")
        print(
            f"agent-cost: {len(empty)} file(s) parsed to zero usage and contribute "
            f"nothing to the totals: {shown}",
            file=sys.stderr,
        )
    return results


def _is_empty(stats: SessionStats) -> bool:
    return stats.total_tokens == 0 and stats.turns == 0 and stats.tool_calls == 0


def parse_file(path: str | Path) -> list[SessionStats]:
    """Detect the format of a file and parse it into a list of SessionStats."""
    p = Path(path)
    if not p.is_file():
        return []

    if p.name == "sessions.json":
        return parse_hermes_sessions(p)

    if p.suffix in (".db", ".sqlite", ".sqlite3"):
        return parse_opencode_sqlite(p)

    if p.suffix == ".json":
        return _parse_json_file(p)
    elif p.suffix == ".jsonl":
        return _parse_jsonl_file(p)

    # Unknown extension, try SQLite first if it's a binary DB, else json/jsonl
    try:
        res = parse_opencode_sqlite(p)
        if res:
            return res
    except Exception:
        pass

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


_CODEX_SIGNATURES = ("session_meta", "turn_context", "response_item")
_CLAUDE_SIGNATURES = ("cache_read_input_tokens", "tool_use", "sessionid", "claude")
_OPENCODE_SIGNATURES = ("opencode",)


def _sniff_jsonl(p: Path) -> str | None:
    """Stream the file looking for a format signature; stop at the first hit.

    Scanning only the head is what misclassifies sessions: a transcript whose
    opening lines are metadata and user text carries no signature until the
    first assistant reply, which can be well past any fixed cutoff. Streaming
    costs nothing on normal files (the signature usually appears within a few
    lines) and is bounded by the file itself.
    """
    with p.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            low = line.lower()
            if any(sig in low for sig in _CODEX_SIGNATURES):
                return "codex"
            if any(sig in low for sig in _CLAUDE_SIGNATURES):
                return "claude"
            if any(sig in low for sig in _OPENCODE_SIGNATURES):
                return "opencode"
    return None


def _parse_jsonl_file(p: Path) -> list[SessionStats]:
    kind = _sniff_jsonl(p)
    if kind == "codex":
        return [parse_codex_rollout(p)]
    if kind == "claude":
        return [parse_claude_session(p)]
    if kind == "opencode":
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
