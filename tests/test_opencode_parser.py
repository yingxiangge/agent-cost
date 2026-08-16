from pathlib import Path

from agent_cost.parsers.opencode import parse_opencode_session


def test_parse_opencode_session():
    stats = parse_opencode_session(Path("examples/opencode_session.sanitized.json"))
    assert stats.agent == "opencode"
    assert stats.session_key == "opencode-sanitized-001"
    assert stats.turns == 2
    assert stats.tool_calls == 2
    assert stats.input_tokens == 7700
    assert stats.output_tokens == 430
    assert stats.cache_read_tokens == 6400
    assert stats.cache_hit_rate > 0.4
    assert stats.model == "deepseek-chat"
