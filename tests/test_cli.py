import json
from agent_cost.cli import main


def test_cli_smoke(capsys):
    # inspect
    ret = main(["inspect", "examples/claude_session.sanitized.jsonl"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "claude-code" in out
    assert "Input" in out

    # analyze rolls up by default
    ret = main(["analyze", "examples/codex_rollout.sanitized.jsonl"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "sessions" in out
    assert "Analysis:" not in out

    # analyze --per-session keeps the per-session view
    ret = main(["analyze", "--per-session", "examples/codex_rollout.sanitized.jsonl"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Analysis:" in out

    # stats
    ret = main(["stats", "examples/"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "AGENT" in out
    assert "TOTAL TOKENS" in out

    # compare text
    ret = main(["compare", "examples/"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "Agent Comparison Report" in out

    # compare json
    ret = main(["compare", "--json", "examples/"])
    assert ret == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["total_sessions"] >= 4
    assert "hermes" in data["agents"]


def test_cli_pricing_validation_errors(capsys, monkeypatch):
    ret = main([
        "--pricing",
        '{"bad-model": {"input": "1", "output": 2}}',
        "inspect",
        "examples/claude_session.sanitized.jsonl",
    ])
    assert ret == 2
    assert "bad-model'.input" in capsys.readouterr().err

    monkeypatch.setenv("AGENT_COST_PRICING", '{"bad-model": {"input": 1}}')
    ret = main(["inspect", "examples/claude_session.sanitized.jsonl"])
    assert ret == 2
    assert "bad-model'.output" in capsys.readouterr().err


def test_cli_rejects_pricing_json_null(capsys):
    ret = main(["--pricing", "null", "inspect", "examples/claude_session.sanitized.jsonl"])
    assert ret == 2
    assert "custom pricing must be a JSON object" in capsys.readouterr().err
