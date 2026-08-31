"""The sheet driver — the one piece of Tessera that did not already exist.

The kernel turns ONE image into a glyph grid. A sprite sheet is many images that
have to agree with each other, and the agreement is the whole product: a walk
cycle whose feet wander by a cell reads as a limp, and eight directions at eight
different scales cannot be flipped through at all.

So this module does not simply convert frames and lay them out. It measures every
converted frame, finds one cell size that every frame fits inside, and places each
frame so that its ANCHOR — not its bounding box, not the image centre — lands on
the same point of every cell. The uniform cell and the stable anchor are the two
invariants a game engine actually consumes, and both are asserted in the tests.

Placement is in whole cells on purpose. A glyph cell is the unit of art here, and
half-cell placement would smear a sprite across the pixel grid it was quantised
onto. Sub-cell precision is preserved where it is useful instead: the metadata
records each anchor in PIXELS as a float, so an engine can position exactly even
though the art itself is cell-aligned.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from typing import Iterable, Sequence

from .kernel_link import open_kernel

ANCHORS = ("center", "bottom", "feet")
FILL_MODES = ("solid", "tone")
LAYOUTS = ("direction_rows", "frame_rows")


@dataclass(frozen=True)
class View:
    """One rendered look at the subject, before the kernel sees it."""
    pixels: Sequence[float]          # RGBA, 0..1, row-major
    width: int
    height: int
    yaw_index: int = 0               # which direction column/row this belongs to
    frame_index: int = 0             # which animation frame
    yaw_degrees: float = 0.0         # recorded for the sidecar, not used in layout
    frame_number: int = 0            # the host's own frame id, ditto
    mask: Sequence[float] | None = None


@dataclass(frozen=True)
class BBox:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int: return self.x + self.w

    @property
    def bottom(self) -> int: return self.y + self.h


@dataclass(frozen=True)
class Placed:
    view: View
    frame: object                    # kernel GlyphFrame
    bbox: BBox | None                # None when the frame converted to nothing
    anchor: tuple[float, float]      # cell units, in the converted frame's own space
    col: int
    row: int
    origin: tuple[int, int]          # top-left of this frame's bbox inside its sheet cell


def sprite_settings(bundle, **overrides):
    """The sprite preset, and the reasoning for every value that differs from stock.

    KernelSettings ships tuned for the look ASCII Studio sells inside a DCC: a
    lit, bloomed, faintly scanlined CRT. Those defaults are actively wrong for a
    sprite, so this preset turns the screen off and leaves the quantiser on.

    cell_aspect is the one that matters most and the easiest to get wrong. The
    kernel derives row count as `H/W * columns * cell_aspect`, and the stock 0.5
    is correct for a TERMINAL, whose cells are about twice as tall as they are
    wide. A sprite is emitted as square pixels through a 5x7 cell, so preserving
    the subject's real proportions requires cell_width/cell_height. Left at 0.5,
    every sprite comes out squashed vertically by (5/7)/0.5 = 1.43x — which reads
    as a modelling error rather than a settings error, and gets debugged as one.
    """
    kernel = bundle.kernel
    base = dict(
        # The vocabulary must follow the tile set. KernelSettings.glyphs defaults
        # to the ASCII ramp, so leaving it alone made every non-text tile set fail
        # its own allowed-glyph check — caught by the default-output test, not by
        # reading the code.
        glyphs="".join(kernel.chars),
        color_mode="SOURCE",                 # the creator's rule: colour comes from the model
        background=(0, 0, 0, 0),             # transparent, so a sprite is a cutout
        cell_aspect=kernel.cell_width / kernel.cell_height,
        structure_strength=0.7,              # KEPT: this is the silhouette-preserving route
        shadow_strength=0.0,                 # screen-look effects, all off
        bloom_strength=0.0,
        scanline_strength=0.0,
        vignette_strength=0.0,
        chromatic_strength=0.0,
        grain_strength=0.0,
        density=1.0,                         # no dropout by default; patterns opt in
        jitter=0.0,                          # deterministic by default
    )
    base.update(overrides)
    return bundle.Settings(**base)


def occupancy(view: View) -> list[float]:
    """The same silhouette, painted white — a luminance carrier, nothing more."""
    px = view.pixels
    out = [0.0] * len(px)
    for i in range(0, len(px), 4):
        if px[i + 3] > 0.0:
            out[i:i + 4] = [px[i + 3]] * 4
    return out


def alpha_channel(view: View) -> list[float]:
    return [view.pixels[i * 4 + 3] for i in range(view.width * view.height)]


def convert(bundle, settings, view: View, fill_mode: str):
    """One converted frame, with coverage and colour decided by different rules.

    The kernel maps LUMINANCE to glyph coverage. For ASCII art that is exactly
    right: you are reproducing tone using marks on a fixed background, so a dark
    region must be reproduced with a sparse mark. For a sprite it is exactly
    wrong. A red torso has a rec709 luminance around 0.37, so tone-driven
    selection can never choose a solid tile for it no matter how opaque the model
    is, and the sprite comes out dotted — which reads as a dithering bug rather
    than as the intended behaviour it actually is.

    `solid` therefore runs the kernel twice and takes one property from each pass.
    The SHAPE pass sees the silhouette painted white, so coverage tracks how much
    of the cell the model actually occupies, and a partially covered edge cell
    still gets the quadrant tile whose shape matches its edge. The COLOUR pass
    sees the real pixels, masked by alpha so that transparent neighbours cannot
    drag an edge cell's colour toward black. Neither pass modifies the kernel;
    both are ordinary calls, and the fingerprint is untouched.

    `tone` keeps the stock behaviour for anyone who wants the ASCII-art look.
    """
    kernel = bundle.kernel
    colour = kernel.convert_rgba(view.pixels, view.width, view.height, settings,
                                 view.mask if view.mask is not None else alpha_channel(view))
    if fill_mode == "tone":
        return colour
    shape = kernel.convert_rgba(occupancy(view), view.width, view.height, settings, view.mask)
    cells = tuple(
        bundle.GlyphCell(s.glyph, c.foreground, c.background, s.luminance)
        for s, c in zip(shape.cells, colour.cells)
    )
    return bundle.GlyphFrame(colour.width, colour.height, cells,
                             colour.kernel_version, colour.source_hash)


def is_ink(bundle, cell) -> bool:
    """Does this cell carry subject, as opposed to nothing?

    Two conditions, because either alone is wrong. A cell whose foreground is
    fully transparent drew nothing regardless of which glyph was chosen; a cell
    holding the blank glyph drew nothing regardless of how opaque it was.
    """
    return cell.foreground[3] > 0 and bundle.kernel.chars[cell.glyph] != " "


def content_bbox(bundle, frame) -> BBox | None:
    """Tight bounds of the subject in cell units, or None for an empty frame."""
    xs_min = ys_min = math.inf
    xs_max = ys_max = -math.inf
    for y in range(frame.height):
        row = y * frame.width
        for x in range(frame.width):
            if is_ink(bundle, frame.cells[row + x]):
                xs_min = min(xs_min, x); xs_max = max(xs_max, x)
                ys_min = min(ys_min, y); ys_max = max(ys_max, y)
    if xs_max < 0:
        return None
    return BBox(int(xs_min), int(ys_min), int(xs_max - xs_min + 1), int(ys_max - ys_min + 1))


def anchor_of(bundle, frame, bbox: BBox, mode: str) -> tuple[float, float]:
    """Where this frame should be pinned. Cell units, in the frame's own space.

    `bottom` and `feet` are deliberately not the same thing. `bottom` is the
    horizontal centre of the bounding box at its lowest edge — right for a prop.
    `feet` is the centroid of whatever ink actually occupies that lowest row —
    right for a character, because a walk cycle leans, and pinning a leaning body
    by its box centre slides the contact point out from under it.
    """
    if mode not in ANCHORS:
        raise ValueError(f"anchor must be one of {ANCHORS}")
    cx = bbox.x + bbox.w / 2.0
    if mode == "center":
        return (cx, bbox.y + bbox.h / 2.0)
    if mode == "bottom":
        return (cx, float(bbox.bottom))
    lowest = bbox.bottom - 1
    row = lowest * frame.width
    inked = [x for x in range(bbox.x, bbox.right) if is_ink(bundle, frame.cells[row + x])]
    centre = (sum(inked) / len(inked) + 0.5) if inked else cx
    return (centre, float(bbox.bottom))


def _grid(views: Sequence[View], layout: str) -> tuple[int, int, dict]:
    yaws = sorted({v.yaw_index for v in views})
    frames = sorted({v.frame_index for v in views})
    if layout == "direction_rows":
        rows, cols = len(yaws), len(frames)
        slot = {(y, f): (yaws.index(y), frames.index(f)) for y in yaws for f in frames}
    elif layout == "frame_rows":
        rows, cols = len(frames), len(yaws)
        slot = {(y, f): (frames.index(f), yaws.index(y)) for y in yaws for f in frames}
    else:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    return rows, cols, slot


def build_sheet(views: Sequence[View], *, bundle=None, settings=None,
                anchor: str = "feet", layout: str = "direction_rows",
                padding: int = 1, scale: int = 1, fill_mode: str = "solid"):
    """Convert, measure, align and pack. Returns (width, height, pixels, metadata)."""
    if not views:
        raise ValueError("no views to pack")
    if fill_mode not in FILL_MODES:
        raise ValueError(f"fill_mode must be one of {FILL_MODES}")
    if bundle is None:
        from .tilesets import DEFAULT_TILESET, load
        bundle = load(DEFAULT_TILESET)      # pixel by default; text is opt-in
    settings = settings or sprite_settings(bundle)
    kernel = bundle.kernel

    converted = []
    for view in views:
        frame = convert(bundle, settings, view, fill_mode)
        bbox = content_bbox(bundle, frame)
        converted.append((view, frame, bbox))

    # One cell size for every frame. Measured from the anchor OUTWARD rather than
    # from the bounding boxes, because it is the anchor that has to coincide: two
    # frames of equal size whose anchors sit at different heights still need
    # different room above and below.
    left = right = top = bottom = 0.0
    for view, frame, bbox in converted:
        if bbox is None:
            continue
        ax, ay = anchor_of(bundle, frame, bbox, anchor)
        left = max(left, ax - bbox.x)
        right = max(right, bbox.right - ax)
        top = max(top, ay - bbox.y)
        bottom = max(bottom, bbox.bottom - ay)

    cell_w = int(math.ceil(left) + math.ceil(right)) + 2 * padding
    cell_h = int(math.ceil(top) + math.ceil(bottom)) + 2 * padding
    cell_w = max(cell_w, 1)
    cell_h = max(cell_h, 1)
    anchor_x = int(math.ceil(left)) + padding
    anchor_y = int(math.ceil(top)) + padding

    rows, cols, slot = _grid(views, layout)
    placed: list[Placed] = []
    for view, frame, bbox in converted:
        r, c = slot[(view.yaw_index, view.frame_index)]
        if bbox is None:
            placed.append(Placed(view, frame, None, (0.0, 0.0), c, r, (0, 0)))
            continue
        ax, ay = anchor_of(bundle, frame, bbox, anchor)
        ox = anchor_x - int(round(ax - bbox.x))
        oy = anchor_y - int(round(ay - bbox.y))
        placed.append(Placed(view, frame, bbox, (ax, ay), c, r, (ox, oy)))

    # Compose ONE glyph frame the size of the whole sheet, then render once. The
    # alternative — render each frame and blit the pixels — would run every
    # post-effect per tile and seam them together at the tile edges.
    sheet_w, sheet_h = cols * cell_w, rows * cell_h
    empty = bundle.GlyphCell(0, (0, 0, 0, 0), (0, 0, 0, 0), 0.0)
    cells = [empty] * (sheet_w * sheet_h)
    for p in placed:
        if p.bbox is None:
            continue
        base_x = p.col * cell_w + p.origin[0]
        base_y = p.row * cell_h + p.origin[1]
        for y in range(p.bbox.y, p.bbox.bottom):
            for x in range(p.bbox.x, p.bbox.right):
                cell = p.frame.cells[y * p.frame.width + x]
                if not is_ink(bundle, cell):
                    continue
                tx, ty = base_x + (x - p.bbox.x), base_y + (y - p.bbox.y)
                if 0 <= tx < sheet_w and 0 <= ty < sheet_h:
                    cells[ty * sheet_w + tx] = cell

    composite = bundle.GlyphFrame(sheet_w, sheet_h, tuple(cells), kernel.version,
                                  hashlib.sha256(b"tessera-sheet").hexdigest())
    width, height, pixels = kernel.render_rgba(composite, scale, settings)

    px_per_cell_x = kernel.cell_width * scale
    px_per_cell_y = kernel.cell_height * scale
    meta = {
        "schema": "com.astral.tessera.sheet/1",
        "kernel_version": kernel.version,
        "kernel_fingerprint": kernel.fingerprint,
        "anchor_mode": anchor,
        "fill_mode": fill_mode,
        "layout": layout,
        "scale": scale,
        "padding_cells": padding,
        "grid": {"rows": rows, "columns": cols},
        "cell": {"width_cells": cell_w, "height_cells": cell_h,
                 "width_px": cell_w * px_per_cell_x, "height_px": cell_h * px_per_cell_y,
                 "anchor_x_px": anchor_x * px_per_cell_x,
                 "anchor_y_px": anchor_y * px_per_cell_y},
        "sheet": {"width_px": width, "height_px": height},
        "frames": [
            {
                "row": p.row, "column": p.col,
                "yaw_index": p.view.yaw_index, "yaw_degrees": p.view.yaw_degrees,
                "frame_index": p.view.frame_index, "frame_number": p.view.frame_number,
                "empty": p.bbox is None,
                "x_px": p.col * cell_w * px_per_cell_x,
                "y_px": p.row * cell_h * px_per_cell_y,
                "bbox_px": None if p.bbox is None else {
                    "x": (p.col * cell_w + p.origin[0]) * px_per_cell_x,
                    "y": (p.row * cell_h + p.origin[1]) * px_per_cell_y,
                    "width": p.bbox.w * px_per_cell_x,
                    "height": p.bbox.h * px_per_cell_y,
                },
                # The anchor in pixels, as a float, so a host can position exactly
                # even though the art itself was placed on whole cells.
                "anchor_px": {
                    "x": (p.col * cell_w + anchor_x) * px_per_cell_x,
                    "y": (p.row * cell_h + anchor_y) * px_per_cell_y,
                },
            }
            for p in sorted(placed, key=lambda q: (q.row, q.col))
        ],
    }
    meta["content_digest"] = hashlib.sha256(
        json.dumps(meta, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return width, height, pixels, meta
