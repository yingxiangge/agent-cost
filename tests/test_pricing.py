import pytest

from agent_cost.pricing import estimate_cost, resolve_pricing, validate_custom_pricing


def test_estimate_cost_deepseek():
    cost, status = estimate_cost(1_000_000, 200_000, 3_000_000, 0, "deepseek-chat")
    assert status == "estimated"
    assert cost is not None and cost > 0


def test_unknown_model_is_unpriced_not_guessed():
    """An unlisted model must report `unknown`, never another model's prices."""
    for model in ("", "<synthetic>", "some-local-llama", "gemini-2.5-pro", "mistral-large"):
        cost, status = estimate_cost(1000, 100, 0, 0, model)
        assert status == "unknown", model
        assert cost is None, model


def test_current_anthropic_models_are_priced():
    """Claude Code writes these model ids; none may fall through to `unknown`."""
    expected = {
        "claude-opus-5": (5.0, 25.0),
        "claude-opus-4-8": (5.0, 25.0),
        "claude-sonnet-5": (2.0, 10.0),
        "claude-haiku-4-5": (1.0, 5.0),
        "claude-fable-5": (10.0, 50.0),
    }
    for model, (inp, out) in expected.items():
        table = resolve_pricing(model)
        assert table is not None, model
        assert (table["input"], table["output"]) == (inp, out), model


def test_opus_4_1_is_not_swallowed_by_opus_4_5():
    """Longest-prefix must not blur two families with very different prices."""
    assert resolve_pricing("claude-opus-4-1")["input"] == 15.0
    assert resolve_pricing("claude-opus-4-5")["input"] == 5.0


def test_dated_model_resolves_to_its_family():
    assert resolve_pricing("claude-opus-4-5-20260101") == resolve_pricing("claude-opus-4-5")
    assert resolve_pricing("claude-3-5-sonnet-20241022") == resolve_pricing("claude-3-5-sonnet")


def test_provider_prefix_is_stripped():
    assert resolve_pricing("deepseek/deepseek-chat") == resolve_pricing("deepseek-chat")


def test_longest_prefix_wins():
    """gpt-5-mini must not be priced as gpt-5."""
    assert resolve_pricing("gpt-5-mini") == resolve_pricing("gpt-5-mini")
    assert resolve_pricing("gpt-5-mini") != resolve_pricing("gpt-5")
    assert resolve_pricing("gpt-5-codex") == resolve_pricing("gpt-5")


def test_custom_pricing_merges_instead_of_replacing():
    custom = {"claude-opus-5": {"input": 5.0, "output": 25.0, "cache_read": 0.5, "cache_write": 6.25}}

    cost, status = estimate_cost(1_000_000, 0, 0, 0, "claude-opus-5", custom)
    assert status == "estimated"
    assert cost == 5.0

    # Overriding one model must leave the built-in table intact.
    cost, status = estimate_cost(1_000_000, 0, 0, 0, "deepseek-chat", custom)
    assert status == "estimated"
    assert cost == 0.14


def test_custom_pricing_allows_comment_metadata():
    custom = {
        "_comment": "copied from pricing.example.json",
        "local-model": {"input": 0.0, "output": 0.0},
    }

    assert validate_custom_pricing(custom) == custom
    cost, status = estimate_cost(1_000_000, 1_000_000, 0, 0, "local-model", custom)
    assert status == "estimated"
    assert cost == 0.0


@pytest.mark.parametrize(
    ("custom", "message"),
    [
        ([], "custom pricing must be a JSON object"),
        ({"bad-model": []}, "pricing entry 'bad-model' must be an object"),
        ({"bad-model": {"input": 1.0}}, "pricing entry 'bad-model'.output is required"),
        (
            {"bad-model": {"input": 1.0, "output": 2.0, "latency": 3.0}},
            "pricing entry 'bad-model'.latency is not supported",
        ),
        ({"bad-model": {"input": "1", "output": 2.0}}, "pricing entry 'bad-model'.input must be a number"),
        ({"bad-model": {"input": 1.0, "output": -2.0}}, "pricing entry 'bad-model'.output must be non-negative"),
    ],
)
def test_custom_pricing_validation_errors_name_the_bad_key(custom, message):
    with pytest.raises(ValueError, match=message):
        validate_custom_pricing(custom)
