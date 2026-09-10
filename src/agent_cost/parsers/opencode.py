from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone
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
            _process_opencode_event(event, stats, tool_map=tool_map, last_tool=last_tool)

    return stats


def _epoch_ms_to_iso(value: object) -> str:
    """Render an epoch-millisecond timestamp as UTC ISO 8601.

    OpenCode stores times as integer milliseconds. Everything downstream
    compares timestamps as ISO strings, so convert at the parser boundary
    instead of teaching every consumer a second time format.
    """
    try:
        ms = int(value)
    except (TypeError, ValueError):
        return ""
    if ms <= 0:
        return ""
    return (
        datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def _session_time(row, cols: set, iso_col: str, epoch_col: str) -> str:
    """Read a session timestamp under either schema OpenCode has used.

    JSON exports carry `created_at` / `updated_at`; the SQLite schema uses
    `time_created` / `time_updated` in epoch milliseconds. Reading only the
    first left every database-backed session without a timestamp.
    """
    if iso_col in cols and row[iso_col]:
        return str(row[iso_col])
    if epoch_col in cols and row[epoch_col]:
        return _epoch_ms_to_iso(row[epoch_col])
    return ""


def parse_opencode_sqlite(path: str | Path, warn: bool = True) -> list[SessionStats]:
    """Parse an OpenCode SQLite database (``~/.local/share/opencode/opencode.db``).

    The database belongs to a possibly running agent, so it is opened through a
    read-only URI: this tool must never write to it, nor trigger WAL recovery.
    There is deliberately no read-write fallback -- failing to read is a result
    we can report, corrupting someone's session store is not.

    A row we cannot decode is counted and reported on stderr, never swallowed:
    a partially parsed database looks exactly like a cheap session, and an
    under-reported cost is worse than a loud failure.
    """
    p = Path(path)
    if not p.is_file():
        return []

    try:
        conn = sqlite3.connect(f"file:{p.resolve()}?mode=ro", uri=True)
    except sqlite3.Error:
        return []
    conn.row_factory = sqlite3.Row

    sessions: dict[str, SessionStats] = {}
    session_tool_maps: dict[str, dict[str, str]] = {}
    session_last_tools: dict[str, list[str]] = {}
    skipped = 0
    saw_usage = False

    try:
        cur = conn.cursor()
        try:
            tables = {row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        except sqlite3.DatabaseError:
            # Not a SQLite database at all: a negative format probe, not an error.
            return []

        # 1. Session metadata, when the schema exposes it.
        if "session" in tables or "sessions" in tables:
            tbl = "session" if "session" in tables else "sessions"
            cols = {col[1] for col in cur.execute(f"PRAGMA table_info({tbl})")}
            id_col = "id" if "id" in cols else "session_id" if "session_id" in cols else None
            if id_col:
                for row in cur.execute(f"SELECT * FROM {tbl}"):
                    s_id = str(row[id_col])
                    st = SessionStats(agent="opencode", session_key=s_id)
                    st.created_at = _session_time(row, cols, "created_at", "time_created")
                    st.updated_at = _session_time(row, cols, "updated_at", "time_updated")
                    for model_col in ("modelID", "model_id", "model"):
                        if model_col in cols and row[model_col]:
                            st.model = str(row[model_col])
                            break
                    sessions[s_id] = st

        # 2. Per-message usage.
        if "message" in tables or "messages" in tables:
            msg_tbl = "message" if "message" in tables else "messages"
            msg_cols = {col[1] for col in cur.execute(f"PRAGMA table_info({msg_tbl})")}
            s_fk = "session_id" if "session_id" in msg_cols else "sessionId" if "sessionId" in msg_cols else None
            data_col = next((c for c in ("data", "payload", "message") if c in msg_cols), None)

            if s_fk and data_col:
                for row in cur.execute(f"SELECT {s_fk}, {data_col} FROM {msg_tbl} ORDER BY rowid ASC"):
                    raw_data = row[data_col]
                    if not raw_data:
                        continue
                    try:
                        msg_obj = _decode_message(raw_data)
                    except (ValueError, TypeError, UnicodeDecodeError):
                        skipped += 1
                        continue
                    if msg_obj is None:
                        continue

                    s_id = str(row[s_fk] or "default")
                    st = sessions.get(s_id)
                    if st is None:
                        st = SessionStats(agent="opencode", session_key=s_id)
                        sessions[s_id] = st
                    t_map = session_tool_maps.setdefault(s_id, {})
                    l_tool = session_last_tools.setdefault(s_id, ["tool"])
                    if isinstance(msg_obj.get("tokens"), dict) or isinstance(msg_obj.get("usage"), dict):
                        saw_usage = True
                    try:
                        _process_opencode_event(msg_obj, st, tool_map=t_map, last_tool=l_tool)
                    except (ValueError, TypeError, AttributeError):
                        # One malformed counter must not truncate the scan: the
                        # rows after it carry usage we would otherwise lose.
                        skipped += 1
    finally:
        conn.close()

    if not saw_usage:
        # `session` and `message` are generic table names. Without a single
        # usage payload this is some other tool's database that happens to
        # match the shape, and reporting its rows as OpenCode sessions would
        # be a misdetection dressed up as a result.
        if warn and sessions:
            print(
                f"agent-cost: {p.name}: no OpenCode usage payload found, ignored",
                file=sys.stderr,
            )
        return []

    if warn and skipped:
        print(
            f"agent-cost: {p.name}: {skipped} message row(s) could not be read; "
            f"the totals below are incomplete",
            file=sys.stderr,
        )

    return [s for s in sessions.values() if not (s.total_tokens == 0 and s.turns == 0 and s.tool_calls == 0)]


def _decode_message(raw: object) -> dict | None:
    """Return the message payload as a dict, or None when it is not one.

    SQLite hands back TEXT as ``str`` and BLOB as ``bytes``; OpenCode writes
    JSON either way, so a bytes column must be decoded rather than dropped.
    """
    if isinstance(raw, (bytes, bytearray)):
        raw = bytes(raw).decode("utf-8")
    if isinstance(raw, str):
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    if isinstance(raw, dict):
        return raw
    return None


def _process_opencode_event(
    event: dict,
    stats: SessionStats,
    tool_map: dict[str, str] | None = None,
    last_tool: list[str] | None = None,
) -> None:
    if "session_id" in event or "sessionId" in event:
        stats.session_key = str(event.get("session_id") or event.get("sessionId") or stats.session_key)
    if ("model" in event or "modelID" in event) and not stats.model:
        stats.model = str(event.get("model") or event.get("modelID") or "")
    if "created_at" in event or "timestamp" in event:
        ts = str(event.get("created_at") or event.get("timestamp") or "")
        if not stats.created_at:
            stats.created_at = ts
        stats.updated_at = ts

    etype = str(event.get("type") or "")

    # Tool output/results
    if etype in ("tool_result", "action_result", "tool-result") or "tool_result" in event:
        t_id = event.get("toolCallId") or event.get("id") or event.get("tool_use_id")
        t_name = (
            (tool_map.get(str(t_id)) if tool_map and t_id else None)
            or event.get("tool")
            or event.get("name")
            or (last_tool[0] if last_tool else "tool")
        )
        res = event.get("result") or event.get("output") or event.get("content") or ""
        chars = _chars(res)
        stats.record_tool_output(t_name, chars, content=res)
    # Step or turn level tool calls
    elif etype in ("tool_call", "action", "tool-call") or "tool" in event or "toolCalls" in event or "tools" in event:
        # First key that is actually present wins -- an `or` chain would treat an
        # explicitly empty tool list as absent and fall through to counting one.
        tool = next(
            (event[k] for k in ("tool", "action", "toolCalls", "tools") if event.get(k) is not None),
            "",
        )
        if isinstance(tool, (list, tuple)):
            for t in tool:
                if isinstance(t, dict):
                    t_name = str(t.get("name") or t.get("tool") or "tool")
                    t_id = t.get("id") or t.get("toolCallId")
                    if t_id and tool_map is not None:
                        tool_map[str(t_id)] = t_name
                    if last_tool is not None:
                        last_tool[0] = t_name
                    stats.record_tool_call(t_name, _chars(t_name), t.get("input") or t.get("arguments"))
                else:
                    t_name = str(t or "tool")
                    if last_tool is not None:
                        last_tool[0] = t_name
                    stats.record_tool_call(t_name, _chars(t_name))
        elif isinstance(tool, dict):
            t_name = str(tool.get("name") or tool.get("tool") or "tool")
            t_id = tool.get("id") or tool.get("toolCallId")
            if t_id and tool_map is not None:
                tool_map[str(t_id)] = t_name
            if last_tool is not None:
                last_tool[0] = t_name
            stats.record_tool_call(t_name, _chars(t_name), tool.get("input") or tool.get("arguments"))
        else:
            t_name = str(tool or "tool")
            if last_tool is not None:
                last_tool[0] = t_name
            stats.record_tool_call(t_name, _chars(t_name))

    # Handle AI SDK / OpenCode parts list
    parts = event.get("parts")
    if isinstance(parts, list):
        for p in parts:
            if isinstance(p, dict):
                ptype = p.get("type")
                if ptype in ("tool-call", "tool_call"):
                    t_name = str(p.get("toolName") or p.get("name") or p.get("tool") or "tool")
                    t_id = p.get("toolCallId") or p.get("id")
                    if t_id and tool_map is not None:
                        tool_map[str(t_id)] = t_name
                    if last_tool is not None:
                        last_tool[0] = t_name
                    stats.record_tool_call(t_name, _chars(t_name))
                elif ptype in ("tool-result", "tool_result"):
                    t_id = p.get("toolCallId") or p.get("id")
                    t_name = (
                        (tool_map.get(str(t_id)) if tool_map and t_id else None)
                        or p.get("toolName")
                        or p.get("name")
                        or (last_tool[0] if last_tool else "tool")
                    )
                    res = p.get("result") or p.get("output") or p.get("content") or ""
                    stats.record_tool_output(t_name, _chars(res), content=res)

    if event.get("type") == "compaction":
        stats.compaction_events += 1

    # Format 1: Standard usage dict
    usage = event.get("usage")
    if isinstance(usage, dict):
        inp, out, cached, cache_write = _read_usage(usage)
        stats.input_tokens += inp
        stats.output_tokens += out
        stats.cache_read_tokens += cached
        stats.cache_write_tokens += cache_write
        stats.turns += 1
        stats.sample_context(inp + cached + cache_write)
        return

    # Format 2: OpenCode's native `tokens` dict, as written by the AI SDK.
    #
    # ASSUMED SEMANTICS: `input` EXCLUDES `cache.read`, so the two are summed
    # rather than netted -- the Anthropic convention that `_read_usage` applies
    # to `input_tokens`.
    #
    # This one cannot be decided from the field names the way `_read_usage`
    # does: the AI SDK normalises every provider onto the same `input` key,
    # while the meaning still follows the provider underneath (OpenAI's
    # `prompt_tokens` includes the cached prefix, Anthropic's `input_tokens`
    # does not). On an OpenAI-backed OpenCode session this therefore
    # double-counts the cached prefix. Documented as a known limitation until
    # it can be checked against a real OpenAI-backed `opencode.db`; do not
    # "fix" it by guessing the provider from the model id.
    #
    # `tokens.reasoning` is deliberately NOT added: reasoning tokens are a
    # subset of `output` (OpenAI bills them inside `completion_tokens`,
    # Anthropic inside `output_tokens`), so adding them would double-count.
    tokens = event.get("tokens")
    if isinstance(tokens, dict):
        inp = int(tokens.get("input") or 0)
        out = int(tokens.get("output") or 0)
        cache_obj = tokens.get("cache")
        if isinstance(cache_obj, dict):
            cached = int(cache_obj.get("read") or 0)
            cache_write = int(cache_obj.get("write") or 0)
        else:
            cached = int(tokens.get("cached") or tokens.get("cache_read") or 0)
            cache_write = int(tokens.get("cache_write") or 0)

        stats.input_tokens += inp
        stats.output_tokens += out
        stats.cache_read_tokens += cached
        stats.cache_write_tokens += cache_write
        stats.turns += 1
        stats.sample_context(inp + cached + cache_write)


def _parse_opencode_dict(data: dict, stats: SessionStats) -> SessionStats:
    stats.session_key = str(data.get("session_id") or data.get("id") or stats.session_key)
    stats.model = str(data.get("model") or data.get("modelID") or stats.model)
    stats.created_at = str(data.get("created_at") or "")
    stats.updated_at = str(data.get("updated_at") or "")

    tool_map: dict[str, str] = {}
    last_tool: list[str] = ["tool"]
    steps = data.get("steps") or data.get("history") or data.get("messages") or []
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict):
                _process_opencode_event(step, stats, tool_map=tool_map, last_tool=last_tool)

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
    tool_map: dict[str, str] = {}
    last_tool: list[str] = ["tool"]
    for rec in records:
        if isinstance(rec, dict):
            _process_opencode_event(rec, stats, tool_map=tool_map, last_tool=last_tool)
    return stats

