# Release and submission

Two channels, prepared together: a **GitHub repository** as the development and
source channel, and a **storefront listing** as the customer channel. The same
package manifest and evidence set backs both, so a claim made in a listing can be
checked against an artifact.

## Positioning

Tessera turns 3D models into game-ready sprite sheets. The distinguishing claim,
and the only one worth leading with, is that **no image-generation model is
involved**: it renders the model the customer already owns and quantises the
result. Output is deterministic, reproducible, and derived from their asset rather
than from a service.

Do not claim "first" or "only" without a dated marketplace search recorded
alongside the claim.

## What ships

- `TesseraStudio.dmg` — the macOS app, kernel embedded
- Source for the Rust core, the Flutter client, and the Blender capture scripts
- `release/PACKAGE-MANIFEST.json` — artifact checksums, kernel fingerprint,
  verification summary
- `release/RELEASE-NOTES.md`, `release/RIGHTS-NOTICE.md`
- `release/evidence/` — real delivered sheets, the demo video, checksums

## What does not ship, and why it matters

No 3D models, and no sprite sheets of third-party models. A sheet is a derivative
of the model it came from; the customer's sheets belong to the customer, and other
people's assets are not ours to redistribute. The demo material shows output, and
the listing must say plainly that assets are not included.

## Honest constraints for the listing

State these rather than let a customer discover them:

- **Blender 4.2+ is required** and is not bundled. Tessera drives it; it does not
  replace it.
- **macOS build is signed locally, not notarised.** First launch needs
  right-click → Open. Say so in the description, not only in the README.
- **Blender and Unity editions are specified, not built.** Do not list them.
- **One render at a time.** Concurrent headless Blender renders fail, and on some
  GPU drivers hang; the tools serialise deliberately.

## Copy

**Short.** 3D models in, game-ready sprite sheets out. Pick a character, pick an
animation, drag the light, render. No AI image generation — it renders your model
and quantises the result, so the output is deterministic and yours.

**Long.** Tessera loads a model and shows it immediately: spin it, scrub its
animation, drag the light and watch the shading change in real time — no round
trip, because the viewport is a compiled renderer inside the app. When it looks
right, render a sheet. Directions and frames are yours to choose; timing reads the
animation's own keys, so a cycle loops without a stuttered duplicate frame at the
seam. Every frame is placed on one cell size and pinned by an anchor, so a walk
cycle's feet stay planted instead of wandering. Colour comes from the model
itself. Every sheet is checked before you get it — cells non-empty, coverage
consistent, anchor stable, frames distinct — and a sheet that fails a check tells
you which one.

## Submission checklist

1. `cargo test -p tessera_core` — golden vector, fingerprint, cross-implementation
2. `python3 tests/test_sheet.py && python3 tests/test_timing.py` — 31 tests
3. `cd app && flutter analyze && flutter test`
4. Rebuild the DMG; verify checksum against `PACKAGE-MANIFEST.json`
5. Mount the DMG and launch the app from the image, not from the build tree
6. Confirm `release/evidence/` sheets came from a run whose QA passed
7. Record the dated marketplace search if any comparative claim is made
