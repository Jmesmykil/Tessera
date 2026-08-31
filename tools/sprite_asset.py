#!/usr/bin/env python3
"""One command: a .blend in, a sprite sheet out.

  python3 tools/sprite_asset.py --list
  python3 tools/sprite_asset.py carrot --yaws 8 --size 256 --quality high

The machine gate below is CODE rather than a note, because it is the one thing a
future run must not be free to skip. This Mac has kernel-panicked twice under
memory pressure, and a headless Blender started beside a live session is exactly
how it happened. The thresholds are the ones that incident produced.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tessera.frames import read_views
from tessera.png import write_rgba
from tessera.sheet import build_sheet, sprite_settings
from tessera.tilesets import DEFAULT_TILESET, columns_for, load, PALETTES

BLENDER = Path("/Applications/Blender.app/Contents/MacOS/Blender")
LIBRARY = Path.home() / "blenderkit_data" / "models"
OUT = Path.home() / "Tessera" / "out"
MIN_AVAILABLE_GB = 6.0
MIN_SWAP_FREE_GB = 1.5


def machine_state() -> tuple[float, float, list[int]]:
    vm = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    counts = {}
    for line in vm.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            value = value.strip().rstrip(".")
            if value.isdigit():
                counts[key.strip()] = int(value)
    available = sum(counts.get(k, 0) for k in
                    ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"))
    available_gb = available * 16384 / 2 ** 30
    swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    swap_free_gb = float(re.search(r"free = ([\d.]+)M", swap).group(1)) / 1024
    running = [int(p) for p in subprocess.run(
        ["pgrep", "-x", "Blender"], capture_output=True, text=True).stdout.split()]
    return available_gb, swap_free_gb, running


def check_gate(force: bool) -> None:
    available, swap_free, running = machine_state()
    print(f"machine    available {available:.2f} GB (need {MIN_AVAILABLE_GB})   "
          f"swap free {swap_free:.2f} GB (need {MIN_SWAP_FREE_GB})")
    if running:
        print(f"           Blender already running: pid {', '.join(map(str, running))}")
    problems = []
    if available < MIN_AVAILABLE_GB:
        problems.append(f"available memory {available:.2f} GB below {MIN_AVAILABLE_GB} GB")
    if swap_free < MIN_SWAP_FREE_GB:
        problems.append(f"swap free {swap_free:.2f} GB below {MIN_SWAP_FREE_GB} GB")
    if running:
        problems.append(f"a Blender session is already open (pid {running[0]}) — "
                        "a second one beside it is what caused the panics")
    if problems and not force:
        print("\nBLOCKED, and deliberately:")
        for problem in problems:
            print(f"  - {problem}")
        print("\nThe capture is ready and unchanged; rerun when the machine is clear, "
              "or pass --force if you have decided otherwise.")
        raise SystemExit(2)
    if problems:
        print("  --force given; proceeding over " + str(len(problems)) + " blocked condition(s)")


def catalogue() -> dict[str, Path]:
    found: dict[str, Path] = {}
    for blend in sorted(LIBRARY.glob("*/*.blend")):
        name = re.sub(r"_(\d+K|0_5K)?_?[0-9a-f-]{8,}.*$", "", blend.stem) or blend.stem
        found.setdefault(name, blend)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("asset", nargs="?")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--yaws", type=int, default=8)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--quality", default="high")
    ap.add_argument("--tileset", default=DEFAULT_TILESET)
    ap.add_argument("--palette", default=None, choices=sorted(PALETTES))
    ap.add_argument("--anchor", default="bottom")
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    assets = catalogue()
    if args.list or not args.asset:
        print(f"{len(assets)} BlendKit assets in {LIBRARY}\n")
        for name in sorted(assets):
            print(f"  {name}")
        return 0

    matches = [n for n in assets if args.asset.lower() in n.lower()]
    if not matches:
        print(f"no asset matching {args.asset!r}; try --list")
        return 1
    if len(matches) > 1 and args.asset not in matches:
        print(f"{args.asset!r} matches {len(matches)}: {', '.join(sorted(matches)[:8])}")
        return 1
    name = args.asset if args.asset in matches else matches[0]
    blend = assets[name]

    check_gate(args.force)
    if not BLENDER.is_file():
        print(f"Blender not found at {BLENDER}")
        return 1

    frames = OUT / f"{name}.tsf"
    capture = Path(__file__).resolve().parents[1] / "tessera" / "blender" / "capture.py"
    print(f"capturing  {name}  ({blend.name})")
    result = subprocess.run([str(BLENDER), "--background", "--factory-startup", str(blend),
                             "--python", str(capture), "--",
                             "--out", str(frames), "--yaws", str(args.yaws),
                             "--size", str(args.size)],
                            capture_output=True, text=True)
    if result.returncode != 0 or not frames.exists():
        print(result.stdout[-2000:]); print(result.stderr[-2000:])
        return 1

    views = read_views(frames)
    bundle = load(args.tileset)
    extra = {}
    if args.palette:
        extra = dict(color_mode="PALETTE", palette=[tuple(c) for c in PALETTES[args.palette]])
    settings = sprite_settings(
        bundle, columns=columns_for(args.size, args.quality, bundle.kernel.cell_width), **extra)
    w, h, pixels, meta = build_sheet(views, bundle=bundle, settings=settings,
                                     anchor=args.anchor, layout="direction_rows",
                                     scale=args.scale, fill_mode="solid")
    meta["subject"] = {"asset": name, "blend": str(blend), "tileset": args.tileset,
                       "quality": args.quality, "palette": args.palette}
    png = write_rgba(OUT / f"{name}-sheet.png", w, h, pixels)
    (OUT / f"{name}-sheet.json").write_text(json.dumps(meta, indent=2))
    print(f"sheet      {w}x{h}px   {meta['grid']['rows']}x{meta['grid']['columns']} cells   {png}")
    subprocess.run(["open", "-R", str(png)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
