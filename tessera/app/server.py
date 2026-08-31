"""Tessera Studio — the standalone app, on the standard library alone.

A browser UI served by `http.server`, because that is the only cross-platform GUI
this project can ship without acquiring a dependency it spent the whole build
avoiding. The kernel is dependency-free, the sheet driver is dependency-free, the
PNG encoder is dependency-free; a GUI toolkit would be the first thing in the
stack that has to be installed, on the machine least likely to tolerate it
(Blender's bundled Python, a locked-down workstation, a CI box).

It binds to 127.0.0.1 only. This serves a local library and shells out to a render
host; it is not something to expose.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..config import Config
from ..jobs import Runner, build_sheet_from
from ..library import provider_for, search
from ..lighting import PRESETS, LightingProfile
from ..tilesets import PALETTES, available

HERE = Path(__file__).resolve().parent
STATE: dict = {"jobs": {}, "counter": 0}


def _library_cache(config, force=False):
    if force or "assets" not in STATE:
        provider = provider_for(config.library(), config.host, force)
        STATE["assets"] = list(provider.assets())
    return STATE["assets"]


class Handler(BaseHTTPRequestHandler):
    config: Config

    def log_message(self, *args):                       # quiet; the UI is the log
        pass

    # -- plumbing ------------------------------------------------------------
    def _send(self, code, body, ctype="application/json"):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _file(self, path: Path):
        if not path.is_file():
            return self._send(404, {"error": "not found"})
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self._send(200, path.read_bytes(), ctype)

    # -- routes --------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                return self._file(HERE / "ui.html")
            if url.path == "/api/bootstrap":
                config = self.config
                return self._send(200, {
                    "source": getattr(config, "source", "?"),
                    "libraries": [lib.name for lib in config.libraries],
                    "host": {"kind": config.host.kind, "name": config.host.ssh_host or "local"},
                    "profiles": sorted(PRESETS),
                    "tilesets": sorted(available()),
                    "palettes": sorted(PALETTES),
                    "out_dir": str(Path(config.out_dir).expanduser()),
                    "defaults": {"profile": config.default_profile,
                                 "tileset": config.default_tileset},
                })
            if url.path == "/api/search":
                assets = _library_cache(self.config, query.get("refresh") == "1")
                def flag(name):
                    value = query.get(name)
                    return None if value in (None, "", "any") else value == "1"
                found = search(_Static(assets), query.get("q", ""),
                               rig=flag("rig"), animated=flag("animated"),
                               top=query.get("top") or None,
                               max_faces=int(query["max_faces"]) if query.get("max_faces") else None,
                               limit=int(query.get("limit", 60)))
                return self._send(200, {"count": len(found), "assets": [
                    {"name": a.name, "path": str(a.path), "category": a.category,
                     "top": a.top, "rig": a.rig, "animated": a.animated,
                     "faces": a.faces, "license": a.license} for a in found]})
            if url.path == "/api/job":
                return self._send(200, STATE["jobs"].get(query.get("id"), {"state": "unknown"}))
            if url.path == "/api/tops":
                tops = sorted({a.top for a in _library_cache(self.config) if a.top})
                return self._send(200, {"tops": tops})
            if url.path.startswith("/out/"):
                return self._file(Path(self.config.out_dir).expanduser() / url.path[5:])
            return self._send(404, {"error": "no route"})
        except Exception:
            return self._send(500, {"error": traceback.format_exc(limit=3)})

    def do_POST(self):
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if url.path != "/api/render":
            return self._send(404, {"error": "no route"})
        STATE["counter"] += 1
        job_id = f"job{STATE['counter']:04d}"
        STATE["jobs"][job_id] = {"state": "queued", "log": "", "spec": body}
        threading.Thread(target=_run_job, args=(self.config, job_id, body),
                         daemon=True).start()
        return self._send(200, {"id": job_id})


class _Static:
    def __init__(self, assets): self._assets = assets
    def assets(self): return iter(self._assets)


def _run_job(config: Config, job_id: str, spec: dict) -> None:
    job = STATE["jobs"][job_id]
    try:
        job["state"] = "capturing"
        preview = bool(spec.get("preview"))
        size = int(spec.get("size", 512)) if not preview else 192
        yaws = int(spec.get("yaws", 8)) if not preview else int(spec.get("preview_yaws", 1))
        frames = int(spec.get("frames", 8))
        stem = f"{job_id}-{'preview' if preview else 'sheet'}"

        runner = Runner(config.host, config.out_dir)
        options = {
            "yaws": yaws, "frames": frames, "size": size,
            "profile": spec.get("profile", "studio"),
            "center": spec.get("center", "root"),
            "root-motion": spec.get("root_motion", "strip"),
            "elevation": spec.get("elevation", 30.0),
            "loop": 1 if spec.get("loop", True) else 0,
            "phase": spec.get("phase", 0.0),
            "speed": spec.get("speed", 1.0),
            "ambient": spec.get("ambient"), "key": spec.get("key"),
            "fill": spec.get("fill"), "rim": spec.get("rim"),
            "exposure": spec.get("exposure"),
            "start": spec.get("start"), "end": spec.get("end"),
            "fps": spec.get("target_fps"),
            "samples": 16 if preview else spec.get("samples"),
        }
        result = runner.capture(spec["path"], stem, options)
        job["log"] = result.log
        job["seconds"] = round(result.seconds, 1)
        if not result.ok:
            job["state"] = "failed"
            return

        job["state"] = "packing"
        out_stem = Path(config.out_dir).expanduser() / stem
        png, meta = build_sheet_from(
            result.frames, out_stem,
            tileset=spec.get("tileset", config.default_tileset),
            quality=spec.get("quality", "draft" if preview else "standard"),
            anchor=spec.get("anchor", "feet"), capture_size=size,
            scale=int(spec.get("scale", 1)), palette=spec.get("palette") or None)
        job.update(state="done", png=f"/out/{png.name}", qa=meta["qa"],
                   qa_passed=meta["qa_passed"], grid=meta["grid"],
                   sheet=meta["sheet"], cell=meta["cell"])
    except Exception:
        job["state"] = "failed"
        job["log"] = (job.get("log", "") + "\n" + traceback.format_exc())[-6000:]


def serve(config: Config, port: int = 8733, open_browser: bool = True) -> None:
    Handler.config = config
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"Tessera Studio — {url}")
    print(f"  config {getattr(config, 'source', '?')}")
    print(f"  host   {config.host.kind} {config.host.ssh_host or 'local'}")
    print("  ctrl-c to stop")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
