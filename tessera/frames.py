"""The frame bridge: raw RGBA in, Views out.

Tessera writes PNG but does not read it, and adding a decoder to talk to Blender
would be the wrong forty lines — Blender already has one. So the capture side
renders, loads the result with Blender's own loader, and writes a flat float
buffer that both ends agree on. No decoder, no dependency, no format guessing.

  magic  b"TSF1"
  uint32 width, height, count
  then, per view: uint32 yaw_index, frame_index; float32 yaw_degrees;
                  uint32 frame_number; then width*height*4 float32 RGBA, TOP-DOWN

Top-down is stated because Blender's image buffers are bottom-up and a silently
flipped sprite sheet is the kind of bug that survives review — every frame looks
plausible on its own, and only the shadow being on the wrong side gives it away.
"""

from __future__ import annotations

import struct
from array import array
from pathlib import Path

MAGIC = b"TSF1"
_HEAD = struct.Struct("<4sIII")
# frame_number is SIGNED: Blender actions may start before frame 0, and a
# crocodile death animation in this library does. Packing it unsigned raised
# struct.error mid-write, leaving a 16-byte header and no frames.
_VIEW = struct.Struct("<IIfi")


def write_frames(path: str | Path, width: int, height: int, views) -> Path:
    """views: iterable of (yaw_index, frame_index, yaw_degrees, frame_number, rgba)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    views = list(views)
    with path.open("wb") as fh:
        fh.write(_HEAD.pack(MAGIC, width, height, len(views)))
        for yaw_index, frame_index, yaw_degrees, frame_number, rgba in views:
            if len(rgba) != width * height * 4:
                raise ValueError(f"view {yaw_index}/{frame_index} has {len(rgba)} values, "
                                 f"expected {width * height * 4}")
            fh.write(_VIEW.pack(yaw_index, frame_index, float(yaw_degrees), frame_number))
            array("f", rgba).tofile(fh)
    return path


def read_views(path: str | Path):
    """Returns a list of tessera.sheet.View, ready to pack."""
    from .sheet import View
    path = Path(path)
    with path.open("rb") as fh:
        magic, width, height, count = _HEAD.unpack(fh.read(_HEAD.size))
        if magic != MAGIC:
            raise ValueError(f"{path} is not a Tessera frame file")
        out = []
        for _ in range(count):
            yaw_index, frame_index, yaw_degrees, frame_number = _VIEW.unpack(fh.read(_VIEW.size))
            buf = array("f")
            buf.fromfile(fh, width * height * 4)
            out.append(View(buf.tolist(), width, height, yaw_index=yaw_index,
                            frame_index=frame_index, yaw_degrees=yaw_degrees,
                            frame_number=frame_number))
    return out
