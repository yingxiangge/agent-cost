import json
from datetime import datetime, timedelta, timezone

import pytest

from agent_cost.analyze import analyze
from agent_cost.baseline import (
    baseline_path,
    diff_summaries,
    list_baselines,
    load_baseline,
    parse_time,
    save_baseline,
    split_by_cutoff,
)
from agent_cost.cli import main
from agent_cost.models import SessionStats
from agent_cost.summary import summarize


@pytest.fixture(autouse=True)
def isolated_baseline_dir(monkeypatch, tmp_path):
    monkeypatch.setattr("agent_cost.baseline.BASELINE_DIR", tmp_path / "baselines")


def _session(key: str, created_at: str, tool_chars: int = 600) -> SessionStats:
    stats = SessionStats(agent="claude-code", session_key=key, created_at=created_at)
    stats.turns = 4
    stats.input_tokens = 1_000
    stats.output_tokens = 400
    stats.cache_read_tokens = 9_000
    stats.context_samples = [
        {"turn": 1, "estimated_prompt_tokens": 1_000},
        {"turn": 4, "estimated_prompt_tokens": 5_000},
    ]
    stats.source_chars = {"tool_output": tool_chars, "assistant": 200}
    stats.tool_stats = {
        "Bash": {"calls": 3, "output_chars": tool_chars, "images": 0, "image_tokens": 0}
    }
    return stats


def test_split_by_cutoff_keeps_only_later_sessions():
    cutoff = "2026-08-20T00:00:00Z"
    sessions = [
        _session("old", "2026-08-19T23:59:00Z"),
        _session("new", "2026-08-21T10:00:00Z"),
        _session("also-new", "2026-09-01T10:00:00Z"),
    ]
    after, undateable = split_by_cutoff(sessions, cutoff)

    assert [s.session_key for s in after] == ["new", "also-new"]
    assert undateable == 0


def test_split_by_cutoff_excludes_undateable_rather_than_guessing():
    """A session with no timestamp belongs to neither window; it is counted, not folded in."""
    sessions = [_session("dated", "2026-08-21T10:00:00Z"), _session("undated", "")]
    after, undateable = split_by_cutoff(sessions, "2026-08-20T00:00:00Z")

    assert [s.session_key for s in after] == ["dated"]
    assert undateable == 1


def test_split_by_cutoff_handles_mixed_timezone_offsets():
    """08-20 07:00+08:00 is 08-19 23:00 UTC: before the cutoff, despite the later date."""
    sessions = [_session("tz", "2026-08-20T07:00:00+08:00")]
    after, _ = split_by_cutoff(sessions, "2026-08-20T00:00:00Z")

    assert after == []


def test_parse_time_rejects_junk():
    assert parse_time("") is None
    assert parse_time("not a date") is None
    assert parse_time("2026-08-20T00:00:00Z") == datetime(2026, 8, 20, tzinfo=timezone.utc)


def test_save_and_list_roundtrip():
    summary = summarize([(s, analyze(s)) for s in (_session("a", "2026-08-01T00:00:00Z"),)])
    path = save_baseline("before-rtk", summary)

    assert json.loads(path.read_text())["label"] == "before-rtk"
    assert load_baseline("before-rtk")["summary"]["totals"]["sessions"] == 1
    listed = list_baselines()
    assert [item["label"] for item in listed] == ["before-rtk"]
    assert listed[0]["sessions"] == 1


def test_label_cannot_escape_the_baseline_directory():
    with pytest.raises(ValueError):
        baseline_path("../../etc/passwd")


def test_diff_reports_share_moves_in_points():
    before = summarize([(s, analyze(s)) for s in (_session("a", "2026-08-01T00:00:00Z", 600),)])
    after = summarize([(s, analyze(s)) for s in (_session("b", "2026-08-25T00:00:00Z", 200),)])
    diff = diff_summaries(before, after)

    cache = next(m for m in diff["metrics"] if m["name"] == "Cache hit")
    assert "delta_pt" in cache  # shares move in points, never percent-of-percent

    tool_output = next(r for r in diff["sources"] if r["source"] == "tool_output")
    assert tool_output["before_pct"] == pytest.approx(0.75)
    assert tool_output["after_pct"] == pytest.approx(0.5)
    assert tool_output["delta_pt"] == pytest.approx(-0.25)


def test_waste_is_normalised_per_session():
    """Windows differ in size, so waste counts must be per session to compare."""
    before = summarize([(s, analyze(s)) for s in (_session("a", "2026-08-01T00:00:00Z"),)])
    before["waste"]["repeated_file_reads"] = 10
    before["totals"]["sessions"] = 10
    after = summarize([(s, analyze(s)) for s in (_session("b", "2026-08-25T00:00:00Z"),)])
    after["waste"]["repeated_file_reads"] = 1
    after["totals"]["sessions"] = 4

    row = next(r for r in diff_summaries(before, after)["waste"] if "repeated" in r["name"])
    assert row["before"] == pytest.approx(1.0)
    assert row["after"] == pytest.approx(0.25)
    assert row["pct_change"] == pytest.approx(-0.75)


def test_diff_without_a_baseline_says_how_to_make_one(capsys):
    assert main(["diff", "--against", "nope", "examples/claude_session.sanitized.jsonl"]) == 1
    assert "agent-cost baseline --label nope" in capsys.readouterr().err


def test_diff_with_no_new_sessions_stops_instead_of_printing_zeroes(capsys):
    main(["baseline", "--label", "now", "examples/claude_session.sanitized.jsonl"])
    capsys.readouterr()

    assert main(["diff", "--against", "now", "examples/claude_session.sanitized.jsonl"]) == 1
    assert "nothing to compare yet" in capsys.readouterr().err


def test_baseline_list_needs_no_sessions(capsys):
    main(["baseline", "--label", "kept", "examples/claude_session.sanitized.jsonl"])
    capsys.readouterr()

    assert main(["baseline", "--list"]) == 0
    assert "kept" in capsys.readouterr().out
