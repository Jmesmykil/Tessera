# Tessera 0.1.0

3D models in, game-ready sprite sheets out. No image model anywhere in the path.

## What it does

Point it at a folder of `.blend` files. Pick a character; it loads and spins
immediately. Pick one of its animations, drag the light where you want it, and
render a sheet — eight directions by eight frames, or whatever you choose. Every
sheet is checked before you get it.

Rendering uses Blender, which you already have. Everything else — the quantiser,
the packer, the live 3D viewport, the quality checks — is a compiled kernel inside
the app.

## Why it exists

Three earlier attempts at a sprite generator died the same way: each needed an
image-generation model that was not available. Tessera needs none. It renders the
model you already own and quantises the result, so the output is deterministic,
reproducible, and yours.

## Output depth

Sheets are written as **16-bit RGBA PNG**. The capture is HDR float end to end
and three separate stages were flattening it: the writer emitted 8 bits and
clipped everything above 1.0 to white, the kernel quantised each cell's colour
to bytes so a 16-bit file was still an 8-bit picture, and the Unity capture
clamped derived colour into [0,1]. Alpha is coverage and belongs in that range;
colour is energy and does not.

The kernel's byte-exact colour is the ASCII contract and is gated by golden
vectors, so it did not move — a parallel unrounded field carries the float value
and a second renderer reads it. Measured on real element sheets, distinct
colours went from 32 to 75,894 on the flattest subject, and from 442 to 71,386
on another. Thirty-two colours was visible banding.

Where a subject's colour exceeds 1.0, the sheet is normalised so the peak lands
at 1.0 and the divisor is recorded in the sidecar as `encoding.energy_scale`.
Multiply the texel by it to recover the original range, so emissive subjects
keep their glow instead of arriving as a flat matte.

`--depth 8` remains available for engines that will not take a 16-bit texture,
and `--scale N` multiplies the canvas for high-resolution tiers — the element
sheets ship at both a 1:1 tier and a 4K tier of 3864-4536 px wide.

## Matting subjects that have no alpha

A material that writes emission but no coverage cannot be matted by rendering it
against two backgrounds: it reads the background back almost unchanged, so the
derived alpha collapses to zero everywhere. One real element did exactly this
and packed a full 56-view capture into a sheet with not a single inked pixel.

Rendered over black, such a subject reads exactly its own emission with nothing
of the background in it, which is already a valid matte — luminance becomes
coverage. It engages only when background differencing recovered under 0.5% of
the frame, and it logs when it does. A fallback that engages silently is the
failure it was written to catch.

## The parts that took the most getting right

**Colour comes from the model.** `color_mode=SOURCE` takes the alpha-masked
area-average of the source pixels under each cell. Blender's default `AgX` view
transform is turned off, because a filmic tonemap drains saturation by design and
guarantees the colour reaching the quantiser is not the colour the artist authored.

**Coverage comes from the silhouette, not the tone.** The kernel maps luminance to
glyph coverage, which is correct for ASCII art and wrong for sprites: a red torso
sits near 0.37 luminance and can never pick a solid tile, so it comes out dotted.
`fill_mode=solid` runs the kernel twice — a silhouette pass for coverage, an
alpha-masked colour pass for colour.

**One cell size, one anchor.** Every frame is measured, one cell is derived that
all of them fit, and each is pinned by its anchor rather than its bounding box.
`feet` is the centroid of the ink in the lowest row, not the box centre, because a
walk cycle leans and pinning a leaning body by its box slides the contact point
out from under it.

**Timing is float throughout.** Ranges are read from the animation's own keys,
never from the scene range or from `Action.frame_range` — both of which lie. Loops
drop the endpoint, because a cycle's last frame is its first.

**It does not look like ASCII unless you ask.** The default tile set is `pixel-hd`,
a 2×2 cell carrying all sixteen possible ink patterns, so silhouette reproduction
is lossless. Tile sets are data files; the text ramp is one option among them.

## Verification

The Rust core is proven equivalent to a Python reference at two levels: the
cross-host golden vector fixes one conversion to an exact glyph grid, and a full
sheet built from the same frames is raw-scanline identical between the two
implementations. Kernel fingerprint `374be5746ebac893…`, byte-identical on macOS
and Linux.

Every sheet is inspected before delivery: cells non-empty, coverage consistent,
anchor identical in every cell, subject inside its cell, orbit varies, frames
distinct, output not crushed to black. The inspector was verified against a
known-bad sheet, where it fails four of seven — a guard that passes everything is
worthless.

## Known limits

- Rendering requires Blender 4.2+ on `PATH`. The app does not bundle it.
- The macOS build is signed locally, not notarised, so first launch needs
  right-click → Open.
- The Blender and Unity editions are specified but not built.
- One Blender at a time. Concurrent headless renders fail, and on some GPU drivers
  they hang unkillably; the batch tools serialise for this reason.
