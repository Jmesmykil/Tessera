"""Automatic sheet inspection, so a broken sheet never reaches a person.

Written after handing over a Ninja Girl sheet whose second, third and fourth
columns were nearly empty — the animation walked the subject out of a camera
that had been aimed once, at frame one. It was obvious in the image and it should
never have been a human's job to notice.

Every check below is a property a correct sheet has and a broken one does not, so
each one can FAIL rather than merely report. The thresholds are deliberately
loose: this is here to catch a sheet that is wrong, not to arbitrate taste.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Finding:
    check: str
    ok: bool
    detail: str

    def __str__(self) -> str:
        return f"  [{'PASS' if self.ok else 'FAIL'}] {self.check:22} {self.detail}"


def _cell_coverage(pixels, width, meta) -> list[tuple[dict, float]]:
    cw = meta["cell"]["width_px"]
    ch = meta["cell"]["height_px"]
    out = []
    for frame in meta["frames"]:
        x0, y0 = frame["x_px"], frame["y_px"]
        opaque = 0
        for y in range(y0, y0 + ch):
            row = y * width
            for x in range(x0, x0 + cw):
                if pixels[(row + x) * 4 + 3] > 0.0:
                    opaque += 1
        out.append((frame, opaque / float(cw * ch)))
    return out


def inspect(pixels, width, height, meta, *, min_coverage=0.02,
            max_coverage_ratio=6.0, max_anchor_drift_px=0) -> list[Finding]:
    findings: list[Finding] = []
    coverage = _cell_coverage(pixels, width, meta)
    values = [c for _, c in coverage]

    empty = [f["frame_index"] for f, c in coverage if c < min_coverage]
    findings.append(Finding(
        "cells non-empty", not empty,
        f"{len(values) - len(empty)}/{len(values)} cells carry subject" +
        (f"; empty at frame_index {sorted(set(empty))}" if empty else "")))

    lo, hi = min(values), max(values)
    ratio = (hi / lo) if lo > 0 else float("inf")
    findings.append(Finding(
        "coverage consistent", ratio <= max_coverage_ratio,
        f"min {lo:.3f} max {hi:.3f} ratio {ratio:.1f}x (limit {max_coverage_ratio}x)"))

    # The anchor must land on the same spot inside every cell — that is the whole
    # promise of the sheet, and it is cheap to verify rather than trust.
    offsets = {(f["anchor_px"]["x"] - f["x_px"], f["anchor_px"]["y"] - f["y_px"])
               for f in meta["frames"]}
    findings.append(Finding(
        "anchor stable", len(offsets) == 1,
        f"{len(offsets)} distinct in-cell anchor offset(s)" +
        ("" if len(offsets) == 1 else f": {sorted(offsets)[:4]}")))

    inside = all(f["bbox_px"] is None or (
        f["bbox_px"]["x"] >= f["x_px"] and f["bbox_px"]["y"] >= f["y_px"] and
        f["bbox_px"]["x"] + f["bbox_px"]["width"] <= f["x_px"] + meta["cell"]["width_px"] and
        f["bbox_px"]["y"] + f["bbox_px"]["height"] <= f["y_px"] + meta["cell"]["height_px"])
        for f in meta["frames"])
    findings.append(Finding("subject inside cell", inside,
                            "every bbox fits its cell" if inside else "a bbox escapes its cell"))

    # A sheet where every direction looks identical means the orbit never moved.
    per_yaw: dict[int, list[float]] = {}
    for frame, c in coverage:
        per_yaw.setdefault(frame["yaw_index"], []).append(c)
    means = [sum(v) / len(v) for v in per_yaw.values()]
    spread = (max(means) - min(means)) if len(means) > 1 else 1.0
    findings.append(Finding(
        "orbit varies", spread > 1e-4 or len(means) <= 1,
        f"{len(means)} yaw(s), coverage spread {spread:.4f}"))

    # Duplicate cells: the creator spotted these by eye before any check existed.
    # Frames sampled past the end of an action all return the held final pose, so
    # identical neighbours within a row are the signature of a bad sample window.
    cw, ch = meta["cell"]["width_px"], meta["cell"]["height_px"]
    digests: dict[tuple[int, int], int] = {}
    for frame in meta["frames"]:
        x0, y0 = frame["x_px"], frame["y_px"]
        acc = 0
        for y in range(y0, y0 + ch, 2):
            row = y * width
            for x in range(x0, x0 + cw, 2):
                o = (row + x) * 4
                acc = (acc * 31 + int(pixels[o] * 255) * 7
                       + int(pixels[o + 3] * 255)) & 0xFFFFFFFF
        digests[(frame["yaw_index"], frame["frame_index"])] = acc
    per_yaw: dict[int, list[int]] = {}
    for (yaw_index, _), value in digests.items():
        per_yaw.setdefault(yaw_index, []).append(value)
    dupes = sum(len(v) - len(set(v)) for v in per_yaw.values())
    findings.append(Finding(
        "frames distinct", dupes == 0,
        f"{dupes} duplicate frame(s) across {len(per_yaw)} yaw row(s)" +
        ("" if dupes == 0 else " — samples are probably running past the action's end")))

    opaque_total = sum(1 for i in range(width * height) if pixels[i * 4 + 3] > 0.0)
    lit = sum(1 for i in range(width * height)
              if pixels[i * 4 + 3] > 0.0 and max(pixels[i * 4:i * 4 + 3]) > 0.06)
    share = lit / opaque_total if opaque_total else 0.0
    findings.append(Finding(
        "not crushed to black", share > 0.5,
        f"{share:.1%} of opaque pixels carry visible value (want >50%)"))

    return findings


def report(findings) -> bool:
    for finding in findings:
        print(finding)
    ok = all(f.ok for f in findings)
    print(f"  QA {'PASSED' if ok else 'FAILED'} — {sum(f.ok for f in findings)}/{len(findings)} checks")
    return ok
