from pathlib import Path

from agent_cost.parsers.opencode import _read_usage, parse_opencode_session


def test_parse_opencode_session():
    stats = parse_opencode_session(Path("examples/opencode_session.sanitized.json"))
    assert stats.agent == "opencode"
    assert stats.session_key == "opencode-sanitized-001"
    assert stats.turns == 2
    assert stats.tool_calls == 2
    # prompt_tokens (3500, 4200) already include cached_tokens (2800, 3600),
    # so the uncached input is 700 + 600 -- not 7700.
    assert stats.input_tokens == 1300
    assert stats.output_tokens == 430
    assert stats.cache_read_tokens == 6400
    assert stats.prompt_tokens == 7700
    assert stats.total_tokens == 8130
    assert stats.cache_hit_rate == 6400 / 7700
    assert stats.model == "deepseek-chat"


def test_openai_usage_does_not_double_count_cache():
    """prompt_tokens includes the cached prefix and must be netted out."""
    inp, out, cached, cache_write = _read_usage(
        {"prompt_tokens": 3500, "completion_tokens": 120, "cached_tokens": 2800}
    )
    assert (inp, out, cached, cache_write) == (700, 120, 2800, 0)


def test_anthropic_usage_is_taken_as_is():
    """input_tokens already excludes the cached prefix and must not be reduced."""
    inp, out, cached, cache_write = _read_usage(
        {"input_tokens": 700, "output_tokens": 120, "cache_read_tokens": 2800, "cache_write_tokens": 50}
    )
    assert (inp, out, cached, cache_write) == (700, 120, 2800, 50)


def test_usage_never_goes_negative():
    inp, _, cached, _ = _read_usage({"prompt_tokens": 100, "cached_tokens": 500})
    assert inp == 0
    assert cached == 500


def test_parse_opencode_sqlite(tmp_path):
    import json
    import sqlite3
    from agent_cost.parsers.detect import load_path
    from agent_cost.parsers.opencode import parse_opencode_sqlite

    db_file = tmp_path / "opencode.db"
    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("CREATE TABLE session (id TEXT PRIMARY KEY, created_at TEXT, updated_at TEXT, modelID TEXT)")
    cur.execute("CREATE TABLE message (id INTEGER PRIMARY KEY, session_id TEXT, data TEXT)")

    cur.execute(
        "INSERT INTO session (id, created_at, updated_at, modelID) VALUES (?, ?, ?, ?)",
        ("ses_123", "2026-08-20T10:00:00Z", "2026-08-20T10:05:00Z", "claude-3-5-sonnet"),
    )

    msg1 = {
        "role": "assistant",
        "tokens": {
            "input": 1200,
            "output": 350,
            "cache": {"read": 4000, "write": 500},
        },
        "toolCalls": ["read_file"],
    }
    msg2 = {
        "role": "assistant",
        "tokens": {
            "input": 800,
            "output": 200,
            "cache": {"read": 5000, "write": 0},
        },
        "toolCalls": ["write_to_file"],
    }

    cur.execute("INSERT INTO message (session_id, data) VALUES (?, ?)", ("ses_123", json.dumps(msg1)))
    cur.execute("INSERT INTO message (session_id, data) VALUES (?, ?)", ("ses_123", json.dumps(msg2)))
    conn.commit()
    conn.close()

    # Direct parser test
    res = parse_opencode_sqlite(db_file)
    assert len(res) == 1
    st = res[0]
    assert st.agent == "opencode"
    assert st.session_key == "ses_123"
    assert st.model == "claude-3-5-sonnet"
    assert st.input_tokens == 2000
    assert st.output_tokens == 550
    assert st.cache_read_tokens == 9000
    assert st.cache_write_tokens == 500
    assert st.turns == 2
    assert st.tool_calls == 2

    # load_path auto-detection test
    loaded = load_path(db_file)
    assert len(loaded) == 1
    assert loaded[0].session_key == "ses_123"

