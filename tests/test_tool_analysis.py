from __future__ import annotations

import json
from pathlib import Path

from agent_cost.analyze import analyze, classify_tool
from agent_cost.models import SessionStats
from agent_cost.parsers.claude import parse_claude_session
from agent_cost.parsers.codex import parse_codex_rollout
from agent_cost.parsers.opencode import parse_opencode_session, parse_opencode_sqlite
from agent_cost.report import format_analyze


def test_classify_tool_categories():
    # Shell / command
    assert classify_tool("bash")[0] == "shell"
    assert classify_tool("local_shell_call")[0] == "shell"
    assert classify_tool("exec_command")[0] == "shell"
    assert classify_tool("terminal")[0] == "shell"

    # File Read
    assert classify_tool("view_file")[0] == "file_read"
    assert classify_tool("read_file")[0] == "file_read"
    assert classify_tool("FileRead")[0] == "file_read"
    assert classify_tool("ReadNotebook")[0] == "file_read"

    # Search
    assert classify_tool("grep_search")[0] == "search"
    assert classify_tool("GrepTool")[0] == "search"
    assert classify_tool("find_by_name")[0] == "search"
    assert classify_tool("ripgrep")[0] == "search"
    assert classify_tool("rg")[0] == "search"

    # File Edit
    assert classify_tool("replace_file_content")[0] == "file_edit"
    assert classify_tool("FileEdit")[0] == "file_edit"
    assert classify_tool("file_writer")[0] == "file_edit"
    assert classify_tool("apply_patch")[0] == "file_edit"

    # Web
    assert classify_tool("read_url_content")[0] == "web"
    assert classify_tool("web_search")[0] == "web"
    assert classify_tool("browser")[0] == "web"

    # Subagent
    assert classify_tool("invoke_subagent")[0] == "subagent"
    assert classify_tool("manage_task")[0] == "subagent"

    # Other
    assert classify_tool("custom_metric_tool")[0] == "other"
    assert classify_tool("")[0] == "other"


def test_claude_parser_tool_attribution(tmp_path):
    log_file = tmp_path / "claude_tools.jsonl"
    lines = [
        json.dumps({"type": "user", "content": "run tests and check file"}),
        json.dumps({
            "type": "assistant",
            "usage": {"input_tokens": 100, "output_tokens": 50},
            "content": [
                {"type": "tool_use", "id": "call_1", "name": "Bash", "input": {"command": "pytest"}},
                {"type": "tool_use", "id": "call_2", "name": "view_file", "input": {"path": "main.py"}},
            ],
        }),
        json.dumps({
            "type": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": "FAILED 10 tests\n" * 100},
                {"type": "tool_result", "tool_use_id": "call_2", "content": "def main(): pass\n" * 20},
            ],
        }),
    ]
    log_file.write_text("\n".join(lines), encoding="utf-8")

    stats = parse_claude_session(log_file)
    assert stats.tool_calls == 2
    assert "Bash" in stats.tool_stats
    assert stats.tool_stats["Bash"]["calls"] == 1
    assert stats.tool_stats["Bash"]["output_chars"] > 1000

    assert "view_file" in stats.tool_stats
    assert stats.tool_stats["view_file"]["calls"] == 1
    assert stats.tool_stats["view_file"]["output_chars"] > 200

    signals = analyze(stats)
    assert len(signals["tool_breakdown"]) == 2
    assert signals["tool_breakdown"][0]["tool"] == "Bash"
    assert signals["tool_breakdown"][0]["category"] == "shell"

    # Check type-specific recommendations
    rec_text = " ".join(signals["recommendations"])
    assert "Shell/command output" in rec_text
    assert "head/tail/grep" in rec_text


