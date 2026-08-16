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
