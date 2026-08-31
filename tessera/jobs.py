"""Running a capture, wherever Blender actually lives.

The render host is configuration, not an assumption. On this workstation Blender
runs on a Linux box over SSH while the app runs on the Mac; on someone else's it
is the same machine. Both go through one interface so the app never branches on
where the work happens.

Remote runs stage the code before every job. That is deliberate: a remote host
holding a stale copy of the capture script produces output that disagrees with
the local sheet driver in ways that look like asset problems.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

LOCAL_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class JobResult:
    ok: bool
    log: str
    frames: Path | None = None
    seconds: float = 0.0
    meta: dict = field(default_factory=dict)


class Runner:
    def __init__(self, host, out_dir: Path):
        self.host = host
        self.out_dir = Path(out_dir).expanduser()
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # -- placement -----------------------------------------------------------
    def stage(self) -> None:
        if self.host.kind != "ssh":
            return
        target = f"{self.host.ssh_host}:{self.host.workdir.rstrip('/')}/"
        subprocess.run(["rsync", "-a", "--exclude", "out", "--exclude", "__pycache__",
                        "--exclude", "vendor-kernel", f"{LOCAL_ROOT}/", target],
                       check=True, capture_output=True)

    def _remote(self, command: str) -> list[str]:
        env = " ".join(f"{k}={shlex.quote(str(v))}" for k, v in (self.host.env or {}).items())
        # A quoted "~" is a literal directory name, not the home directory, so the
        # tilde is handed to the remote shell as $HOME instead of being shipped
        # inside quotes where it can never expand.
        workdir = self.host.workdir
        remote_dir = ("$HOME" + shlex.quote(workdir[1:]) if workdir.startswith("~")
                      else shlex.quote(workdir))
        return ["ssh", "-n", "-o", "BatchMode=yes", self.host.ssh_host,
                f"cd {remote_dir} && {env} {command}".strip()]

    # -- work ----------------------------------------------------------------
    def capture(self, blend: str, out_name: str, options: dict) -> JobResult:
        started = time.time()
        self.stage()
        remote_out = f"out/{out_name}.tsf"
        flags: list[str] = []
        for key, value in options.items():
            if value is None or value == "":
                continue
            flags += [f"--{key}", str(value)]

        script = "tessera/blender/capture.py"
        argv = ([self.host.blender, "--background", "--factory-startup", blend,
                 "--python", script, "--", "--out", remote_out] + flags)

        if self.host.kind == "ssh":
            command = " ".join(shlex.quote(part) for part in argv)
            proc = subprocess.run(self._remote(command), capture_output=True, text=True)
        else:
            env = {**dict(self.host.env or {})}
            proc = subprocess.run(argv, capture_output=True, text=True, cwd=LOCAL_ROOT,
                                  env={**__import__("os").environ, **env})

        log = "\n".join(line for line in (proc.stdout + proc.stderr).splitlines()
                        if not line.startswith(("Fra:", "Read blend", "  File \"/usr/share")))
        if proc.returncode != 0:
            return JobResult(False, log, seconds=time.time() - started)

        local = self.out_dir / f"{out_name}.tsf"
        if self.host.kind == "ssh":
            fetch = subprocess.run(
                ["scp", "-q", f"{self.host.ssh_host}:{self.host.workdir}/{remote_out}",
                 str(local)], capture_output=True, text=True)
            if fetch.returncode != 0:
                return JobResult(False, log + "\n" + fetch.stderr, seconds=time.time() - started)
        else:
            local = LOCAL_ROOT / remote_out

        return JobResult(True, log, frames=local, seconds=time.time() - started)


def build_sheet_from(frames_path: Path, out_stem: Path, *, tileset: str, quality: str,
                     anchor: str, capture_size: int, scale: int = 1, palette=None):
    """Convert captured frames into a delivered sheet, gated on QA."""
    from .frames import read_views
    from .png import write_rgba
    from .qa import inspect
    from .sheet import build_sheet, sprite_settings
    from .tilesets import PALETTES, columns_for, load

    views = read_views(frames_path)
    bundle = load(tileset)
    extra = {}
    if palette:
        extra = dict(color_mode="PALETTE", palette=[tuple(c) for c in PALETTES[palette]])
    settings = sprite_settings(
        bundle, columns=columns_for(capture_size, quality, bundle.kernel.cell_width), **extra)
    width, height, pixels, meta = build_sheet(
        views, bundle=bundle, settings=settings, anchor=anchor,
        layout="direction_rows", scale=scale, fill_mode="solid")

    findings = inspect(pixels, width, height, meta)
    meta["qa"] = [{"check": f.check, "ok": f.ok, "detail": f.detail} for f in findings]
    meta["qa_passed"] = all(f.ok for f in findings)

    png = write_rgba(out_stem.with_suffix(".png"), width, height, pixels)
    out_stem.with_suffix(".json").write_text(json.dumps(meta, indent=2))
    return png, meta
