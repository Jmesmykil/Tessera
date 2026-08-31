"""`python3 -m tessera` — the app, and the same verbs without it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tessera.config import Config                              # noqa: E402
from tessera.library import provider_for, search                # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(prog="tessera", description="3D in, sprite sheets out.")
    sub = ap.add_subparsers(dest="cmd")

    studio = sub.add_parser("studio", help="open the app (default)")
    studio.add_argument("--port", type=int, default=8733)
    studio.add_argument("--no-browser", action="store_true")

    ls = sub.add_parser("library", help="list or search assets")
    ls.add_argument("query", nargs="?", default="")
    ls.add_argument("--rigged", action="store_true")
    ls.add_argument("--animated", action="store_true")
    ls.add_argument("--limit", type=int, default=40)

    sub.add_parser("config", help="show resolved configuration")
    sub.add_parser("doctor", help="check the render host and kernel are reachable")

    ap.add_argument("--config", default=None)
    args = ap.parse_args()
    config = Config.load(args.config)

    if args.cmd == "library":
        provider = provider_for(config.library(), config.host)
        found = search(provider, args.query,
                       rig=True if args.rigged else None,
                       animated=True if args.animated else None,
                       limit=args.limit)
        for asset in found:
            print(asset.label())
        print(f"\n{len(found)} shown from {config.library().root}")
        return 0

    if args.cmd == "config":
        print(f"source     {getattr(config, 'source', '?')}")
        print(f"host       {config.host.kind} {config.host.ssh_host or 'local'} env={config.host.env}")
        print(f"out_dir    {config.out_dir}")
        for lib in config.libraries:
            print(f"library    {lib.name}: {lib.root}"
                  f"{' (indexed)' if lib.index_csv else ' (walk)'}")
        return 0

    if args.cmd == "doctor":
        return doctor(config)

    from tessera.app.server import serve
    serve(config, port=getattr(args, "port", 8733),
          open_browser=not getattr(args, "no_browser", False))
    return 0


def doctor(config) -> int:
    """Check the things whose absence produces a confusing failure later."""
    import subprocess
    ok = True

    try:
        from tessera.kernel_link import open_kernel
        bundle = open_kernel()
        print(f"  ok    kernel {bundle.kernel.version} {bundle.kernel.fingerprint[:12]}")
    except Exception as exc:
        ok = False
        print(f"  FAIL  kernel — {exc}")

    lib = Path(config.library().root).expanduser()
    if config.host.kind == "ssh":
        probe = subprocess.run(["ssh", "-n", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                                config.host.ssh_host,
                                f"{config.host.blender} --version | head -1; "
                                f"test -d {lib} && echo LIBOK"],
                               capture_output=True, text=True)
        out = probe.stdout.strip()
        print(f"  {'ok  ' if 'Blender' in out else 'FAIL'}  host {config.host.ssh_host}: "
              f"{out.splitlines()[0] if out else probe.stderr.strip()[:60]}")
        print(f"  {'ok  ' if 'LIBOK' in out else 'FAIL'}  library {lib}")
        ok = ok and "Blender" in out and "LIBOK" in out
    else:
        found = subprocess.run([config.host.blender, "--version"],
                               capture_output=True, text=True)
        print(f"  {'ok  ' if found.returncode == 0 else 'FAIL'}  local blender")
        print(f"  {'ok  ' if lib.is_dir() else 'FAIL'}  library {lib}")
        ok = ok and found.returncode == 0 and lib.is_dir()

    print("  READY" if ok else "  NOT READY")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
