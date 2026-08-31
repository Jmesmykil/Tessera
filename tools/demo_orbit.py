"""End-to-end demonstration: a 3D form, orbited, through the kernel, onto a sheet.

The subject here is a placeholder — a few boxes assembled into something with a
readable front, back, left and right — and it is a placeholder ON PURPOSE. The
production front end is the host DCC: Blender and Unity already render a model
with its real materials, textures and lighting, and hand those pixels to the same
kernel. What this file supplies is the one thing the driver needs and no host has
wired yet: views that actually differ by direction and by animation frame.

So the projector below is small and real rather than large and fake. Orthographic,
because that is what a sprite sheet wants — perspective would make the same subject
a different size in different cells and break the uniform-cell invariant on purpose.
Painter's algorithm over flat-shaded quads, because depth order is the only 3D
property the sheet driver can be wrong about.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tessera.png import write_rgba
from tessera.sheet import View, build_sheet, sprite_settings
from tessera.kernel_link import open_kernel

# name: (centre x,y,z), (size x,y,z), rgb
PARTS = [
    ("torso", (0.0, 0.10, 0.0), (0.44, 0.52, 0.26), (0.85, 0.24, 0.28)),
    ("head",  (0.0, 0.52, 0.0), (0.30, 0.30, 0.28), (0.94, 0.80, 0.62)),
    ("pack",  (0.0, 0.14, -0.20), (0.30, 0.34, 0.14), (0.20, 0.36, 0.62)),
    ("visor", (0.0, 0.55, 0.15), (0.22, 0.09, 0.04), (0.15, 0.85, 0.90)),
    ("legL",  (-0.12, -0.32, 0.0), (0.15, 0.34, 0.16), (0.24, 0.26, 0.32)),
    ("legR",  (0.12, -0.32, 0.0), (0.15, 0.34, 0.16), (0.24, 0.26, 0.32)),
]

FACES = [  # (normal, the four corner sign-triples)
    ((0, 0, 1),  ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1))),
    ((0, 0, -1), ((1, -1, -1), (-1, -1, -1), (-1, 1, -1), (1, 1, -1))),
    ((1, 0, 0),  ((1, -1, 1), (1, -1, -1), (1, 1, -1), (1, 1, 1))),
    ((-1, 0, 0), ((-1, -1, -1), (-1, -1, 1), (-1, 1, 1), (-1, 1, -1))),
    ((0, 1, 0),  ((-1, 1, 1), (1, 1, 1), (1, 1, -1), (-1, 1, -1))),
    ((0, -1, 0), ((-1, -1, -1), (1, -1, -1), (1, -1, 1), (-1, -1, 1))),
]

LIGHT = (-0.42, 0.80, 0.43)


def render_view(size: int, yaw: float, lift: float) -> list[float]:
    """Orthographic, flat-shaded, painter-sorted. Returns RGBA 0..1."""
    pixels = [0.0] * (size * size * 4)
    depth_sorted = []
    cy, sy = math.cos(yaw), math.sin(yaw)

    for name, (cx, cyy, cz), (sx, syy, sz), rgb in PARTS:
        bob = lift if name in ("legL", "torso", "head", "pack", "visor") else 0.0
        swing = lift * (1.0 if name == "legL" else -1.0) if name in ("legL", "legR") else 0.0
        for normal, corners in FACES:
            pts = []
            for ox, oy, oz in corners:
                x = cx + ox * sx / 2 + swing * 0.5
                y = cyy + oy * syy / 2 + bob
                z = cz + oz * sz / 2
                rx, rz = x * cy + z * sy, -x * sy + z * cy
                pts.append((rx, y, rz))
            nx, ny, nz = normal
            rnx, rnz = nx * cy + nz * sy, -nx * sy + nz * cy
            depth = sum(p[2] for p in pts) / 4.0
            lam = max(0.0, rnx * LIGHT[0] + ny * LIGHT[1] + rnz * LIGHT[2])
            shade = 0.32 + 0.68 * lam
            depth_sorted.append((depth, pts, tuple(min(1.0, c * shade) for c in rgb)))

    depth_sorted.sort(key=lambda item: item[0])          # far to near
    half = size / 2.0
    scale = size * 0.40

    for _, pts, colour in depth_sorted:
        screen = [(half + p[0] * scale, half - p[1] * scale) for p in pts]
        xs = [p[0] for p in screen]; ys = [p[1] for p in screen]
        x0, x1 = max(0, int(min(xs))), min(size - 1, int(max(xs)) + 1)
        y0, y1 = max(0, int(min(ys))), min(size - 1, int(max(ys)) + 1)
        for py in range(y0, y1 + 1):
            for px in range(x0, x1 + 1):
                if _inside(screen, px + 0.5, py + 0.5):
                    o = (py * size + px) * 4
                    pixels[o:o + 4] = [*colour, 1.0]
    return pixels


def _inside(poly, x, y) -> bool:
    sign = 0
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        cross = (bx - ax) * (y - ay) - (by - ay) * (x - ax)
        if cross == 0:
            continue
        s = 1 if cross > 0 else -1
        if sign == 0:
            sign = s
        elif s != sign:
            return False
    return True


def main() -> int:
    yaws, frames, size = 8, 4, 56
    out = Path.home() / "Tessera" / "out"
    bundle = open_kernel()
    settings = sprite_settings(bundle, columns=18)

    t0 = time.time()
    views = []
    for yi in range(yaws):
        yaw = yi * (2 * math.pi / yaws)
        for fi in range(frames):
            lift = 0.045 * math.sin(fi * (2 * math.pi / frames))
            views.append(View(render_view(size, yaw, lift), size, size,
                              yaw_index=yi, frame_index=fi,
                              yaw_degrees=round(math.degrees(yaw), 2), frame_number=fi))
    t_render = time.time() - t0

    t1 = time.time()
    w, h, pixels, meta = build_sheet(views, bundle=bundle, settings=settings,
                                     anchor="feet", layout="direction_rows", scale=2)
    t_sheet = time.time() - t1

    png = write_rgba(out / "tessera-orbit-demo.png", w, h, pixels)
    (out / "tessera-orbit-demo.json").write_text(json.dumps(meta, indent=2))

    opaque = sum(1 for i in range(w * h) if pixels[i * 4 + 3] > 0)
    print(f"views      {len(views)}  ({yaws} yaws x {frames} frames, {size}x{size} each)")
    print(f"grid       {meta['grid']['rows']} rows x {meta['grid']['columns']} cols")
    print(f"cell       {meta['cell']['width_px']}x{meta['cell']['height_px']} px"
          f"   anchor at +{meta['cell']['anchor_x_px']},+{meta['cell']['anchor_y_px']}")
    print(f"sheet      {w}x{h} px   {opaque} opaque px ({100*opaque/(w*h):.1f}%)")
    print(f"empty      {sum(1 for f in meta['frames'] if f['empty'])} of {len(meta['frames'])} cells")
    print(f"timing     project {t_render:.2f}s   convert+pack+render {t_sheet:.2f}s")
    print(f"digest     {meta['content_digest'][:16]}")
    print(f"png        {png}  ({png.stat().st_size} bytes)")
    subprocess.run(["open", "-R", str(png)], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
