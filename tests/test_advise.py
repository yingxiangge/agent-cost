from __future__ import annotations

from agent_cost.advise import advise
from agent_cost.models import SessionStats
from agent_cost.report import HOOK_SNIPPET, format_advice


def _session(key: str, turns: list[list[tuple[str, str, int]]]) -> SessionStats:
    """Build a session from [(tool, detail, output_chars), ...] per turn."""
    stats = SessionStats(agent="claude-code", session_key=key)
    for index, tools in enumerate(turns, start=1):
        for tool, detail, chars in tools:
            stats.record_tool_output(tool, chars, detail=detail)
        stats.turns = index
        stats.sample_context(10_000 * index)
    return stats


def _repeated(key: str, tool: str, detail: str, chars: int, at: list[int], length: int):
    turns: list[list[tuple[str, str, int]]] = [[] for _ in range(length)]
    for index in at:
        turns[index] = [(tool, detail, chars)]
    return _session(key, turns)


def test_a_one_off_call_is_not_a_habit():
    """Nothing can be changed about a call that happens once.

    The expensive one-off is deliberately larger than the habit, so a ranking
    that ignored recurrence would put it first.
    """
    sessions = [
        _repeated("s1", "Read", "hot.md", 4_000, [1], 20),
        _repeated("s2", "Read", "hot.md", 4_000, [1], 20),
        _repeated("s3", "Bash", "one-off dump", 40_000, [1], 20),
    ]

    result = advise(sessions)
    details = [habit["detail"] for habit in result["habits"]]

    assert details == ["hot.md"]
    assert "one-off dump" not in details


def test_recurrence_is_summed_across_sessions():
    sessions = [
        _repeated("s1", "Read", "notes.md", 4_000, [1, 5], 20),
        _repeated("s2", "Read", "notes.md", 4_000, [2], 20),
    ]

    habit = advise(sessions)["habits"][0]

    assert habit["occurrences"] == 3
    assert habit["avg_output_chars"] == 4_000
    # 1_000 tokens carried by 18 + 14 turns in s1, and 17 in s2.
    assert habit["carried_tokens"] == 1_000 * (18 + 14 + 17)


def test_habits_are_ranked_by_carried_cost():
    sessions = [
        _repeated("s1", "Read", "late.md", 9_000, [17, 18], 20),
        _repeated("s2", "Read", "early.md", 4_000, [1, 2], 20),
    ]

    ranked = [habit["detail"] for habit in advise(sessions)["habits"]]

    assert ranked == ["early.md", "late.md"]


def test_advice_comes_from_the_tool_classifier():
    """An unseen tool name inherits its category's advice, never nothing."""
    sessions = [
        _repeated("s1", "run_command", "pytest -q", 4_000, [1, 2], 20),
        _repeated("s2", "some_new_grep_tool", "x", 4_000, [1, 2], 20),
    ]

    by_tool = {habit["tool"]: habit for habit in advise(sessions)["habits"]}

    assert by_tool["run_command"]["category"] == "shell"
    assert by_tool["some_new_grep_tool"]["category"] == "search"
    assert all(habit["advice"] for habit in by_tool.values())


def test_min_occurrences_and_limit_are_honoured():
    sessions = [
        _repeated("s1", "Read", "a.md", 4_000, [1, 2, 3], 20),
        _repeated("s2", "Read", "b.md", 3_000, [1, 2], 20),
        _repeated("s3", "Read", "c.md", 2_000, [1], 20),
    ]

    assert [h["detail"] for h in advise(sessions, limit=1)["habits"]] == ["a.md"]
    assert advise(sessions)["habit_count"] == 2
    assert advise(sessions, min_occurrences=1)["habit_count"] == 3


def test_sessions_without_attribution_are_skipped_not_counted():
    plain = SessionStats(agent="codex", session_key="no-attribution")
    for value in (1_000, 2_000):
        plain.turns += 1
        plain.sample_context(value)

    result = advise([plain, _repeated("s1", "Read", "a.md", 4_000, [1, 2], 20)])

    assert result["sessions_seen"] == 2
    assert result["sessions_analyzed"] == 1


def test_rendering_groups_advice_by_category():
    sessions = [
        _repeated("s1", "Read", "a.md", 4_000, [1, 2], 20),
        _repeated("s2", "Read", "b.md", 3_000, [1, 2], 20),
    ]

    rendered = format_advice(advise(sessions))

    assert "a.md" in rendered and "b.md" in rendered
    # One advice line for the category, not one per habit.
    assert rendered.count("Locate with a search first") == 1


def test_rendering_says_so_when_nothing_recurs():
    rendered = format_advice(advise([_repeated("s1", "Read", "a.md", 4_000, [1], 20)]))
    assert "No recurring expensive calls" in rendered


def test_hook_snippet_is_valid_settings_json():
    import json

    parsed = json.loads(HOOK_SNIPPET)
    entry = parsed["hooks"]["SessionStart"][0]

    assert entry["hooks"][0]["type"] == "command"
    assert entry["hooks"][0]["command"].startswith("agent-cost advise")
