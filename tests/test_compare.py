from pathlib import Path

from agent_cost.compare import compare_sessions
from agent_cost.parsers.detect import load_path
from agent_cost.report import format_compare


def test_compare_sessions():
    sessions = []
    sessions.extend(load_path(Path("examples/codex_rollout.sanitized.jsonl")))
    sessions.extend(load_path(Path("examples/hermes_sessions.sanitized.json")))
    sessions.extend(load_path(Path("examples/claude_session.sanitized.jsonl")))
    sessions.extend(load_path(Path("examples/opencode_session.sanitized.json")))

    assert len(sessions) >= 5
    result = compare_sessions(sessions)

    assert result.total_sessions >= 5
    assert "codex" in result.agent_summaries
    assert "hermes" in result.agent_summaries
    assert "claude-code" in result.agent_summaries
    assert "opencode" in result.agent_summaries

    text = format_compare(result)
    assert "Agent Comparison Report" in text
    assert "hermes" in text
    assert "claude-code" in text
    assert "codex" in text
    assert "opencode" in text
    assert "TOTAL" in text
