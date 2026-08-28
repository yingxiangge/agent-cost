from __future__ import annotations

import base64
import struct

# Anthropic prices an image at roughly (width x height) / 750 tokens, capped by the
# 1568px long-edge downscale the API applies before counting.
_PIXELS_PER_TOKEN = 750
_MAX_IMAGE_TOKENS = 1600


def _png_size(data: bytes) -> tuple[int, int] | None:
    # 8-byte signature, 4-byte chunk length, b"IHDR", then width and height.
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def _jpeg_size(data: bytes) -> tuple[int, int] | None:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        # SOF0-SOF15 carry the frame size; SOF4/SOF8/SOF12 are not frame markers.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        segment_length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if segment_length < 2:
            return None
        i += 2 + segment_length
    return None


def image_dimensions(b64_data: str, prefix_chars: int = 8192) -> tuple[int, int] | None:
    """Decode the head of a base64 payload and read the image's pixel dimensions.

    Only the prefix is decoded: PNG carries the size in the first 24 bytes and
    JPEG within the first few KB, so the multi-MB body never has to be decoded.
    """
    head = str(b64_data or "")[: prefix_chars - (prefix_chars % 4)]
    if not head:
        return None
    try:
        raw = base64.b64decode(head, validate=False)
    except (ValueError, TypeError):
        return None
    return _png_size(raw) or _jpeg_size(raw)


def estimate_image_tokens(b64_data: str) -> int:
    """Estimate the context tokens an image occupies.

    Falls back to the per-image ceiling when the format is unreadable, because
    under-counting an image is what made base64 look like file-read text.
    """
    size = image_dimensions(b64_data)
    if not size:
        return _MAX_IMAGE_TOKENS
    width, height = size
    if width <= 0 or height <= 0:
        return _MAX_IMAGE_TOKENS
    return max(1, min(_MAX_IMAGE_TOKENS, round(width * height / _PIXELS_PER_TOKEN)))
