from __future__ import annotations

import json

import pytest

from agent_cost.analyze import (
    DEFAULT_BUDGET,
    NO_TOOL_CULPRIT,
    analyze,
    context_budget,
    parse_budget,
)
from agent_cost.models import SessionStats
from agent_cost.parsers.claude import parse_claude_session
from agent_cost.report import format_analyze


def _write(tmp_path, records) -> str:
    path = tmp_path / "session.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")
    return str(path)


def _usage(prompt: int, output: int = 10) -> dict:
    return {
        "input_tokens": prompt,
        "output_tokens": output,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }


def _assistant(msg_id: str, prompt: int, blocks: list | None = None) -> dict:
    return {
        "type": "assistant",
        "message": {"id": msg_id, "usage": _usage(prompt), "content": blocks or []},
    }


def _tool_result(tool_use_id: str, text: str) -> dict:
    return {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": text}
            ]
        },
    }


# --- usage de-duplication -------------------------------------------------


def test_usage_counted_once_per_message_id(tmp_path):
    """One assistant message split across content-block lines bills once.

    Claude Code repeats the whole usage object on every line of a message, one
    line per content block. Counting each line inflated tokens and turns by
    ~2x across this project's own transcripts.
    """
    path = _write(
        tmp_path,
        [
            _assistant("msg_1", 1000, [{"type": "thinking", "thinking": "..."}]),
            _assistant("msg_1", 1000, [{"type": "text", "text": "hello"}]),
            _assistant("msg_1", 1000, [{"type": "tool_use", "name": "Bash", "id": "t1",
                                        "input": {"command": "ls"}}]),
            _assistant("msg_2", 2000, [{"type": "text", "text": "bye"}]),
        ],
    )
    stats = parse_claude_session(path)

    assert stats.turns == 2
    assert stats.input_tokens == 3000
    assert stats.output_tokens == 20
    # Content blocks differ per line and are still all processed.
    assert stats.tool_stats["Bash"]["calls"] == 1
    assert stats.source_chars["assistant"] == len("hello") + len("bye")


def test_empty_usage_is_not_a_turn(tmp_path):
    """An all-zero usage record is a placeholder, not spend and not a turn."""
    path = _write(
        tmp_path,
        [
            _assistant("msg_1", 1000),
            {"type": "assistant", "message": {"id": "msg_blank", "usage": _usage(0, 0),
                                              "content": []}},
            _assistant("msg_2", 1200),
        ],
    )
    stats = parse_claude_session(path)

    assert stats.turns == 2
    assert [s["estimated_prompt_tokens"] for s in stats.context_samples] == [1000, 1200]
    # Without the guard the zero lands between them and the next delta reads
    # as a +1200 jump instead of +200.
    assert stats.context_samples[-1]["delta"] == 200


# --- per-turn attribution -------------------------------------------------


def test_turn_growth_is_attributed_to_the_tool_that_caused_it(tmp_path):
    """Tool output is charged to the turn whose prompt carries it.

    A tool result appears in the transcript before the usage figure that
    includes it, so it belongs to the *next* sample, not the one before.
    """
    path = _write(
        tmp_path,
        [
            _assistant("msg_1", 1000, [{"type": "tool_use", "name": "Bash", "id": "t1",
                                        "input": {"command": "npm test"}}]),
            _tool_result("t1", "x" * 4000),
            _assistant("msg_2", 5000, [{"type": "text", "text": "done"}]),
        ],
    )
    stats = parse_claude_session(path)

    first, second = stats.context_samples
    assert first["tools"] == []
    assert second["delta"] == 4000
    assert second["tools"][0]["tool"] == "Bash"
    assert second["tools"][0]["detail"] == "npm test"
    assert second["tools"][0]["output_chars"] == 4000

    jump = context_budget(stats)["biggest_jump"]
    assert jump["turn"] == 2
    assert jump["culprit"] == "Bash `npm test`"


