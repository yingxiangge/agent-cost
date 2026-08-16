import json

from agent_cost.cli import main
from agent_cost.models import SessionStats
from agent_cost.parsers.claude import parse_claude_session
from agent_cost.pricing import estimate_cost, estimate_session_cost


def _session(**buckets) -> SessionStats:
    s = SessionStats(agent="claude-code", session_key="t", model="claude-opus-5")
    for mode, tokens in buckets.items():
        speed, _, geo = mode.partition("__")
        s.add_usage(*tokens, speed=speed, inference_geo=geo)
    return s


def test_fast_mode_is_priced_at_fast_rates():
    standard, _ = estimate_cost(1_000_000, 1_000_000, 0, 0, "claude-opus-5")
    fast, _ = estimate_cost(1_000_000, 1_000_000, 0, 0, "claude-opus-5", speed="fast")
    assert standard == 5.0 + 25.0
    assert fast == 10.0 + 50.0


def test_fast_mode_falls_back_for_models_without_fast_rates():
    """Opus 4.6 runs fast requests at standard speed and standard rates."""
    standard, _ = estimate_cost(1_000_000, 0, 0, 0, "claude-opus-4-6")
    fast, _ = estimate_cost(1_000_000, 0, 0, 0, "claude-opus-4-6", speed="fast")
    assert fast == standard


def test_us_inference_geo_applies_the_premium():
    base, _ = estimate_cost(1_000_000, 0, 0, 0, "claude-opus-5")
    us, _ = estimate_cost(1_000_000, 0, 0, 0, "claude-opus-5", inference_geo="us")
    assert us == base * 1.1


def test_not_available_geo_is_standard_priced():
    base, _ = estimate_cost(1_000_000, 0, 0, 0, "claude-opus-5")
    same, _ = estimate_cost(1_000_000, 0, 0, 0, "claude-opus-5", inference_geo="not_available")
    assert same == base


def test_multipliers_stack():
    cost, _ = estimate_cost(1_000_000, 0, 0, 0, "claude-opus-5", speed="fast", inference_geo="us")
    assert cost == 10.0 * 1.1


def test_session_mixing_modes_is_priced_per_bucket():
    """Fast mode can be toggled mid-session; one flat rate would be wrong."""
    s = _session(standard=(1_000_000, 0, 0, 0), fast=(1_000_000, 0, 0, 0))
    cost, status = estimate_session_cost(s)
    assert status == "estimated"
    assert cost == 5.0 + 10.0

    # The flat totals alone would have priced everything at the standard rate.
    flat, _ = estimate_cost(s.input_tokens, 0, 0, 0, s.model)
    assert flat == 10.0
    assert cost != flat


def test_sessions_without_buckets_fall_back_to_totals():
    """Codex/Hermes/OpenCode parsers record no modes and must be unaffected."""
    s = SessionStats(agent="hermes", session_key="t", model="claude-opus-5")
    s.input_tokens = 1_000_000
    assert s.billing_buckets == {}
    cost, status = estimate_session_cost(s)
    assert (cost, status) == (5.0, "estimated")


def test_unknown_model_in_any_bucket_makes_the_session_unknown():
    s = _session(standard=(1000, 0, 0, 0))
    s.model = "some-unlisted-model"
    assert estimate_session_cost(s) == (None, "unknown")


def test_claude_parser_records_billing_modes(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        "\n".join(
            json.dumps(rec)
            for rec in [
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-opus-5",
                        "usage": {"input_tokens": 10, "output_tokens": 1, "speed": "standard",
                                  "inference_geo": "not_available"},
                    },
                },
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-opus-5",
                        "usage": {"input_tokens": 20, "output_tokens": 2, "speed": "fast",
                                  "inference_geo": "us"},
                    },
                },
            ]
        ),
        encoding="utf-8",
    )
    stats = parse_claude_session(p)
    assert stats.input_tokens == 30  # flat totals stay correct
    assert stats.billing_buckets == {
        "standard|not_available": {"input": 10, "output": 1, "cache_read": 0, "cache_write": 0},
        "fast|us": {"input": 20, "output": 2, "cache_read": 0, "cache_write": 0},
    }


def test_subscription_flag_relabels_cost(capsys):
    ret = main(["--subscription", "inspect", "examples/claude_session.sanitized.jsonl"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "included in subscription" in out
    assert "API-equiv. Value" in out

    ret = main(["inspect", "examples/claude_session.sanitized.jsonl"])
    assert ret == 0
    assert "Estimated Cost" in capsys.readouterr().out
