#!/usr/bin/env python3
"""Coverage sweep: every model and animation shape, hunting SILENT failures.

Three real defects in this project were silent — they produced a plausible image
and no error. A rig whose motion lived in NLA strips rendered a bind pose; samples
past the end of an action returned the held final pose; a static prop's identical
frames were reported as a defect. None raised an exception, and a person caught
all three by eye.

So this sweep does not ask "did it crash". It asks, per asset, whether each known
silent-failure SHAPE is present, and writes a receipt with the measurements behind
every verdict. A verdict with no number behind it is an opinion.

  python3 tools/sweep.py --limit 12 --size 256
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tessera.frames import read_views
from tessera.png import write_rgba
from tessera.qa import inspect
from tessera.sheet import build_sheet, sprite_settings
from tessera.tilesets import columns_for, load

LIBRARY = Path("/mnt/shared/blendkit_library")
OUT = Path.home() / "Tessera" / "out" / "sweep"
BLENDER = "blender"


def truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def pick(limit: int):
    """A matrix, not a random sample. Each row names the shape it is there to test."""
    rows = list(csv.DictReader((LIBRARY / "INDEX.csv").open()))
    def find(pred, n=1):
        out = []
        for r in rows:
            if pred(r):
                out.append(r)
                if len(out) >= n:
                    break
        return out

    faces = lambda r: int(float(r["faceCount"] or 0))
    groups = [
        ("rigged+animated human", find(lambda r: r["top"] == "humans" and truthy(r["rig"])
                                       and truthy(r["animated"]), 2)),
        ("rigged, NOT animated", find(lambda r: truthy(r["rig"]) and not truthy(r["animated"]), 1)),
        ("animated, no rig", find(lambda r: truthy(r["animated"]) and not truthy(r["rig"]), 1)),
        ("static prop (furniture)", find(lambda r: r["top"] == "furniture", 1)),
        ("static prop (tools)", find(lambda r: r["top"] == "tools", 1)),
        ("weapon", find(lambda r: r["top"] == "weapons", 1)),
        ("animal rigged", find(lambda r: r["top"] == "animals" and truthy(r["rig"]), 1)),
        ("very low poly", find(lambda r: 0 < faces(r) < 1200, 1)),
        ("very high poly", sorted(rows, key=faces, reverse=True)[:1]),
    ]
    picked = []
    for label, entries in groups:
        for entry in entries:
            if not entry["rel"].endswith(".blend"):
                continue
            picked.append((label, entry))
            if len(picked) >= limit:
                return picked
    return picked


LOCK = Path(__file__).parents[1] / "tessera" / "blender" / "gpu_lock.sh"


def run_blender(args: list[str], timeout=600):
    """Always through the lock: concurrent Blenders on this host hang rather than fail."""
    started = time.time()
    import os
    from tessera.config import Config
    env = {**os.environ, **(Config.load().host.env or {})}
    proc = subprocess.run([str(LOCK), str(timeout), BLENDER,
                           "--background", "--factory-startup"] + args,
                          capture_output=True, text=True, timeout=timeout + 90, env=env)
    return proc, time.time() - started


def sweep(limit: int, size: int, yaws: int, frames: int):
    OUT.mkdir(parents=True, exist_ok=True)
    receipts = []
    for index, (shape, row) in enumerate(pick(limit), 1):
        blend = LIBRARY / row["rel"]
        stem = f"sweep{index:02d}"
        receipt = {
            "n": index, "shape": shape, "name": row["name"], "rel": row["rel"],
            "index_says": {"rig": truthy(row["rig"]), "animated": truthy(row["animated"]),
                           "faces": row["faceCount"], "top": row["top"],
                           "category": row["category"]},
            "failures": [], "checks": {},
        }
        print(f"\n[{index}/{limit}] {shape}: {row['name'][:44]}", flush=True)

        # 1. clips + capture in ONE launch ------------------------------------
        # Two cold Blender starts per asset was costing more than the renders. The
        # capture now writes the clip list on its way through, so the sweep pays
        # one start and one file load instead of two of each.
        clips_path = OUT / f"{stem}-clips.json"
        tsf = OUT / f"{stem}.tsf"
        script = str(Path(__file__).parents[1] / "tessera/blender/capture.py")
        proc, seconds = run_blender([
            str(blend), "--python", script, "--",
            "--out", str(tsf), "--clips-json-also", str(clips_path),
            "--yaws", str(yaws), "--frames", str(frames), "--size", str(size),
            "--profile", "studio"])
        receipt["capture"] = {"seconds": round(seconds, 1), "exit": proc.returncode}
        for line in proc.stdout.splitlines():
            for key in ("engine", "clip", "action", "timing", "samples", "tracking",
                        "framing", "colour", "lighting"):
                if line.startswith(key):
                    receipt["capture"][key] = line.split(None, 1)[1].strip()
        if not clips_path.exists():
            receipt["failures"].append("clip listing produced no file")
            receipt["stderr_tail"] = proc.stderr[-400:]
            receipts.append(receipt)
            continue
        clips = json.loads(clips_path.read_text())["clips"]
        motion = [c for c in clips if not c["pose"]]
        receipt["clips"] = {"total": len(clips), "motion": len(motion),
                            "poses": len(clips) - len(motion),
                            "names": [c["name"] for c in clips[:6]],
                            "seconds": round(seconds, 1)}
        # The index claiming animated while the file exposes no motion is exactly
        # the NLA-strip class of silent failure, seen from the other side.
        if truthy(row["animated"]) and not motion:
            receipt["failures"].append(
                "index says animated but no motion clip was found")

        receipt["clip_used"] = receipt["capture"].get("clip", "")
        if not tsf.exists():
            receipt["failures"].append(f"capture produced no frames (exit {proc.returncode})")
            receipt["stderr_tail"] = proc.stderr[-400:]
            receipts.append(receipt)
            continue

        # 3. sheet + QA -------------------------------------------------------
        views = read_views(tsf)
        bundle = load("pixel-hd")
        settings = sprite_settings(bundle, columns=columns_for(size, "high", 2))
        started = time.time()
        w, h, pixels, meta = build_sheet(views, bundle=bundle, settings=settings,
                                         anchor="feet", scale=1, fill_mode="solid")
        findings = inspect(pixels, w, h, meta)
        write_rgba(OUT / f"{stem}.png", w, h, pixels)
        receipt["sheet"] = {"width": w, "height": h, "grid": meta["grid"],
                            "cell": [meta["cell"]["width_px"], meta["cell"]["height_px"]],
                            "pack_seconds": round(time.time() - started, 1)}
        receipt["checks"] = {f.check: {"ok": f.ok, "detail": f.detail} for f in findings}
        for finding in findings:
            if not finding.ok:
                receipt["failures"].append(f"{finding.check}: {finding.detail}")

        # 4. silent-failure probes the QA pass cannot see ---------------------
        opaque = [i for i in range(w * h) if pixels[i * 4 + 3] > 0]
        if opaque:
            sat = []
            for i in opaque[::37]:
                r, g, b = pixels[i * 4], pixels[i * 4 + 1], pixels[i * 4 + 2]
                hi, lo = max(r, g, b), min(r, g, b)
                sat.append(0.0 if hi <= 0 else (hi - lo) / hi)
            mean_sat = sum(sat) / len(sat)
            receipt["checks"]["carries colour"] = {
                "ok": mean_sat > 0.02,
                "detail": f"mean saturation {mean_sat:.3f} over {len(sat)} samples"}
            if mean_sat <= 0.02:
                receipt["failures"].append(
                    "render is greyscale — material or texture may not have loaded")
        # A sprite squashed by the terminal cell aspect is the defect that reads as
        # a modelling error, so it is measured rather than trusted.
        expected = bundle.kernel.cell_width / bundle.kernel.cell_height
        receipt["checks"]["cell aspect"] = {
            "ok": abs(settings.cell_aspect - expected) < 1e-6,
            "detail": f"{settings.cell_aspect:.4f} (expect {expected:.4f})"}

        receipt["verdict"] = "PASS" if not receipt["failures"] else "FAIL"
        print(f"    {receipt['verdict']}  clips={len(clips)} motion={len(motion)}  "
              f"{w}x{h}  {receipt['capture']['seconds']}s", flush=True)
        for failure in receipt["failures"]:
            print(f"      ! {failure}", flush=True)
        receipts.append(receipt)

    ledger = OUT / "receipts.jsonl"
    with ledger.open("w") as fh:
        for receipt in receipts:
            receipt.setdefault("verdict", "FAIL")
            fh.write(json.dumps(receipt) + "\n")

    passed = sum(1 for r in receipts if r["verdict"] == "PASS")
    print(f"\n{'=' * 62}\n{passed}/{len(receipts)} passed — receipts at {ledger}")
    for receipt in receipts:
        mark = "ok  " if receipt["verdict"] == "PASS" else "FAIL"
        print(f"  [{mark}] {receipt['shape']:24} {receipt['name'][:34]}")
        for failure in receipt["failures"]:
            print(f"           ! {failure[:96]}")
    return 0 if passed == len(receipts) else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--size", type=int, default=256)
    ap.add_argument("--yaws", type=int, default=3)
    ap.add_argument("--frames", type=int, default=4)
    raise SystemExit(sweep(**vars(ap.parse_args())))
