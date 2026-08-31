"""Tile sets and palettes — the answer to "it doesn't always have to be text".

A tile set is a kernel payload. That is the whole trick and it is worth stating
plainly, because it is what makes this product cheap to extend: the kernel never
rasterises a font, it reads each tile as a bitmap out of `kernel.json`. Glyphs
were only ever one choice of bitmap. Swapping them for colour blocks needed no
code, and swapping them for anything else will not either.

Three sets ship, and they are genuinely different tools rather than three looks:

  text-ramp       5x7, 10 glyphs. The canonical ASCII kernel, byte-identical to
                  the one ASCII, ASCII Studio for Blender and ASCII Studio for
                  Unity all carry. Kept because a release is invalid if it drifts.

  quadrant-block  4x4, 16 tiles. Solid and half/quarter blocks. Reads as chunky
                  pixel art, and the four distinct shapes at each coverage level
                  are what let the structural route keep a silhouette edge sharp.

  pixel-hd        2x2, all 16 patterns. This is the high-definition mode, and it
                  is high definition in a precise sense rather than a marketing
                  one: with a 2x2 cell there are exactly 2^4 possible ink
                  patterns, and all sixteen are present, so the tile vocabulary
                  can represent ANY binary sub-cell mask exactly. Silhouette
                  reproduction is lossless; only colour remains per-cell.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Tessera's default is PIXEL, not text. The kernel came out of a glyph engine, so
# the text ramp is the vocabulary it inherits — but a sprite generator whose
# out-of-the-box output looks like ASCII art has picked a style on the user's
# behalf. Text is one tile set among several and it is opt-in.
DEFAULT_TILESET = "pixel-hd"

# Quality is cell DENSITY, which is why it is expressed as columns rather than as
# an output scale. Scaling a coarse sheet up just makes big blocks; more columns
# is more sprite. At the pixel-hd cell of 2x2, columns = source_width / 2 samples
# every source pixel exactly once, so that is the point past which more columns
# only oversamples what is already there.
QUALITY = {"draft": 0.25, "standard": 0.5, "high": 1.0}


def columns_for(source_width: int, quality: str = "standard", cell_width: int = 2) -> int:
    if quality not in QUALITY:
        raise ValueError(f"quality must be one of {sorted(QUALITY)}")
    ceiling = max(8, source_width // cell_width)
    return max(8, min(1024, round(ceiling * QUALITY[quality])))


TILESETS = Path(__file__).resolve().parent.parent / "assets" / "tilesets"
CANONICAL = Path(__file__).resolve().parent.parent / "assets" / "kernel.json"

# Blocks in reading order for the 2x2 set: bit 3 = top-left, 0 = bottom-right.
_QUAD_CHARS = " ▗▖▄▝▐▞▟▘▚▌▙▀▜▛█"

# Named palettes for PALETTE colour mode. Dark to light, which is the order the
# kernel's ordered dither expects. Two to six entries, per its own validator.
PALETTES = {
    "ink":     [(18, 18, 22, 255), (72, 76, 88, 255), (146, 152, 168, 255), (226, 230, 238, 255)],
    "gameboy": [(15, 56, 15, 255), (48, 98, 48, 255), (139, 172, 15, 255), (155, 188, 15, 255)],
    "ember":   [(26, 14, 18, 255), (110, 34, 40, 255), (204, 90, 52, 255), (247, 190, 116, 255)],
    "cold":    [(14, 20, 34, 255), (38, 70, 110, 255), (92, 148, 196, 255), (206, 232, 246, 255)],
}


def _payload(name: str, cell: int, chars: str, rows_for) -> dict:
    return {
        "schema": "com.astral.ascii.kernel/1",
        "version": "1.0.0",
        "name": name,
        "cell_width": cell,
        "cell_height": cell,
        "luminance": "rec709",
        "glyphs": [{"char": c, "rows": rows_for(i)} for i, c in enumerate(chars)],
        "defaults": {"columns": 96, "cell_aspect": 1.0, "gamma": 1.0, "contrast": 1.0,
                     "structure_strength": 0.7, "edge_threshold": 0.08, "invert": False,
                     "background": [0, 0, 0, 0]},
    }


def build_pixel_hd() -> dict:
    """All sixteen 2x2 patterns. Index IS the pattern, so nothing is missing."""
    def rows_for(i: int) -> list[int]:
        return [((i >> 3) & 1) << 1 | ((i >> 2) & 1),
                ((i >> 1) & 1) << 1 | (i & 1)]
    return _payload("Tessera Pixel HD", 2, _QUAD_CHARS, rows_for)


def fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def ensure_generated() -> Path:
    TILESETS.mkdir(parents=True, exist_ok=True)
    path = TILESETS / "pixel-hd.kernel.json"
    payload = build_pixel_hd()
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")
    return path


def available() -> dict[str, Path]:
    ensure_generated()
    sets = {"text-ramp": CANONICAL}
    for path in sorted(TILESETS.glob("*.kernel.json")):
        sets[path.name.replace(".kernel.json", "")] = path
    return sets


def load(name: str):
    """Open a bundle on a named tile set, with the divergence gate kept for the canonical one."""
    from .kernel_link import open_kernel, load_kernel_module, KernelBundle
    sets = available()
    if name not in sets:
        raise ValueError(f"unknown tile set {name!r}; have {sorted(sets)}")
    if name == "text-ramp":
        return open_kernel()                    # the shared kernel, gate enforced
    module = load_kernel_module()
    return KernelBundle(module, module.AsciiKernel(sets[name]))
