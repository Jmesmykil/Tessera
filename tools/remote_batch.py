#!/usr/bin/env python3
"""Render a remote library on this machine, and put the sheets back beside it.

The library lives on another box and the renderer runs here, so each asset makes a
round trip: fetch, render, pack, push back. The sheets land mirroring the library's
own folders, so a model and its sprites sit together and a game can find them by
the path it already knows.

Why not mount it: neither NFS, SMB nor sshfs is available between these machines,
and a per-asset copy over the LAN costs a few seconds against a render that costs
tens — so the copy is not the bottleneck and needing no mount is worth more than
saving it.

Resumable, serial, and time-boxed. Anything already on the far side is skipped, one
Blender runs at a time, and no asset may hang the queue.

  python3 tools/remote_batch.py --limit 5 --size 384
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
CAPTURE = ROOT / "tessera" / "blender" / "capture.py"
CLI = ROOT / "rust" / "target" / "release" / "tessera"
CACHE = Path.home() / ".cache" / "tessera" / "remote-assets"
BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"

HOST = "astral-primary"
LIBRARY = "/mnt/shared/blendkit_library"
SHEETS = f"{LIBRARY}/_sprites"


class BlenderLock:
    """One Blender at a time on this machine, and wait rather than fail.

    Every render failure today traced to two Blenders running at once — on Linux
    it wedged the GPU driver into unkillable D-state, and here it simply made
    renders come back empty. The same asset that "failed" in a batch rendered
    perfectly the moment nothing else was running.

    So the batch takes an advisory lock and waits for it. It also has to coexist
    with the creator's own interactive Blender, which this lock cannot see — hence
    the retry below: one contended failure is worth retrying once before it is
    called a defect, because a defect report that is really a scheduling accident
    is worse than no report.
    """

    def __init__(self, path=Path("/tmp/tessera-blender.lock"), timeout=1800):
        self.path, self.timeout, self.handle = path, timeout, None

    def __enter__(self):
        import fcntl
        self.handle = self.path.open("w")
        deadline = time.time() + self.timeout
        while True:
            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.time() > deadline:
                    raise SystemExit("another Blender has held the lock too long")
                time.sleep(2)

    def __exit__(self, *_):
        import fcntl
        if self.handle:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()


def wait_for_other_blender(quiet_seconds: float = 3.0, limit: float = 900):
    """Do not start while any other Blender is mid-render, ours or the creator's."""
    deadline = time.time() + limit
    while time.time() < deadline:
        running = subprocess.run(["pgrep", "-f", "Blender --background"],
                                 capture_output=True, text=True).stdout.strip()
        if not running:
            time.sleep(quiet_seconds)
            again = subprocess.run(["pgrep", "-f", "Blender --background"],
                                   capture_output=True, text=True).stdout.strip()
            if not again:
                return True
        time.sleep(5)
    return False


def ssh(command: str, timeout=120):
    return subprocess.run(["ssh", "-n", "-o", "BatchMode=yes", HOST, command],
                          capture_output=True, text=True, timeout=timeout,
                          env={**__import__("os").environ, "SSH_AUTH_SOCK": ""})


def headroom() -> tuple[float, float]:
    """Available GB and free swap GB. This Mac has panicked under memory pressure."""
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
    swap = subprocess.run(["sysctl", "-n", "vm.swapusage"], capture_output=True, text=True).stdout
    return (available * 16384 / 2 ** 30,
            float(re.search(r"free = ([\d.]+)M", swap).group(1)) / 1024)


