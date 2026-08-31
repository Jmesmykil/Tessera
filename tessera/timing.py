"""Animation timing — floats throughout, because animations do not agree.

This module exists because of a specific, measured failure. Ninja Girl's action
runs frames 1..75; her SCENE range says 1..250. Sampling four frames evenly across
the scene range put two of them past the end of the animation, where the rig holds
its final pose — so the sheet came back with duplicate images and timing that
matched nothing. The scene range is a container, not a statement about the motion
inside it.

Hence: the action's own range is the default, and everything is a float.

  - `source_fps` comes from the scene, `target_fps` is what the sprite runs at.
    A 30 fps action sampled for a 12 fps sprite needs 0.4 frames per step, and
    rounding that to 1 loses a third of the motion.
  - `start` / `end` are floats so a user can trim a run-up or a settle without
    re-authoring the action.
  - `phase` shifts the sampling window inside the cycle, which is how you get a
    walk to start on the contact pose rather than mid-stride.
  - `speed` scales duration for a sprite that must play faster than the source.
  - `loop=True` DROPS the endpoint, because a cycle's last frame is its first
    frame. Keeping it puts a stutter in every loop, and it is the single most
    common sprite-sheet defect.

Blender can evaluate between keys, so the resolved samples are fed through
`frame_set(int, subframe=frac)` rather than rounded — sub-frame sampling is the
difference between a smooth 8-frame cycle and a juddering one.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Timing:
    start: float | None = None      # None = take the action's own range
    end: float | None = None
    frames: int | None = None       # explicit count wins over target_fps
    source_fps: float = 24.0
    target_fps: float | None = None
    phase: float = 0.0              # 0..1, fraction of the window to shift by
    speed: float = 1.0              # >1 samples a shorter span (faster playback)
    loop: bool = True               # drop the endpoint; a cycle's end IS its start

    def resolve(self, action_start: float, action_end: float,
                source_fps: float | None = None) -> list[float]:
        fps = source_fps or self.source_fps
        lo = self.start if self.start is not None else float(action_start)
        hi = self.end if self.end is not None else float(action_end)
        if hi < lo:
            raise ValueError(f"end {hi} is before start {lo}")
        span = (hi - lo) / max(self.speed, 1e-6)

        if self.frames:
            count = max(1, int(self.frames))
        elif self.target_fps:
            seconds = span / max(fps, 1e-6)
            count = max(1, round(seconds * self.target_fps))
        else:
            count = 8

        if count == 1:
            return [lo]
        # loop -> the window is divided into `count` equal steps and the endpoint
        # is never emitted; open -> the endpoint IS the last sample.
        step = span / (count if self.loop else count - 1)
        offset = self.phase * span
        samples = [lo + ((offset + i * step) % span if self.loop else offset + i * step)
                   for i in range(count)]
        return [min(max(s, lo), hi) for s in samples]

    def describe(self, samples: list[float], fps: float) -> str:
        if len(samples) < 2:
            return f"1 frame at {samples[0]:.2f}"
        step = samples[1] - samples[0]
        return (f"{len(samples)} frames, step {step:.3f} src-frames "
                f"({step / max(fps, 1e-6) * 1000:.1f} ms at {fps:g} fps), "
                f"{'looping' if self.loop else 'open'}")
