from agent_cost.pricing import estimate_cost


def test_estimate_cost_deepseek():
    cost, status = estimate_cost(1_000_000, 200_000, 3_000_000, 0, "deepseek-chat")
    assert status == "estimated"
    assert cost is not None and cost > 0


def test_estimate_cost_unknown_model_falls_back():
    cost, status = estimate_cost(1000, 100, 0, 0, "")
    assert status == "estimated"
    assert cost is not None and cost > 0
