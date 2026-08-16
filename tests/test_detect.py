import json

from agent_cost.parsers.detect import load_path


def _write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records), encoding="utf-8")


def test_signature_after_the_first_15_lines_is_still_found(tmp_path):
    """A transcript's first assistant reply can be far past any fixed cutoff."""
    p = tmp_path / "late.jsonl"
    preamble = [{"type": "mode", "mode": "default"}] * 30
    _write(
        p,
        preamble
        + [
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-5",
                    "usage": {"input_tokens": 100, "output_tokens": 10,
                              "cache_read_input_tokens": 900},
                },
            }
        ],
    )
    sessions = load_path(p, warn=False)
    assert len(sessions) == 1
    assert sessions[0].agent == "claude-code"
    assert sessions[0].total_tokens == 1010


def test_empty_session_warns_on_stderr(tmp_path, capsys):
    p = tmp_path / "empty.jsonl"
    _write(p, [{"type": "mode", "mode": "default"}, {"type": "file-history-snapshot"}])
    load_path(p)
    err = capsys.readouterr().err
    assert "zero usage" in err
    assert "empty.jsonl" in err


def test_warning_can_be_suppressed(tmp_path, capsys):
    p = tmp_path / "empty.jsonl"
    _write(p, [{"type": "mode", "mode": "default"}])
    load_path(p, warn=False)
    assert capsys.readouterr().err == ""


def test_directory_scan_reports_every_empty_file(tmp_path, capsys):
    for i in range(4):
        _write(tmp_path / f"e{i}.jsonl", [{"type": "mode"}])
    load_path(tmp_path)
    err = capsys.readouterr().err
    assert "4 file(s) parsed to zero usage" in err
    assert "+1 more" in err