def remote_assets(limit: int, needle: str):
    script = (
        "python3 -c \"import csv,os,json;"
        f"rows=[r for r in csv.DictReader(open('{LIBRARY}/INDEX.present.csv'))];"
        "print(json.dumps([{'rel':r['rel'],'name':r['name'],'top':r['top'],"
        "'category':r['category'],'rig':r['rig'],'animated':r['animated']} for r in rows]))\"")
    result = ssh(script, timeout=180)
    if result.returncode != 0:
        raise SystemExit(f"could not read the remote index: {result.stderr[:200]}")
    rows = json.loads(result.stdout)
    if needle:
        low = needle.lower()
        rows = [r for r in rows
                if low in r["name"].lower() or low in r["category"].lower()
                or low in r["top"].lower()]
    return rows[:limit] if limit else rows


def fetch(rel: str) -> Path | None:
    local = CACHE / rel.replace("/", "__")
    if local.is_file() and local.stat().st_size > 0:
        return local
    local.parent.mkdir(parents=True, exist_ok=True)
    copy = subprocess.run(
        ["scp", "-q", f"{HOST}:{LIBRARY}/{rel}", str(local)],
        capture_output=True, text=True,
        env={**__import__("os").environ, "SSH_AUTH_SOCK": ""})
    return local if copy.returncode == 0 and local.is_file() else None


def safe_name(text: str) -> str:
    """A filename a game can reference. The author's clip name, minus what breaks paths."""
    cleaned = re.sub(r"\s*\(\d+-\d+\)\s*$", "", text).strip()
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", cleaned)
    return re.sub(r"\s+", "_", cleaned) or "clip"