def test_jump_without_tool_output_says_so(tmp_path):
    """Growth with no tool behind it is reported, not silently unattributed."""
    path = _write(tmp_path, [_assistant("msg_1", 1000), _assistant("msg_2", 9000)])
    stats = parse_claude_session(path)

    jump = context_budget(stats)["biggest_jump"]
    assert jump["delta"] == 8000
    assert jump["culprit"] == NO_TOOL_CULPRIT


def test_pending_output_is_drained_once():
    """Each tool result is attributed to exactly one turn."""
    stats = SessionStats(agent="claude-code", session_key="drain")
    stats.record_tool_output("Bash", 500, detail="ls")
    stats.sample_context(1000)
    stats.sample_context(1500)

    assert stats.pending_tool_output == []
    assert stats.context_samples[0]["tools"][0]["output_chars"] == 500
    assert stats.context_samples[1]["tools"] == []


# --- budget parsing -------------------------------------------------------


@pytest.mark.parametrize(
    "spec,expected",
    [
        ("warning:100k,critical:150k", {"warning": 100_000, "critical": 150_000}),
        ("critical:1m", {"warning": DEFAULT_BUDGET["warning"], "critical": 1_000_000}),
        ("warning:80000", {"warning": 80_000, "critical": DEFAULT_BUDGET["critical"]}),
        ("", dict(DEFAULT_BUDGET)),
    ],
)
def test_parse_budget_accepts_valid_specs(spec, expected):
    assert parse_budget(spec) == expected


@pytest.mark.parametrize(
    "spec,message",
    [
        ("warn:100k", "unknown budget key"),
        ("warning:lots", "is not a number"),
        ("warning:0", "must be positive"),
        ("warning:200k,critical:150k", "must be below critical"),
    ],
)
def test_parse_budget_rejects_bad_specs(spec, message):
    """A budget the user thought they set but did not is worse than none."""
    with pytest.raises(ValueError, match=message):
        parse_budget(spec)


# --- threshold tracking ---------------------------------------------------


def _stats_with_curve(values: list[int]) -> SessionStats:
    stats = SessionStats(agent="claude-code", session_key="curve")
    for value in values:
        stats.turns += 1
        stats.sample_context(value)
    return stats


def test_thresholds_report_the_first_crossing():
    stats = _stats_with_curve([10_000, 90_000, 120_000, 130_000, 160_000, 170_000])
    tracked = context_budget(stats, {"warning": 100_000, "critical": 150_000})

    assert tracked["warning_turn"] == 3
    assert tracked["critical_turn"] == 5
    assert tracked["peak_prompt_tokens"] == 170_000
    assert tracked["final_prompt_tokens"] == 170_000
    assert [e["level"] for e in tracked["curve"]] == [
        "ok", "ok", "warning", "warning", "critical", "critical",
    ]


def test_biggest_jump_ignores_the_first_sample():
    """Turn 1's delta is the session preamble; no tool caused it."""
    stats = _stats_with_curve([50_000, 60_000, 90_000])
    tracked = context_budget(stats)

    assert tracked["biggest_jump"]["turn"] == 3
    assert tracked["biggest_jump"]["delta"] == 30_000


def test_compaction_shows_as_a_negative_delta_and_never_wins():
    stats = _stats_with_curve([100_000, 120_000, 20_000, 30_000])
    tracked = context_budget(stats)

    assert tracked["curve"][2]["delta"] == -100_000
    assert tracked["biggest_jump"]["delta"] == 20_000


def test_budget_is_absent_without_a_curve():
    assert context_budget(SessionStats(agent="x", session_key="y")) is None


def test_analyze_reports_budget_and_report_renders_it():
    stats = _stats_with_curve([10_000, 160_000])
    signals = analyze(stats, {"warning": 100_000, "critical": 150_000})

    assert signals["context_budget"]["critical_turn"] == 2
    joined = " ".join(signals["recommendations"])
    assert "critical budget" in joined

    rendered = format_analyze(stats, signals)
    assert "Context budget: warning 100K | critical 150K" in rendered
    assert "[critical]" in rendered
