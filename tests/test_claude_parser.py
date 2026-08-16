from pathlib import Path

from agent_cost.parsers.claude import parse_claude_session


def test_parse_claude_session():
    stats = parse_claude_session(Path("examples/claude_session.sanitized.jsonl"))
    assert stats.agent == "claude-code"
    assert stats.session_key == "claude-sanitized-001"
    assert stats.turns == 2
    assert stats.tool_calls == 1
    assert stats.input_tokens == 2650
    assert stats.output_tokens == 390
    assert stats.cache_read_tokens == 9300
    assert stats.cache_write_tokens == 250
    assert stats.cache_hit_rate > 0.70
    assert stats.model == "claude-3-5-sonnet-20241022"
