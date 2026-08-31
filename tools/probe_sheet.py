#!/usr/bin/env python3
"""Read alpha out of a packed sheet, with no third-party decoder.

This is an INSTRUMENT, so it proves itself before it reports. `control()`
builds a PNG whose alpha is known before the reader ever runs — 25% clear,
25% opaque, a mid value, and a known corner — and refuses to read a real
sheet unless the reader recovers those exact numbers. An earlier audit in
this project compared two figures produced by the same broken reader and
called the result clean; a control is only a control when its value is
fixed in advance.
"""
import binascii, struct, sys, zlib
from pathlib import Path


def _chunk(tag: bytes, body: bytes) -> bytes:
    return (struct.pack(">I", len(body)) + tag + body
            + struct.pack(">I", binascii.crc32(tag + body) & 0xFFFFFFFF))


def encode(pixels, w, h, depth=8) -> bytes:
    """pixels: flat list of (r,g,b,a) tuples, row-major, samples in 0..maxval."""
    raw = bytearray()
    for y in range(h):
        raw.append(0)                      # filter type 0 (None)
        for x in range(w):
            px = pixels[y * w + x]
            if depth == 16:
                for s in px:
                    raw.extend(struct.pack(">H", s))
            else:
                raw.extend(px)
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, depth, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + _chunk(b"IEND", b""))


def decode(path):
    """Return (width, height, [(r,g,b,a)], maxval). 8- and 16-bit RGB/RGBA.

    Sixteen-bit is not optional here: Tessera writes 16-bit sheets by default,
    so a reader that handled only 8 bits would refuse — or worse, misread — the
    very output it exists to check."""
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    pos, idat, w = 8, bytearray(), None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if tag == b"IHDR":
            w, h, depth, colour, _, _, interlace = struct.unpack(">IIBBBBB", body)
            if depth not in (8, 16) or colour not in (2, 6) or interlace:
                raise ValueError(f"{path}: unsupported depth={depth} colour={colour}")
            channels = 4 if colour == 6 else 3
            # PNG filters operate on BYTES, so the per-pixel stride used by the
            # Sub/Paeth predictors is channels*2 at 16-bit, not channels.
            bpp = channels * (2 if depth == 16 else 1)
            maxval = 65535 if depth == 16 else 255
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
        pos += 12 + length
    if w is None:
        raise ValueError(f"{path}: no IHDR")

    raw = zlib.decompress(bytes(idat))
    stride = w * bpp
    out, prev = [], bytearray(stride)
    at = 0
    for _ in range(h):
        ftype = raw[at]; at += 1
        line = bytearray(raw[at:at + stride]); at += stride
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if ftype == 1:   line[i] = (line[i] + a) & 0xFF
            elif ftype == 2: line[i] = (line[i] + b) & 0xFF
            elif ftype == 3: line[i] = (line[i] + (a + b) // 2) & 0xFF
            elif ftype == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
            elif ftype != 0:
                raise ValueError(f"{path}: bad filter {ftype}")
        prev = line
        for x in range(w):
            chunk = line[x * bpp:(x + 1) * bpp]
            if depth == 16:
                px = [ (chunk[2*k] << 8) | chunk[2*k+1] for k in range(channels) ]
            else:
                px = list(chunk)
            out.append(tuple(px) if channels == 4 else (px[0], px[1], px[2], maxval))
    return w, h, out, maxval


def control():
    """Known-answer test. Its numbers are fixed HERE, before any read."""
    w = h = 8
    px = []
    for y in range(h):
        for x in range(w):
            if y < 2:    px.append((10, 20, 30, 0))      # 16 clear
            elif y < 4:  px.append((40, 50, 60, 255))    # 16 opaque
            elif y < 6:  px.append((70, 80, 90, 128))    # 16 mid
            else:        px.append((1, 2, 3, 77))        # 16 other
    tmp = Path("/private/tmp/claude-501/-Users-astral/probe-control.png")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    checks = {}
    for depth, mul in ((8, 1), (16, 257)):
        scaled = [tuple(s * mul for s in q) for q in px]
        tmp.write_bytes(encode(scaled, w, h, depth))
        gw, gh, got, maxval = decode(tmp)
        top = maxval
        checks[f"{depth}b size"]   = (gw, gh) == (8, 8)
        checks[f"{depth}b corner"] = got[0] == (10 * mul, 20 * mul, 30 * mul, 0)
        checks[f"{depth}b clear"]  = sum(1 for q in got if q[3] == 0) == 16
        checks[f"{depth}b opaque"] = sum(1 for q in got if q[3] == top) == 16
        checks[f"{depth}b mid"]    = sum(1 for q in got if q[3] == 128 * mul) == 16
        checks[f"{depth}b colour"] = got[16][:3] == (40 * mul, 50 * mul, 60 * mul)
        checks[f"{depth}b maxval"] = maxval == (65535 if depth == 16 else 255)
    tmp.unlink(missing_ok=True)
    bad = [k for k, ok in checks.items() if not ok]
    if bad:
        raise SystemExit(f"CONTROL FAILED on {bad} — the reader is wrong, "
                         "so nothing it says about a real sheet counts.")
    return checks


def report(path):
    w, h, px, maxval = decode(path)
    total = w * h
    clear = sum(1 for p in px if p[3] == 0)
    opaque = sum(1 for p in px if p[3] == maxval)
    inked = [p for p in px if p[3] > 0]
    hues = len({p[:3] for p in inked})
    return dict(name=Path(path).name, w=w, h=h, corner=px[0], depth=16 if maxval > 255 else 8,
                clear=100.0 * clear / total, opaque=100.0 * opaque / total,
                inked=len(inked), hues=hues)


if __name__ == "__main__":
    ok = control()
    print(f"control PASSED ({len(ok)} known values recovered)\n")
    print(f"{'sheet':34s} {'size':>12s} {'corner':>18s} {'clear%':>7s} {'opaque%':>8s} {'colours':>8s} {'bits':>5s}")
    for arg in sys.argv[1:]:
        r = report(arg)
        print(f"{r['name']:34s} {r['w']:5d}x{r['h']:<6d} {str(r['corner']):>18s} "
              f"{r['clear']:7.1f} {r['opaque']:8.1f} {r['hues']:8d} {r['depth']:5d}")
