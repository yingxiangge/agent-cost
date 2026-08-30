from pathlib import Path

import pytest

from agent_cost.analyze import analyze
from agent_cost.cli import main
from agent_cost.discover import discover_paths
from agent_cost.models import SessionStats
from agent_cost.report import format_summary
from agent_cost.summary import summarize


def _session(agent: str, key: str) -> SessionStats:
    stats = SessionStats(agent=agent, session_key=key)
    stats.turns = 4
    stats.input_tokens = 1_000
    stats.output_tokens = 400
    stats.cache_read_tokens = 9_000
    stats.cache_write_tokens = 0
    stats.context_samples = [
        {"turn": 1, "estimated_prompt_tokens": 1_000},
        {"turn": 4, "estimated_prompt_tokens": 5_000},
    ]
    stats.source_chars = {"tool_output": 800, "assistant": 200}
    stats.tool_stats = {
        "Bash": {"calls": 3, "output_chars": 600, "images": 0, "image_tokens": 0},
        "Read": {"calls": 1, "output_chars": 200, "images": 0, "image_tokens": 0},
    }
    return stats


def test_summarize_totals_and_ratios():
    pairs = [(s, analyze(s)) for s in (_session("codex", "a"), _session("claude-code", "b"))]
    summary = summarize(pairs)
    totals = summary["totals"]

    assert totals["sessions"] == 2
    assert totals["agents"] == ["claude-code", "codex"]
    assert totals["turns"] == 8
    # prompt = input + cache read + cache write, summed across both sessions
    assert totals["prompt_tokens"] == 20_000
    assert totals["cache_hit_rate"] == pytest.approx(0.9)
    assert totals["prompt_per_turn"] == 2_500
    assert totals["output_per_turn"] == 100
    assert totals["context_to_output_ratio"] == pytest.approx(25.0)


def test_summarize_growth_and_ranking():
    pairs = [(s, analyze(s)) for s in (_session("codex", "a"),)]
    summary = summarize(pairs)

    growth = summary["context_growth"]
    assert growth["sessions"] == 1
    assert growth["first_turn_avg"] == 1_000
    assert growth["last_turn_avg"] == 5_000
    assert growth["growth_ratio"] == pytest.approx(5.0)

    # Both rankings are largest-first, and percentages are shares of their own total.
    assert [s["source"] for s in summary["sources"]] == ["tool_output", "assistant"]
    assert summary["sources"][0]["pct"] == pytest.approx(0.8)
    assert [t["tool"] for t in summary["tools"]] == ["Bash", "Read"]
    assert summary["tools"][0]["pct"] == pytest.approx(0.75)


def test_summarize_survives_empty_sessions():
    """A session with no turns must not divide by zero."""
    empty = SessionStats(agent="codex", session_key="empty")
    summary = summarize([(empty, analyze(empty))])

    assert summary["totals"]["turns"] == 0
    assert summary["totals"]["cache_hit_rate"] == 0.0
    assert summary["totals"]["context_to_output_ratio"] is None
    assert summary["context_growth"] is None
    assert "0 turns" in format_summary(summary)


def test_analyze_with_no_paths_reports_where_it_looked(monkeypatch, capsys):
    monkeypatch.setattr("agent_cost.cli.discover_paths", lambda: [])
    assert main(["analyze"]) == 1
    err = capsys.readouterr().err
    assert "none of the default locations exist" in err
    assert "~/.claude/projects" in err


def test_discover_skips_locations_that_do_not_exist(monkeypatch, tmp_path):
    present = tmp_path / "projects"
    present.mkdir()
    monkeypatch.setattr(
        "agent_cost.discover.DEFAULT_LOCATIONS",
        (("Claude Code", str(present)), ("Codex", str(tmp_path / "absent"))),
    )
    assert discover_paths() == [Path(present)]
