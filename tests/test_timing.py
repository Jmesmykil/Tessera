"""Tests for the timing model, written from the defect that produced it.

Ninja Girl's action runs 1..75 while her scene claims 1..250. Sampling the scene
range put two of four samples past the end of the motion, where the rig holds its
final pose — duplicate cells, and timing matching nothing. Every test here pins
one property of the fix.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tessera.lighting import PRESETS, LightingProfile
from tessera.timing import Timing


class Sampling(unittest.TestCase):
    def test_samples_stay_inside_the_action(self):
        for count in (1, 2, 4, 8, 16, 37):
            samples = Timing(frames=count).resolve(1, 75)
            self.assertEqual(len(samples), count)
            self.assertTrue(all(1.0 <= s <= 75.0 for s in samples),
                            f"{count} frames escaped the action range: {samples}")

    def test_the_original_defect_cannot_recur(self):
        # The broken run sampled 1, 63, 126, 188 over the SCENE range 1..250.
        # Against the ACTION range nothing may exceed 75.
        self.assertTrue(max(Timing(frames=4).resolve(1, 75)) <= 75.0)
        # And sampling the scene range really would have escaped, so the test
        # above is discriminating rather than vacuous.
        self.assertGreater(max(Timing(frames=4, loop=False).resolve(1, 250)), 75.0)

    def test_loop_drops_the_endpoint(self):
        looping = Timing(frames=4, loop=True).resolve(0, 100)
        opened = Timing(frames=4, loop=False).resolve(0, 100)
        self.assertNotIn(100.0, looping, "a cycle's endpoint duplicates its start")
        self.assertEqual(opened[-1], 100.0)

    def test_samples_are_distinct(self):
        for count in (4, 8, 12):
            samples = Timing(frames=count).resolve(1, 75)
            self.assertEqual(len(set(samples)), count, f"duplicate samples: {samples}")

    def test_fractional_frames_are_preserved(self):
        samples = Timing(frames=8).resolve(1, 75)
        self.assertTrue(any(abs(s - round(s)) > 1e-6 for s in samples),
                        "no sub-frame samples; rounding would judder a short cycle")

    def test_target_fps_sets_the_count(self):
        # 74 source frames at 24 fps is ~3.08 s; at 12 fps that is ~37 samples.
        samples = Timing(target_fps=12, source_fps=24).resolve(1, 75)
        self.assertEqual(len(samples), 37)
        self.assertEqual(len(Timing(target_fps=24, source_fps=24).resolve(1, 75)), 74)

    def test_speed_shortens_the_window(self):
        fast = Timing(frames=4, speed=2.0).resolve(1, 75)
        normal = Timing(frames=4, speed=1.0).resolve(1, 75)
        self.assertLess(max(fast), max(normal))

    def test_phase_rotates_without_leaving_the_window(self):
        shifted = Timing(frames=4, phase=0.25).resolve(1, 75)
        self.assertEqual(len(set(shifted)), 4)
        self.assertTrue(all(1.0 <= s <= 75.0 for s in shifted))

    def test_explicit_trim_is_honoured(self):
        samples = Timing(frames=5, start=20.5, end=40.25).resolve(1, 75)
        self.assertTrue(all(20.5 <= s <= 40.25 for s in samples), samples)

    def test_backwards_range_is_refused(self):
        with self.assertRaises(ValueError):
            Timing(frames=4, start=80, end=10).resolve(1, 75)


class Lighting(unittest.TestCase):
    def test_every_preset_builds(self):
        for name in PRESETS:
            self.assertEqual(LightingProfile.named(name).name, name)

    def test_no_preset_leaves_the_filmic_tonemap_on(self):
        # AgX drains saturation; the product rule is colour from the model.
        for name in PRESETS:
            self.assertIn(LightingProfile.named(name).view_transform, ("Standard", "Raw"))

    def test_flat_really_is_flat(self):
        flat = LightingProfile.named("flat")
        self.assertEqual((flat.key_energy, flat.fill_energy, flat.rim_energy), (0.0, 0.0, 0.0))
        self.assertGreater(flat.ambient_strength, 0.5)

    def test_round_trips_through_json(self):
        import tempfile
        profile = LightingProfile.named("dark-subject")
        path = Path(tempfile.mkdtemp()) / "p.json"
        profile.to_json(path)
        self.assertEqual(LightingProfile.from_json(path), profile)

    def test_unknown_keys_are_refused(self):
        import json, tempfile
        path = Path(tempfile.mkdtemp()) / "bad.json"
        path.write_text(json.dumps({"name": "x", "kye_energy": 3.0}))
        with self.assertRaises(ValueError):
            LightingProfile.from_json(path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
