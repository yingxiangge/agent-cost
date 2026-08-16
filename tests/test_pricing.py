from agent_cost.pricing import estimate_cost, resolve_pricing


def test_estimate_cost_deepseek():
    cost, status = estimate_cost(1_000_000, 200_000, 3_000_000, 0, "deepseek-chat")
    assert status == "estimated"
    assert cost is not None and cost > 0


def test_unknown_model_is_unpriced_not_guessed():
    """An unlisted model must report `unknown`, never another model's prices."""
    for model in ("", "<synthetic>", "claude-opus-5", "some-local-llama", "gemini-2.5-pro"):
        cost, status = estimate_cost(1000, 100, 0, 0, model)
        assert status == "unknown", model
        assert cost is None, model


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
    assert cost == 0.27
