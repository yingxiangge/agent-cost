from __future__ import annotations

import base64
import json
import struct

from agent_cost.analyze import analyze
from agent_cost.media import estimate_image_tokens, image_dimensions
from agent_cost.parsers.claude import parse_claude_session
from agent_cost.report import format_analyze


def _png_b64(width: int, height: int, padding: int = 4000) -> str:
    header = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
    )
    return base64.b64encode(header + b"\x00" * padding).decode()


def _jpeg_b64(width: int, height: int, padding: int = 4000) -> str:
    # SOI, then an APP0 segment to skip over, then an SOF0 frame header.
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00" + b"\x00" * 9
    sof0 = b"\xff\xc0" + struct.pack(">H", 17) + b"\x08" + struct.pack(">HH", height, width)
    return base64.b64encode(b"\xff\xd8" + app0 + sof0 + b"\x00" * padding).decode()


def test_image_dimensions_read_png_and_jpeg_headers():
    assert image_dimensions(_png_b64(1080, 600)) == (1080, 600)
    assert image_dimensions(_jpeg_b64(840, 1280)) == (840, 1280)


def test_estimate_image_tokens_uses_pixels_and_caps():
    # 1080x600 = 648,000 px / 750 = 864 tokens, under the per-image ceiling.
    assert estimate_image_tokens(_png_b64(1080, 600)) == 864
    # A full 1080x1920 screenshot exceeds the ceiling and is clamped, not scaled
    # with its base64 length.
    assert estimate_image_tokens(_png_b64(1080, 1920)) == 1600
    # Unreadable payloads fall back to the ceiling rather than counting characters.
    assert estimate_image_tokens("!!!!") == 1600
    assert estimate_image_tokens("") == 1600


def _write_session(tmp_path, blocks):
    path = tmp_path / "session.jsonl"
    lines = [
        json.dumps({
            "type": "assistant",
            "message": {
                "model": "claude-opus-5",
                "content": [{"type": "tool_use", "id": "call_1", "name": "Read"}],
                "usage": {"input_tokens": 100, "output_tokens": 10},
            },
        }),
        json.dumps({
            "type": "user",
            "message": {"content": [
                {"type": "tool_result", "tool_use_id": "call_1", "content": blocks}
            ]},
        }),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_image_payload_is_not_counted_as_text_chars(tmp_path):
    data = _png_b64(1080, 1920, padding=300_000)
    assert len(data) > 400_000
    stats = parse_claude_session(_write_session(tmp_path, [
        {"type": "text", "text": "screenshot saved"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": data}},
    ]))

    entry = stats.tool_stats["Read"]
    # The base64 body must not inflate the character pools -- only the text block counts.
    assert entry["output_chars"] == len("screenshot saved")
    assert stats.source_chars["tool_output"] == len("screenshot saved")
    assert entry["images"] == 1
    assert entry["image_tokens"] == 1600
    assert stats.image_count == 1
    assert stats.image_tokens == 1600


def test_text_only_tool_results_are_unchanged(tmp_path):
    stats = parse_claude_session(_write_session(tmp_path, [
        {"type": "text", "text": "line one"},
        {"type": "text", "text": "line two"},
    ]))
    entry = stats.tool_stats["Read"]
    assert entry["output_chars"] == len("line one") + len("line two")
    assert entry["images"] == 0
    assert entry["image_tokens"] == 0
    assert stats.image_count == 0


def test_analyze_reports_images_separately(tmp_path):
    blocks = [{"type": "text", "text": "shot"}]
    for _ in range(8):
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": _png_b64(1080, 1920)},
        })
    stats = parse_claude_session(_write_session(tmp_path, blocks))
    signals = analyze(stats)

    summary = signals["image_summary"]
    assert summary["images"] == 8
    assert summary["image_tokens"] == 8 * 1600
    assert summary["tools"][0]["tool"] == "Read"

    read_row = next(i for i in signals["tool_breakdown"] if i["tool"] == "Read")
    assert read_row["images"] == 8
    assert read_row["output_chars"] == len("shot")

    recs = " ".join(signals["recommendations"])
    assert "Images are a major context source" in recs

    out = format_analyze(stats, signals)
    assert "Images: 8 attached, ~12,800 tokens" in out
    assert "+8 img" in out


def test_no_image_summary_when_session_has_no_images(tmp_path):
    stats = parse_claude_session(_write_session(tmp_path, [{"type": "text", "text": "plain"}]))
    signals = analyze(stats)
    assert signals["image_summary"] is None
    assert "Images:" not in format_analyze(stats, signals)
