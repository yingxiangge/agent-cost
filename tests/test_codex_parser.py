from pathlib import Path

from agent_cost.parsers.codex import parse_codex_rollout


def test_parse_codex_rollout():
    stats = parse_codex_rollout(Path("examples/codex_rollout.sanitized.jsonl"))
    assert stats.agent == "codex"
    assert stats.session_key == "sanitized-session-0001"
    assert stats.turns == 3
    assert stats.tool_calls == 1
    assert stats.compaction_events == 1
    assert stats.source_chars["tool_output"] > 0
    assert stats.context_samples[0]["estimated_prompt_tokens"] >= 1
