from __future__ import annotations

from agent_cost.analyze import analyze
from agent_cost.carried import CHARS_PER_TOKEN, carried_cost
from agent_cost.models import SessionStats
from agent_cost.report import format_analyze


def _session(turns: list[list[tuple[str, str, int]]]) -> SessionStats:
    """Build a session from [(tool, detail, output_chars), ...] per turn."""
    stats = SessionStats(agent="claude-code", session_key="carried")
    for index, tools in enumerate(turns, start=1):
        for tool, detail, chars in tools:
            stats.record_tool_output(tool, chars, detail=detail)
        stats.turns = index
        stats.sample_context(10_000 * index)
    return stats


def test_the_same_output_costs_more_early_than_late():
    """Rank by size alone and these two look identical; they are not."""
    turns: list[list[tuple[str, str, int]]] = [[] for _ in range(10)]
    turns[1] = [("Read", "early.md", 4_000)]
    turns[8] = [("Read", "late.md", 4_000)]

    result = carried_cost(_session(turns))
    first, second = result["calls"][0], result["calls"][1]

    assert first["detail"] == "early.md"
    assert second["detail"] == "late.md"
    assert first["turns_after"] == 8
    assert second["turns_after"] == 1
    assert first["carried_tokens"] == 4_000 // CHARS_PER_TOKEN * 8
    assert second["carried_tokens"] == 4_000 // CHARS_PER_TOKEN * 1


def test_a_small_early_call_can_outrank_a_large_late_one():
    turns: list[list[tuple[str, str, int]]] = [[] for _ in range(20)]
    turns[1] = [("Bash", "sed -n '1,80p' x.py", 4_000)]
    turns[18] = [("Read", "big.md", 20_000)]

    result = carried_cost(_session(turns))

    assert result["calls"][0]["detail"] == "sed -n '1,80p' x.py"
    assert result["calls"][0]["carried_tokens"] > result["calls"][1]["carried_tokens"]


def test_the_requesting_turn_is_not_charged():
    """Only the repeats after the turn that needed the output are counted."""
    result = carried_cost(_session([[("Read", "only.md", 8_000)]]))
    assert result["calls"][0]["turns_after"] == 0
    assert result["calls"][0]["carried_tokens"] == 0


def test_totals_shares_and_per_tool_rollup():
    turns: list[list[tuple[str, str, int]]] = [[] for _ in range(5)]
    turns[0] = [("Bash", "a", 4_000), ("Read", "b", 4_000)]
    turns[3] = [("Bash", "c", 4_000)]

    result = carried_cost(_session(turns), limit=2)

    # 4 turns after turn 1 for the first two calls, 1 after turn 4.
    assert result["total_carried_tokens"] == 1_000 * 4 + 1_000 * 4 + 1_000 * 1
    assert result["call_count"] == 3
    assert len(result["calls"]) == 2
    assert result["by_tool"] == {"Bash": 5_000, "Read": 4_000}
    assert result["top_share"] == 8_000 / 9_000


def test_absent_without_per_turn_attribution():
    """Parsers that cannot see individual calls report nothing, not zeros."""
    stats = SessionStats(agent="codex", session_key="no-attribution")
    for value in (1_000, 2_000, 3_000):
        stats.turns += 1
        stats.sample_context(value)

    assert carried_cost(stats) is None


def test_legacy_samples_without_a_tools_field_are_tolerated():
    stats = SessionStats(agent="claude-code", session_key="legacy")
    stats.context_samples = [
        {"turn": 1, "estimated_prompt_tokens": 1_000},
        {"turn": 2, "estimated_prompt_tokens": 2_000},
    ]
    assert carried_cost(stats) is None


def test_output_free_calls_are_skipped():
    stats = _session([[("Edit", "x.py", 0)], [("Read", "y.md", 400)], []])
    result = carried_cost(stats)

    assert [call["tool"] for call in result["calls"]] == ["Read"]


def test_analyze_and_report_surface_carried_cost():
    turns: list[list[tuple[str, str, int]]] = [[] for _ in range(10)]
    turns[1] = [("Read", "notes/BUG_LOG.md", 20_000)]
    stats = _session(turns)

    signals = analyze(stats)
    assert signals["carried_cost"]["calls"][0]["detail"] == "notes/BUG_LOG.md"
    assert "later turns each carried again" in " ".join(signals["recommendations"])

    rendered = format_analyze(stats, signals)
    assert "Carried cost" in rendered
    assert "notes/BUG_LOG.md" in rendered
    assert "8 later turns" in rendered
