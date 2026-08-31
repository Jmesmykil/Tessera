# Tessera

3D in, game-ready sprite sheets out. No image model anywhere in the path.

Tessera is the fourth host of the **ASCII universal kernel** (`com.astral.ascii.kernel/1`),
after ASCII, ASCII Studio for Blender and ASCII Studio for Unity. It does not fork
that kernel: it copies the payload, verifies the fingerprint at load, and fails
loudly rather than running against a kernel that has drifted.

## Run it

    open ~/Tessera/dist/Tessera.app          # the app
    python3 -m tessera studio                # same thing, in a terminal
    python3 -m tessera doctor                # check kernel, render host, library
    python3 -m tessera library ninja --rigged --animated
    python3 -m tessera config

The app binds to `127.0.0.1:8733` only. Logs go to `~/Library/Logs/Tessera.log`.

## Three editions, one core

| Edition | Status | Why it exists |
|---|---|---|
| standalone | working | Python 3, standard library only. Runs anywhere the kernel does. |
| Blender | capture working | The DCC renders with real materials, textures and lighting first. |
| Unity | planned | Physics- and solver-driven subjects (SlimeShot) that have no baked clip. |

Feature work lands once, in the shared layer. An edition never forks it.

## What is configuration, not code

Nothing here knows a path on anyone's machine. `tessera/config.py` layers
flag → `TESSERA_CONFIG` → `~/.config/tessera/config.json` → `profiles/*.json`.
`profiles/workstation.json` describes this workstation — a BlendKit library on a
Linux box, Blender over SSH with `DRI_PRIME=1`. Someone else drops in their own
profile and no code changes.

The library index is cached locally so browsing does not shell out per keystroke;
asset paths stay remote, because that is where the render happens.

## Things learned the hard way, now encoded

- **The scene range is not the action range.** Ninja Girl's scene says 1..250; her
  action ends at 75. Samples past the end return the held final pose — duplicate
  cells, and no error anywhere. Timing reads `action.frame_range`.
- **A cycle's last frame is its first.** `loop=True` drops the endpoint. Keeping it
  puts a stutter in every loop.
- **Track the root, not the bounding box.** A bbox centroid moves when a limb
  extends, so an overhead sword drags the camera and the character appears to sink.
- **Lights ride the camera.** A world-fixed key lights the front and silhouettes
  the back, so one character reads as two across a turnaround.
- **AgX is a bug here.** Blender's default view transform drains saturation by
  design. The product rule is that colour comes from the model.
- **Cell aspect 0.5 is a terminal value.** Left alone it squashes every sprite by
  1.43x, which reads as a modelling error and gets debugged as one.
- **Luminance-driven coverage is wrong for sprites.** A red torso is never white so
  it never picks a solid tile. `fill_mode="solid"` runs the kernel twice —
  silhouette for coverage, alpha-masked colour for colour.

## Checks are not optional

`tessera/qa.py` runs on every sheet and each check can FAIL: cells non-empty,
coverage consistent, anchor identical in every cell, bbox inside its cell, orbit
varies, frames distinct, output not crushed to black. The app shows the result and
the runner refuses to deliver a failing sheet. Verified against a known-bad
capture, where it fails 4 of 7 — a guard that passes everything is worthless.

## Tile sets are data

`text-ramp` (5x7, 10 glyphs, the canonical kernel) · `quadrant-block` (4x4, 16
blocks) · `pixel-hd` (2x2 carrying **all 16 possible patterns**, so silhouette
reproduction is lossless). Default is `pixel-hd`: this is a sprite generator, and
it should not look like ASCII unless someone asks for that.

    tests: python3 tests/test_sheet.py && python3 tests/test_timing.py