def test_codex_parser_tool_attribution():
    stats = parse_codex_rollout(Path("examples/codex_rollout.sanitized.jsonl"))
    assert stats.tool_calls == 1
    assert "exec_command" in stats.tool_stats
    assert stats.tool_stats["exec_command"]["calls"] == 1
    assert stats.tool_stats["exec_command"]["output_chars"] > 0

    signals = analyze(stats)
    assert len(signals["tool_breakdown"]) == 1
    assert signals["tool_breakdown"][0]["category"] == "shell"

    text = format_analyze(stats, signals)
    assert "Tool output breakdown:" in text
    assert "exec_command" in text
    assert "[Shell / Command]" in text


def test_type_specific_recommendations():
    # 1. File read heavy session
    stats_read = SessionStats(agent="test-agent", session_key="s1")
    stats_read.record_tool_call("view_file")
    stats_read.record_tool_output("view_file", 50000)
    stats_read.source_chars["user"] = 1000

    signals_read = analyze(stats_read)
    rec_text_read = " ".join(signals_read["recommendations"])
    assert "File read output" in rec_text_read
    assert "windowed reads" in rec_text_read

    # 2. Search / grep heavy session
    stats_search = SessionStats(agent="test-agent", session_key="s2")
    stats_search.record_tool_call("grep_search")
    stats_search.record_tool_output("grep_search", 40000)
    stats_search.source_chars["user"] = 1000

    signals_search = analyze(stats_search)
    rec_text_search = " ".join(signals_search["recommendations"])
    assert "Search/grep output" in rec_text_search
    assert "narrow search paths" in rec_text_search

    # 3. Web / browser heavy session
    stats_web = SessionStats(agent="test-agent", session_key="s3")
    stats_web.record_tool_call("read_url_content")
    stats_web.record_tool_output("read_url_content", 60000)
    stats_web.source_chars["user"] = 1000

    signals_web = analyze(stats_web)
    rec_text_web = " ".join(signals_web["recommendations"])
    assert "Web/browser output" in rec_text_web
    assert "markdown text" in rec_text_web

    # 4. High call frequency check
    stats_freq = SessionStats(agent="test-agent", session_key="s4")
    for _ in range(15):
        stats_freq.record_tool_call("check_status")
        stats_freq.record_tool_output("check_status", 50)
    signals_freq = analyze(stats_freq)
    rec_text_freq = " ".join(signals_freq["recommendations"])
    assert "High call frequency for 'check_status'" in rec_text_freq

    # 5. File edit heavy session
    stats_edit = SessionStats(agent="test-agent", session_key="s5")
    stats_edit.record_tool_call("file_writer")
    stats_edit.record_tool_output("file_writer", 80000)
    stats_edit.source_chars["user"] = 1000
    signals_edit = analyze(stats_edit)
    rec_text_edit = " ".join(signals_edit["recommendations"])
    assert "File edit output" in rec_text_edit
    assert "targeted diff/patch replacements" in rec_text_edit

    # 6. Subagent heavy session
    stats_sub = SessionStats(agent="test-agent", session_key="s6")
    stats_sub.record_tool_call("invoke_subagent")
    stats_sub.record_tool_output("invoke_subagent", 90000)
    stats_sub.source_chars["user"] = 1000
    signals_sub = analyze(stats_sub)
    rec_text_sub = " ".join(signals_sub["recommendations"])
    assert "Subagent output" in rec_text_sub
    assert "concise structured findings" in rec_text_sub


def test_analyze_reports_repeated_file_reads_and_exact_output_duplicates():
    stats = SessionStats(agent="test-agent", session_key="repeated")
    for _ in range(3):
        stats.record_tool_call("view_file", input_value={"path": "src/main.py"})
        stats.record_tool_output("view_file", 1200, content="same file contents")
    stats.record_tool_call("bash", input_value={"command": "pytest -q"})
    stats.record_tool_output("bash", 800, content="FAILED test_example\n")
    stats.record_tool_call("bash", input_value={"command": "pytest -q"})
    stats.record_tool_output("bash", 800, content="FAILED test_example\n")

    signals = analyze(stats)

    assert signals["repeated_file_reads"] == [{"path": "src/main.py", "reads": 3}]
    assert signals["repeated_tool_output"] == [
        {
            "tool": "view_file",
            "calls": 3,
            "total_chars": 3600,
            "unique_chars": 1200,
            "repeated_chars": 2400,
            "duplicate_calls": 2,
        },
        {
            "tool": "bash",
            "calls": 2,
            "total_chars": 1600,
            "unique_chars": 800,
            "repeated_chars": 800,
            "duplicate_calls": 1,
        },
    ]
    rec_text = " ".join(signals["recommendations"])
    assert "src/main.py" in rec_text
    assert "Repeated output from 'view_file'" in rec_text


