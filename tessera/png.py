"""A PNG writer in the standard library, because the kernel earned it.

`ascii_studio/kernel.py` is 361 lines with no third-party imports, which is why
the same code runs inside Blender, inside a test, and on a bare machine. Reaching
for Pillow here to save forty lines would throw that away: Blender ships its own
Python, Unity ships none, and "install Pillow first" is how a tool stops being
usable in the places it was built to run.

PNG is well specified and the subset we need is small: one IHDR, one IDAT of
zlib-compressed scanlines each prefixed with a filter byte, one IEND. Filter 0
(None) is used throughout — filtering trades encode time for file size, and glyph
output is large flat runs that zlib already collapses well.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path
from typing import Sequence

_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def encode_rgba(width: int, height: int, pixels: Sequence[float]) -> bytes:
    """Encode float RGBA in 0..1 — the kernel's `render_rgba` output — as 8-bit PNG."""
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be positive")
    expected = width * height * 4
    if len(pixels) != expected:
        raise ValueError(f"expected {expected} channel values, got {len(pixels)}")

    raw = bytearray()
    row_bytes = width * 4
    for y in range(height):
        raw.append(0)                                   # filter: None
        start = y * row_bytes
        raw.extend(
            min(255, max(0, round(value * 255.0)))
            for value in pixels[start:start + row_bytes]
        )

    return b"".join((
        _SIGNATURE,
        # bit depth 8, colour type 6 (RGBA), deflate, adaptive filtering, no interlace
        _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
        _chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
        _chunk(b"IEND", b""),
    ))


def write_rgba(path: str | Path, width: int, height: int, pixels: Sequence[float]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_rgba(width, height, pixels))
    return path