def render_adaptive(blend, clip, out_png, size, yaws, frames, timeout, clips_out=None):
    """Render, and if the sheet repeats itself, sample the clip less densely.

    A zebra's sleep cycle runs 125 frames and barely moves. Eight samples across it
    are genuinely identical once quantised, and the duplicate check is right to say
    so — but the fix is fewer frames, not a failure. A slow animation needs fewer
    samples than a run cycle, and nothing in the file says which it is until it has
    been rendered once.

    So a duplicate report becomes a retry at half the frames rather than a defect.
    A sheet with four distinct poses is worth more than eight where five repeat,
    and it is smaller.
    """
    outcome = render(blend, clip, out_png, size, yaws, frames, timeout, clips_out)
    duplicated = any("frames distinct" in line and line.startswith("[FAIL")
                     for line in outcome.get("checks", []))
    if not duplicated or frames <= 2:
        return outcome
    reduced = max(2, frames // 2)
    retry = render(blend, clip, out_png, size, yaws, reduced, timeout)
    retry["reduced_frames"] = reduced
    still_duplicated = any("frames distinct" in line and line.startswith("[FAIL")
                           for line in retry.get("checks", []))
    if still_duplicated and reduced > 2:
        final = render(blend, clip, out_png, size, yaws, 2, timeout)
        final["reduced_frames"] = 2
        return final if final.get("ok") else retry
    return retry if retry.get("ok") else outcome


def render(blend: Path, clip: str | None, out_png: Path, size: int, yaws: int,
           frames: int, timeout: int, clips_out: Path | None = None):
    tsf = CACHE / "frames.tsf"
    args = [BLENDER, "--background", "--factory-startup", str(blend),
            "--python", str(CAPTURE), "--", "--out", str(tsf),
            "--yaws", str(yaws), "--frames", str(frames), "--size", str(size),
            "--profile", "studio"]
    # The clip list comes out of the render that was happening anyway, rather than
    # paying a second cold Blender start to ask what the animations are called.
    if clips_out is not None:
        args += ["--clips-json-also", str(clips_out)]
    if clip:
        args += ["--clip", clip]
    started = time.time()
    proc = None
    for attempt in (1, 2):
        tsf.unlink(missing_ok=True)
        try:
            with BlenderLock():
                proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"render exceeded {timeout}s", "seconds": timeout}
        if tsf.exists():
            break
        if attempt == 1:
            # Contention looks exactly like a broken asset. Give it one clean run
            # before calling it broken, rather than filing a scheduling accident
            # as a defect.
            wait_for_other_blender(limit=120)
    if not tsf.exists():
        tail = "\n".join((proc.stdout if proc else "").splitlines()[-3:])
        return {"ok": False, "error": tail or (proc.stderr[-200:] if proc else "no output"),
                "seconds": round(time.time() - started, 1), "retried": True}

    out_png.parent.mkdir(parents=True, exist_ok=True)
    columns = max(8, min(1024, size // 2))
    pack = subprocess.run(
        [str(CLI), "sheet", str(tsf), str(out_png),
         "--tileset", str(ROOT / "assets/tilesets/pixel-hd.kernel.json"),
         "--columns", str(columns), "--anchor", "feet"],
        capture_output=True, text=True)
    tsf.unlink(missing_ok=True)
    note = ""
    for line in proc.stdout.splitlines():
        if line.startswith(("clip", "timing", "deps")):
            note = line.strip()
    return {"ok": pack.returncode == 0, "qa_passed": pack.returncode == 0,
            "note": note,
            "sheet": pack.stdout.strip().splitlines()[-1] if pack.stdout.strip() else "",
            "checks": [l.strip() for l in pack.stdout.splitlines() if l.strip().startswith("[")],
            "seconds": round(time.time() - started, 1)}


def push(local_png: Path, rel_dir: str) -> tuple[bool, str]:
    """Copy the finished sheet back, and SAY WHY if it does not land.

    A silent False here cost real diagnosis time: a clip whose render succeeded was
    reported as failed with no reason, and the receipt said ok. One retry, because
    a single scp over a LAN is not a verdict, and the error text either way.
    """
    for attempt in (1, 2):
        made = ssh(f"mkdir -p '{SHEETS}/{rel_dir}'", timeout=60)
        if made.returncode != 0:
            if attempt == 2:
                return False, f"mkdir failed: {made.stderr.strip()[:120]}"
            time.sleep(2)
            continue
        # The sidecar travels with the sheet. A PNG without its cell geometry and
        # anchors cannot be sliced by an engine, so shipping one without the other
        # is shipping half the deliverable — and the far side had 185 of them.
        payload = [str(local_png)]
        sidecar = local_png.with_suffix(".json")
        if sidecar.is_file():
            payload.append(str(sidecar))
        copy = subprocess.run(
            ["scp", "-q", *payload, f"{HOST}:{SHEETS}/{rel_dir}/"],
            capture_output=True, text=True,
            env={**__import__("os").environ, "SSH_AUTH_SOCK": ""})
        if copy.returncode == 0:
            return True, ""
        if attempt == 2:
            return False, f"scp exit {copy.returncode}: {copy.stderr.strip()[:140]}"
        time.sleep(2)
    return False, "unreachable"


def audit(row, clips, sheets, receipts_for_asset, actions_in_file=None,
          total_clips=None) -> list[str]:
    """Check each asset AS IT LANDS, against what the asset actually contains.

    A batch that only reports timings is worthless for finding gaps: it cannot
    tell "rendered everything this asset has" from "rendered the one thing it
    happened to notice". So every asset is compared against its own contents and
    against what the catalogue claims about it, and disagreements are printed the
    moment they occur rather than discovered in a log afterwards.

    The most valuable check is the third one. An index that says `animated` while
    the file exposes no motion clip is exactly the NLA-strip failure that made
    rigged characters render as bind poses — silent, plausible, and wrong.
    """
    gaps = []
    motion = [c for c in clips if not c["pose"]]

    # The file's own action count versus what was recognised. A rooster with
    # eleven animations once reported one clip and thirteen "poses", because
    # Action.frame_range lies about slotted actions — and nothing compared the two
    # numbers, so the audit called it fine.
    # Compare TOTAL clips recognised against the file's actions. Comparing motion
    # clips instead flags every genuine single-frame pose as a missing animation,
    # which is a checker that cries wolf — worse than no checker.
    recognised = total_clips if total_clips is not None else len(clips)
    if actions_in_file and recognised < actions_in_file:
        gaps.append(f"{recognised} clips recognised from {actions_in_file} actions "
                    "in the file — some are not being read")
    if actions_in_file and actions_in_file > 2 and len(motion) <= 1:
        gaps.append(f"{actions_in_file} actions but only {len(motion)} motion clip — "
                    "ranges may be collapsing to single frames")

    if motion and len(sheets) < len(motion):
        missing = [c["name"] for c in motion if safe_name(c["name"]) not in sheets]
        gaps.append(f"only {len(sheets)}/{len(motion)} clips rendered; missing "
                    f"{', '.join(missing[:3])}")

    if str(row.get("animated", "")).strip().lower() in ("1", "true", "yes") and not motion:
        gaps.append("catalogue says ANIMATED but no motion clip was found "
                    "(NLA strips? unassigned action?)")

    if str(row.get("rig", "")).strip().lower() in ("1", "true", "yes") and not motion:
        gaps.append("rigged but rendered as a still — check whether its animation "
                    "lives somewhere this reader misses")

    for entry in receipts_for_asset:
        for line in entry.get("checks", []):
            if line.startswith("[FAIL"):
                gaps.append(f"QA {entry.get('clip', 'sheet')}: {line[7:].strip()}")
    return gaps


def single_instance():
    """Refuse to start if another batch is already running.

    Five orphaned supervisors accumulated in one session, each from a separate
    `nohup ... &` whose parent shell exited and left it reparented to init. They
    kept spawning Blender, held the machine while the creator needed it, and their
    contention produced render failures I attributed to the assets.

    An exclusive lock held for the process's lifetime makes a second batch
    impossible rather than merely discouraged, and the PID in the file makes the
    survivor identifiable instead of anonymous.
    """
    import fcntl
    path = Path("/tmp/tessera-batch.lock")
    handle = path.open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        existing = ""
        try:
            existing = Path("/tmp/tessera-batch.lock").read_text().strip()
        except OSError:
            pass
        raise SystemExit(
            f"another batch is already running{f' (pid {existing})' if existing else ''} — "
            "stop it first; this one skips finished work so nothing is lost")
    handle.write(str(os.getpid()))
    handle.flush()
    return handle          # held for the lifetime of the process


def main() -> int:
    _lock = single_instance()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--filter", default="")
    ap.add_argument("--size", type=int, default=384)
    ap.add_argument("--yaws", type=int, default=8)
    ap.add_argument("--frames", type=int, default=8)
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--min-swap", type=float, default=1.0,
                    help="pause below this many GB of free swap")
    args = ap.parse_args()

    CACHE.mkdir(parents=True, exist_ok=True)
    assets = remote_assets(args.limit, args.filter)
    print(f"{len(assets)} assets · render here · sheets -> {HOST}:{SHEETS}\n")

    done = failed = skipped = gaps = 0
    receipts = ROOT / "out" / "remote_batch.jsonl"
    receipts.parent.mkdir(parents=True, exist_ok=True)

    with receipts.open("a") as ledger:
        for index, row in enumerate(assets, 1):
            rel = row["rel"]
            stem = Path(rel).with_suffix("")
            available, swap_free = headroom()
            if swap_free < args.min_swap:
                print(f"paused: swap free {swap_free:.2f} GB below {args.min_swap} GB")
                break

            probe = ssh(f"ls '{SHEETS}/{stem}'/*.png 2>/dev/null | head -1", timeout=60)
            if probe.stdout.strip():
                skipped += 1
                continue

            print(f"[{index}/{len(assets)}] {row['name'][:44]}", flush=True)
            blend = fetch(rel)
            if blend is None:
                failed += 1
                ledger.write(json.dumps({"asset": rel, "ok": False, "stage": "fetch"}) + "\n")
                print("    could not fetch", flush=True)
                continue

            # First pass renders the default clip AND reports what else exists.
            clips_json = CACHE / "clips.json"
            clips_json.unlink(missing_ok=True)
            first = CACHE / "out" / "first.png"
            outcome = render_adaptive(blend, None, first, args.size, args.yaws,
                                      args.frames, args.timeout, clips_out=clips_json)
            outcome["asset"] = rel

            clips, actions_in_file, total_clips = [], None, None
            if clips_json.exists():
                try:
                    # A clip list that cannot be read is not the same as an asset
                    # with no clips, and conflating them blames the file.
                    payload = json.loads(clips_json.read_text(
                        encoding="utf-8", errors="replace"))
                    total_clips = len(payload["clips"])
                    clips = [c for c in payload["clips"] if not c["pose"]]
                    actions_in_file = payload.get("actions_in_file")
                except Exception as error:
                    clips = []
                    print(f"    clip list unreadable: {error}"[:110], flush=True)

            asset_ok = False
            produced, asset_receipts = [], []
            if outcome["ok"]:
                label = safe_name(clips[0]["name"]) if clips else "still"
                named = first.with_name(f"{label}.png")
                first.replace(named)
                first_side = first.with_suffix(".json")
                if first_side.is_file():
                    first_side.replace(named.with_suffix(".json"))
                asset_ok, push_error = push(named, str(stem))
                if not asset_ok:
                    outcome["push_error"] = push_error
                named.unlink(missing_ok=True)
                if asset_ok:
                    produced.append(label)
                outcome["clip"] = label
                asset_receipts.append(outcome)
                print(f"    {label[:34]:36} {outcome['seconds']}s", flush=True)

                # Every remaining animation gets its own sheet: a character with a
                # walk, a run and an idle is three sheets, not one.
                for clip in clips[1:]:
                    label = safe_name(clip["name"])
                    extra = CACHE / "out" / f"{label}.png"
                    more = render_adaptive(blend, clip["name"], extra, args.size,
                                           args.yaws, args.frames, args.timeout)
                    more["asset"], more["clip"] = rel, label
                    pushed, push_error = (push(extra, str(stem)) if more["ok"]
                                          else (False, "render failed"))
                    if pushed:
                        produced.append(label)
                        reduced = more.get("reduced_frames")
                        suffix = f"  ({reduced}f — clip is slow)" if reduced else ""
                        print(f"    {label[:34]:36} {more['seconds']}s{suffix}", flush=True)
                    else:
                        asset_ok = False
                        more["push_error"] = push_error
                        print(f"    {label[:34]:36} FAILED — {push_error[:52]}", flush=True)
                    asset_receipts.append(more)
                    ledger.write(json.dumps(more) + "\n")
                    extra.unlink(missing_ok=True)

            findings = audit(row, clips, produced, asset_receipts, actions_in_file,
                             total_clips)
            if findings:
                gaps += len(findings)
                for finding in findings:
                    print(f"    GAP  {finding}"[:118], flush=True)
            elif asset_ok:
                print(f"    audit ok — {len(produced)} sheet(s), "
                      f"{len(clips)} clip(s) in file", flush=True)

            if asset_ok and not findings:
                done += 1
            else:
                failed += 1
                if not asset_ok and not outcome.get("ok"):
                    # Only report the render's own error. Saying "push failed" when
                    # a different clip failed earlier sends the reader hunting the
                    # wrong problem.
                    print(f"    FAILED  {outcome.get('error', 'no output')}"[:110], flush=True)
            outcome["clips_found"] = [c["name"] for c in clips]
            outcome["gaps"] = findings
            ledger.write(json.dumps(outcome) + "\n")
            ledger.flush()
            first.unlink(missing_ok=True)
            blend.unlink(missing_ok=True)      # one asset on disk at a time


    print(f"\nclean {done}   with gaps or failures {failed}   "
          f"already present {skipped}   gaps found {gaps}")
    print(f"receipts: {receipts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
