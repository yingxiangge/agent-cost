from pathlib import Path

from agent_cost.parsers.hermes import parse_hermes_sessions


def test_parse_hermes_sessions():
    stats = parse_hermes_sessions(Path("examples/hermes_sessions.sanitized.json"))
    assert len(stats) == 2
    first = stats[0]
    assert first.agent == "hermes"
    assert first.input_tokens == 151_127
    assert first.cache_read_tokens == 1_691_204
    assert abs(first.cache_hit_rate - 1691204 / 1842331) < 1e-9
    assert first.total_tokens == 1_993_458
    assert first.context_samples[-1]["estimated_prompt_tokens"] == 87_321
