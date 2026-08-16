import json
from agent_cost.cli import main


def test_cli_smoke(capsys):
    # inspect
    ret = main(["inspect", "examples/claude_session.sanitized.jsonl"])
    assert ret == 0
    out = capsys.readouterr().out
    assert "claude-code" in out
    assert "Input" in out

    # analyze
    ret = main(["analyze", "examples/codex_rollout.sanitized.jsonl"])
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
