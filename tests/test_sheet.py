"""Tests for the sheet driver.

Every fixture here is synthetic and labelled as such. That is deliberate: the
properties under test are geometric invariants — one cell size, one anchor point,
determinism, transparency — and a synthetic subject whose exact position is known
can prove them, where a real render could only fail to contradict them.

Two of these tests re-introduce the bug they guard against (the squashed aspect,
and a subject that moves inside its own frame) so that a guard which stopped
inspecting anything would be caught rather than staying green.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tessera.kernel_link import open_kernel, canonical_fingerprint, KERNEL_JSON, GOLDEN_VECTOR
from tessera.png import encode_rgba
from tessera.sheet import (View, build_sheet, sprite_settings, content_bbox, anchor_of)
import json


def blank(w: int, h: int) -> list[float]:
    return [0.0] * (w * h * 4)


def box(pixels, w, x0, y0, bw, bh, rgb=(1.0, 0.25, 0.25)):
    """Paint an opaque rectangle. The synthetic 'model'."""
    for y in range(y0, y0 + bh):
        for x in range(x0, x0 + bw):
            o = (y * w + x) * 4
            pixels[o:o + 4] = [*rgb, 1.0]
    return pixels


def subject(w=48, h=48, x0=18, y0=10, bw=12, bh=28, rgb=(1.0, 0.25, 0.25)):
    return box(blank(w, h), w, x0, y0, bw, bh, rgb)


class KernelGate(unittest.TestCase):
    def test_payload_matches_kernel_and_golden_vector(self):
        bundle = open_kernel()
        payload = json.loads(KERNEL_JSON.read_text())
        self.assertEqual(bundle.kernel.fingerprint, canonical_fingerprint(payload))
        golden = json.loads(GOLDEN_VECTOR.read_text())
        self.assertEqual(golden["kernel_fingerprint"], bundle.kernel.fingerprint)


class Aspect(unittest.TestCase):
    def test_sprite_preset_preserves_source_aspect(self):
        bundle = open_kernel()
        k = bundle.kernel
        s = sprite_settings(bundle, columns=24)
        self.assertAlmostEqual(s.cell_aspect, k.cell_width / k.cell_height)
        px = subject(64, 64)
        frame = k.convert_rgba(px, 64, 64, s)
        out_aspect = (frame.height * k.cell_height) / (frame.width * k.cell_width)
        self.assertAlmostEqual(out_aspect, 1.0, delta=0.06)

    def test_stock_cell_aspect_would_squash_it(self):
        # Re-introduce the bug: the terminal default really does distort a sprite,
        # so the preset above is load-bearing rather than decoration.
        bundle = open_kernel()
        k = bundle.kernel
        stock = bundle.Settings(columns=24)          # cell_aspect 0.5
        self.assertEqual(stock.cell_aspect, 0.5)
        frame = k.convert_rgba(subject(64, 64), 64, 64, stock)
        out_aspect = (frame.height * k.cell_height) / (frame.width * k.cell_width)
        self.assertLess(out_aspect, 0.85)


class Invariants(unittest.TestCase):
    def setUp(self):
        self.bundle = open_kernel()
        self.settings = sprite_settings(self.bundle, columns=20)

    def views_at_different_heights(self):
        # Same subject, different position inside its own frame. A driver that
        # packs by image centre puts these at different heights; one that packs
        # by anchor does not.
        return [
            View(subject(48, 48, 18, 6, 10, 26), 48, 48, yaw_index=0, frame_index=0),
            View(subject(48, 48, 22, 16, 10, 26), 48, 48, yaw_index=0, frame_index=1),
        ]

    def test_anchor_lands_on_the_same_pixel_for_every_frame(self):
        w, h, px, meta = build_sheet(self.views_at_different_heights(),
                                     bundle=self.bundle, settings=self.settings,
                                     anchor="feet", layout="frame_rows")
        xs = {f["anchor_px"]["x"] - f["x_px"] for f in meta["frames"]}
        ys = {f["anchor_px"]["y"] - f["y_px"] for f in meta["frames"]}
        self.assertEqual(len(xs), 1, f"anchor x drifted between frames: {xs}")
        self.assertEqual(len(ys), 1, f"anchor y drifted between frames: {ys}")

    def test_every_frame_gets_the_same_cell(self):
        w, h, px, meta = build_sheet(self.views_at_different_heights(),
                                     bundle=self.bundle, settings=self.settings)
        cw, ch = meta["cell"]["width_px"], meta["cell"]["height_px"]
        self.assertEqual(w, meta["grid"]["columns"] * cw)
        self.assertEqual(h, meta["grid"]["rows"] * ch)

    def test_subject_fits_inside_its_cell(self):
        w, h, px, meta = build_sheet(self.views_at_different_heights(),
                                     bundle=self.bundle, settings=self.settings)
        cw, ch = meta["cell"]["width_px"], meta["cell"]["height_px"]
        for f in meta["frames"]:
            b = f["bbox_px"]
            self.assertGreaterEqual(b["x"] - f["x_px"], 0)
            self.assertGreaterEqual(b["y"] - f["y_px"], 0)
            self.assertLessEqual(b["x"] - f["x_px"] + b["width"], cw)
            self.assertLessEqual(b["y"] - f["y_px"] + b["height"], ch)

    def test_feet_and_bottom_differ_on_a_leaning_subject(self):
        # A body whose lowest row sits off to one side. 'bottom' pins the box
        # centre; 'feet' pins the contact point. If these agree, one of them is
        # not doing what it claims.
        px = blank(48, 48)
        box(px, 48, 14, 8, 20, 22)      # torso
        box(px, 48, 14, 30, 6, 8)       # one leg, hard left
        v = View(px, 48, 48)
        k = self.bundle.kernel
        frame = k.convert_rgba(px, 48, 48, self.settings)
        bbox = content_bbox(self.bundle, frame)
        self.assertIsNotNone(bbox)
        b = anchor_of(self.bundle, frame, bbox, "bottom")
        f = anchor_of(self.bundle, frame, bbox, "feet")
        self.assertEqual(b[1], f[1], "both anchors sit on the same baseline")
        self.assertNotAlmostEqual(b[0], f[0], msg="feet must not collapse onto bottom")

    def test_colour_comes_from_the_model(self):
        # The creator's headline rule. A green subject must produce green cells,
        # with no palette or tint involved.
        k = self.bundle.kernel
        frame = k.convert_rgba(subject(48, 48, rgb=(0.1, 0.9, 0.2)), 48, 48, self.settings)
        inked = [c for c in frame.cells if c.foreground[3] > 0]
        self.assertTrue(inked, "subject produced no opaque cells")
        greens = [c for c in inked if c.foreground[1] > c.foreground[0] and c.foreground[1] > c.foreground[2]]
        self.assertGreater(len(greens) / len(inked), 0.9)

    def test_background_is_transparent(self):
        w, h, px, meta = build_sheet(self.views_at_different_heights(),
                                     bundle=self.bundle, settings=self.settings)
        corner = px[3]                                  # alpha of pixel (0,0)
        self.assertEqual(corner, 0.0)
        self.assertTrue(any(px[i * 4 + 3] > 0 for i in range(w * h)), "sheet is entirely empty")

    def test_deterministic(self):
        a = build_sheet(self.views_at_different_heights(), bundle=self.bundle, settings=self.settings)
        b = build_sheet(self.views_at_different_heights(), bundle=self.bundle, settings=self.settings)
        self.assertEqual(a[2], b[2], "pixels differ between identical runs")
        self.assertEqual(a[3]["content_digest"], b[3]["content_digest"])

    def test_empty_view_keeps_its_grid_slot(self):
        views = [
            View(subject(48, 48), 48, 48, yaw_index=0, frame_index=0),
            View(blank(48, 48), 48, 48, yaw_index=0, frame_index=1),
        ]
        w, h, px, meta = build_sheet(views, bundle=self.bundle, settings=self.settings,
                                     layout="frame_rows")
        self.assertEqual(meta["grid"]["rows"], 2)
        self.assertEqual([f["empty"] for f in meta["frames"]], [False, True])

    def test_png_encodes(self):
        w, h, px, meta = build_sheet(self.views_at_different_heights(),
                                     bundle=self.bundle, settings=self.settings)
        blob = encode_rgba(w, h, px)
        self.assertEqual(blob[:8], b"\x89PNG\r\n\x1a\n")
        self.assertGreater(len(blob), 100)


class Defaults(unittest.TestCase):
    def test_default_output_is_not_ascii_art(self):
        """The creator's rule: it must not look like ASCII unless asked.

        Asserted structurally rather than by eye — the default tile set must not
        be the text ramp, and its vocabulary must carry no letter-like glyph.
        """
        from tessera.tilesets import DEFAULT_TILESET, load, columns_for
        self.assertNotEqual(DEFAULT_TILESET, "text-ramp")
        chars = set(load(DEFAULT_TILESET).kernel.chars)
        self.assertFalse(chars & set(" .:-=+*#%@") - {" "},
                         "default vocabulary contains ASCII-art glyphs")

    def test_default_bundle_is_the_pixel_set(self):
        from tessera.tilesets import DEFAULT_TILESET, load
        views = [View(subject(48, 48), 48, 48)]
        w, h, px, meta = build_sheet(views)            # no bundle passed
        self.assertEqual(meta["kernel_fingerprint"], load(DEFAULT_TILESET).kernel.fingerprint)

    def test_pixel_hd_is_lossless_on_silhouette(self):
        from tessera.tilesets import load
        k = load("pixel-hd").kernel
        patterns = {tuple(r) for r in k.rows}
        self.assertEqual(len(patterns), 2 ** (k.cell_width * k.cell_height))

    def test_quality_presets_scale_with_source(self):
        from tessera.tilesets import columns_for
        self.assertLess(columns_for(192, "draft"), columns_for(192, "standard"))
        self.assertLess(columns_for(192, "standard"), columns_for(192, "high"))
        self.assertEqual(columns_for(192, "high"), 96)   # 1 cell per 2 source px



if __name__ == "__main__":
    unittest.main(verbosity=2)