def test_format_analyze_includes_repetition_breakdown():
    stats = SessionStats(agent="test-agent", session_key="repeated")
    stats.record_tool_call("view_file", input_value={"path": "README.md"})
    stats.record_tool_call("view_file", input_value={"path": "README.md"})
    stats.record_tool_output("view_file", 10, content="same")
    stats.record_tool_output("view_file", 10, content="same")

    text = format_analyze(stats, analyze(stats))

    assert "Repeated file reads:" in text
    assert "README.md  2 reads" in text
    assert "Repeated tool output:" in text


def test_opencode_parser_tool_attribution(tmp_path):
    log_file = tmp_path / "opencode_tools.json"
    data = {
        "session_id": "opencode-tool-test",
        "agent": "opencode",
        "steps": [
            {
                "type": "tool_call",
                "tool": "ripgrep",
                "usage": {"prompt_tokens": 100, "completion_tokens": 20},
            },
            {
                "type": "tool_result",
                "tool": "ripgrep",
                "result": "match 1\nmatch 2\n" * 50,
            },
            {
                "type": "tool_call",
                "tool": "file_writer",
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            },
            {
                "type": "tool_result",
                "tool": "file_writer",
                "result": "file updated",
            },
        ],
    }
    log_file.write_text(json.dumps(data), encoding="utf-8")

    stats = parse_opencode_session(log_file)
    assert stats.tool_calls == 2
    assert "ripgrep" in stats.tool_stats
    assert stats.tool_stats["ripgrep"]["calls"] == 1
    assert stats.tool_stats["ripgrep"]["output_chars"] > 500

    assert "file_writer" in stats.tool_stats
    assert stats.tool_stats["file_writer"]["calls"] == 1
    assert stats.tool_stats["file_writer"]["output_chars"] > 0

    signals = analyze(stats)
    assert len(signals["tool_breakdown"]) == 2
    assert signals["tool_breakdown"][0]["tool"] == "ripgrep"
    assert signals["tool_breakdown"][0]["category"] == "search"
    assert "Search/grep output" in " ".join(signals["recommendations"])


def test_analyze_survives_empty_source_chars():
    """Tool fingerprints without source_chars must not crash analyze().

    `ranked` used to be defined only when source_chars was non-empty, while
    step 3 read it unconditionally: a session carrying tool output but no
    source breakdown raised UnboundLocalError.
    """
    stats = SessionStats(agent="claude-code", session_key="empty-sources")
    stats.record_tool_output("Bash", 100, content="x")
    stats.source_chars.clear()

    signals = analyze(stats)

    assert signals["largest_sources"] == []
    assert signals["tool_breakdown"][0]["tool"] == "Bash"


def test_repeated_output_totals_are_per_tool():
    """`total_chars` on a repeated-output row counts that tool alone.

    The loop variable used to shadow the session-wide source character total,
    which then decided whether tool output "dominates" the context.
    """
    stats = SessionStats(agent="claude-code", session_key="repeat")
    for _ in range(3):
        stats.record_tool_output("Bash", 300, content="same-output")
    stats.record_tool_output("Read", 50, content="unique")

    signals = analyze(stats)
    rows = {row["tool"]: row for row in signals["repeated_tool_output"]}

    assert rows["Bash"]["total_chars"] == 900
    assert rows["Bash"]["unique_chars"] == 300
    assert rows["Bash"]["repeated_chars"] == 600
    assert "Read" not in rows
