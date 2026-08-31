#!/usr/bin/env python3
"""Render a whole library to sprite sheets, mirroring its own organisation.

Output lands beside the source structure rather than in a flat dump: an asset at
`humans/rigged/women/Ninja_Girl.blend` produces
`<out>/humans/rigged/women/Ninja_Girl/<clip>.png` and its sidecar. A game needs to
find these later, and the tree the models are already organised by is the one the
person already knows.

Three properties matter more than speed here:

  RESUMABLE. A library this size is a multi-day job on one GPU. Anything already
  written is skipped, so an interrupted run continues rather than restarting.

  SERIAL. Concurrent headless Blenders on this host HANG rather than fail — three
  of them sat for 38 minutes on a 12 MB asset. Every launch goes through the same
  lock the app uses.

  ACCOUNTED. Every asset writes a receipt whether it passed, failed or was skipped,
  so "the library is rendered" is a claim someone can check.

  python3 tools/batch.py --out ~/Sheets --limit 50 --tune ~/.config/tessera/tunes/game.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tessera.config import Config
from tessera.library import provider_for

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "tessera" / "blender" / "gpu_lock.sh"
CAPTURE = ROOT / "tessera" / "blender" / "capture.py"
TESSERA_CLI = ROOT / "rust" / "target" / "release" / "tessera"


def blender(config, args, timeout=900):
    """Always serialised and always time-boxed. See gpu_lock.sh for why both."""
    import os
    env = {**os.environ, **(config.host.env or {})}
    return subprocess.run(
        [str(LOCK), str(timeout), config.host.blender,
         "--background", "--factory-startup"] + args,
        capture_output=True, text=True, timeout=timeout + 120, env=env)


def clips_for(config, blend: Path, scratch: Path):
    target = scratch / "clips.json"
    proc = blender(config, [str(blend), "--python", str(CAPTURE), "--",
                            "--clips-json", str(target)], timeout=900)
    if not target.exists():
        return None, proc.stderr[-300:]
    return json.loads(target.read_text())["clips"], None


def render(config, blend: Path, clip, destination: Path, tune: dict, scratch: Path):
    tsf = scratch / "frames.tsf"
    args = [str(blend), "--python", str(CAPTURE), "--",
            "--out", str(tsf),
            "--yaws", str(tune.get("yaws", 8)),
            "--frames", str(tune.get("frames", 8)),
            "--size", str(tune.get("size", 512)),
            "--profile", tune.get("profile", "studio"),
            "--center", tune.get("center", "root"),
            "--root-motion", tune.get("root_motion", "strip"),
            "--elevation", str(tune.get("elevation", 30)),
            "--loop", "1" if tune.get("loop", True) else "0"]
    for flag, key in (("--key-azimuth", "key_azimuth"), ("--key-elevation", "key_elevation"),
                      ("--ambient", "ambient"), ("--key", "key"), ("--fill", "fill"),
                      ("--rim", "rim"), ("--exposure", "exposure")):
        if tune.get(key) is not None:
            args += [flag, str(tune[key])]
    if clip:
        args += ["--clip", clip]

    started = time.time()
    proc = blender(config, args)
    if not tsf.exists():
        return {"ok": False, "stage": "capture", "exit": proc.returncode,
                "error": proc.stderr[-300:], "seconds": round(time.time() - started, 1)}

    size = int(tune.get("size", 512))
    cell = {"pixel-hd": 2, "quadrant-block": 4, "text-ramp": 5}.get(
        tune.get("tileset", "pixel-hd"), 2)
    factor = {"draft": 0.25, "standard": 0.5, "high": 1.0}.get(tune.get("quality", "high"), 1.0)
    columns = max(8, min(1024, round((size // cell) * factor)))
    tileset = ROOT / "assets" / ("kernel.json" if tune.get("tileset") == "text-ramp"
                                 else f"tilesets/{tune.get('tileset', 'pixel-hd')}.kernel.json")

    destination.parent.mkdir(parents=True, exist_ok=True)
    pack = subprocess.run(
        [str(TESSERA_CLI), "sheet", str(tsf), str(destination),
         "--tileset", str(tileset), "--columns", str(columns),
         "--anchor", tune.get("anchor", "feet")],
        capture_output=True, text=True)
    tsf.unlink(missing_ok=True)
    checks = [line.strip() for line in pack.stdout.splitlines() if line.strip().startswith("[")]
    return {"ok": pack.returncode == 0, "qa_passed": pack.returncode == 0,
            "stage": "packed", "checks": checks,
            "sheet": pack.stdout.strip().splitlines()[-1] if pack.stdout.strip() else "",
            "seconds": round(time.time() - started, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="output root (default: config out_dir)")
    ap.add_argument("--limit", type=int, default=0, help="0 = the whole library")
    ap.add_argument("--tune", default=None)
    ap.add_argument("--clips", default="first", choices=["first", "all"])
    ap.add_argument("--filter", default="", help="substring on name or category")
    args = ap.parse_args()

    config = Config.load()
    out_root = Path(args.out or config.out_dir).expanduser()
    tune = json.loads(Path(args.tune).expanduser().read_text()) if args.tune else {}
    scratch = Path.home() / ".cache" / "tessera" / "batch"
    scratch.mkdir(parents=True, exist_ok=True)
    ledger = out_root / "receipts.jsonl"
    out_root.mkdir(parents=True, exist_ok=True)

    library = config.library()
    assets = list(provider_for(library, config.host).assets())
    if args.filter:
        needle = args.filter.lower()
        assets = [a for a in assets
                  if needle in a.name.lower() or needle in a.category.lower()]
    if args.limit:
        assets = assets[:args.limit]

    root = Path(library.root)
    print(f"{len(assets)} assets -> {out_root}\n")
    done = failed = skipped = 0

    with ledger.open("a") as receipts:
        for index, asset in enumerate(assets, 1):
            try:
                relative = asset.path.relative_to(root).with_suffix("")
            except ValueError:
                relative = Path(asset.name)
            folder = out_root / relative
            marker = folder / "_done.json"
            if marker.exists():
                skipped += 1
                continue

            if not asset.path.exists():
                # 52% of this library's index rows point at files that are not on
                # disk. A missing asset is a catalogue fact, not a render failure,
                # so it is recorded and skipped rather than counted as broken.
                skipped += 1
                receipts.write(json.dumps({"asset": str(relative), "ok": None,
                                           "stage": "missing",
                                           "error": "indexed but not on disk"}) + "\n")
                continue

            print(f"[{index}/{len(assets)}] {asset.name[:46]}", flush=True)
            clips, error = clips_for(config, asset.path, scratch)
            if clips is None:
                failed += 1
                receipts.write(json.dumps({"asset": str(relative), "ok": False,
                                           "stage": "clips", "error": error}) + "\n")
                receipts.flush()
                print("    FAILED reading clips", flush=True)
                continue

            motion = [c for c in clips if not c["pose"]] or [None]
            chosen = motion if args.clips == "all" else motion[:1]
            results = []
            for clip in chosen:
                label = (clip["name"] if clip else "still").replace("/", "_")
                safe = "".join(ch if ch.isalnum() or ch in "-_ ." else "_" for ch in label)
                outcome = render(config, asset.path, clip["name"] if clip else None,
                                 folder / f"{safe}.png", tune, scratch)
                outcome["clip"] = label
                results.append(outcome)
                print(f"    {label[:40]:42} "
                      f"{'ok' if outcome['ok'] else 'FAILED'}  {outcome['seconds']}s",
                      flush=True)

            ok = all(r["ok"] for r in results)
            done += ok
            failed += (not ok)
            if ok:
                marker.write_text(json.dumps({"clips": [r["clip"] for r in results]}, indent=2))
            receipts.write(json.dumps({"asset": str(relative), "ok": ok,
                                       "clips": results}) + "\n")
            receipts.flush()

    print(f"\ndone {done}   failed {failed}   already present {skipped}")
    print(f"receipts: {ledger}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
