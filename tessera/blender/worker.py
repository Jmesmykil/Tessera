"""A resident Blender, so a preview costs a render instead of a cold start.

  blender --background --factory-startup --python tessera/blender/worker.py

Every capture so far paid for a full Blender launch plus a file load — around ten
seconds for a small asset and close to a minute for a two-gigabyte one. That cost
is invisible in a batch and intolerable in a UI: dragging a light is worthless if
each nudge takes half a minute.

So the worker stays alive and, more importantly, KEEPS THE LAST .BLEND LOADED.
Changing only the light on an asset already in memory skips both the process start
and the file read, which is the case a person tuning a look actually hits.

Jobs arrive as JSON files rather than over a socket. A watched directory survives
a dropped SSH connection, needs no port, and leaves a readable trail of exactly
what was asked for — which matters more here than latency, since the render
dominates either way.
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tessera.blender import capture                            # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
JOBS_IN = ROOT / "jobs" / "in"
JOBS_OUT = ROOT / "jobs" / "out"
HEARTBEAT = ROOT / "jobs" / "worker.alive"

_loaded: str | None = None


def ensure_loaded(blend_path: str) -> bool:
    """Load the asset only when it changes. Returns True if a load happened."""
    global _loaded
    blend_path = capture.stage_asset(blend_path)
    if _loaded == blend_path:
        return False
    bpy.ops.wm.open_mainfile(filepath=blend_path)
    _loaded = blend_path
    return True


def handle(job: dict) -> dict:
    started = time.time()
    blend = capture.stage_asset(job.pop("blend"))
    reloaded = ensure_loaded(blend)
    # A fresh load is required whenever the previous job mutated the scene, which
    # every capture does: it adds a camera and lights and mutes NLA tracks. Re-open
    # unless the caller explicitly says the scene is still clean.
    if not reloaded and not job.pop("scene_is_clean", False):
        bpy.ops.wm.open_mainfile(filepath=blend)
    result = capture.run_capture({k: str(v) for k, v in job.items() if v is not None})
    return {"ok": result == 0, "seconds": round(time.time() - started, 2),
            "reloaded": reloaded}


def main() -> int:
    for directory in (JOBS_IN, JOBS_OUT):
        directory.mkdir(parents=True, exist_ok=True)
    HEARTBEAT.write_text(str(time.time()))
    print(f"tessera worker ready — watching {JOBS_IN}", flush=True)

    while True:
        HEARTBEAT.write_text(str(time.time()))
        jobs = sorted(JOBS_IN.glob("*.json"))
        if not jobs:
            time.sleep(0.25)
            continue
        for path in jobs:
            name = path.stem
            try:
                job = json.loads(path.read_text())
            except Exception:
                path.unlink(missing_ok=True)
                continue
            path.unlink(missing_ok=True)
            if job.get("command") == "quit":
                print("worker stopping", flush=True)
                return 0
            try:
                outcome = handle(job)
            except SystemExit as exit_error:
                outcome = {"ok": False, "error": str(exit_error)}
            except Exception:
                outcome = {"ok": False, "error": traceback.format_exc(limit=4)}
            (JOBS_OUT / f"{name}.json").write_text(json.dumps(outcome))
            print(f"job {name}: {'ok' if outcome.get('ok') else 'FAILED'} "
                  f"{outcome.get('seconds', '')}s", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
