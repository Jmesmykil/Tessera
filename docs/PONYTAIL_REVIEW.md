# Ponytail review

Scope: the kernel port, the sheet driver, the capture scripts, the live viewport,
the batch tools, and the client.

## What is shared rather than duplicated

- The kernel is **one compiled binary**, not one implementation per host. Flutter
  binds it through Dart FFI, Blender and Unity through the same C ABI. Three hosts
  cannot drift apart when there is only one thing to drift from — which is
  strictly stronger than the divergence gate it replaces.
- `sheet.rs` and `sheet.py` are proven equivalent, not assumed: the golden vector
  fixes the kernel and a full sheet from identical frames is raw-scanline
  identical between them. The Python is the oracle; the Rust is the product.
- Tile sets are **data**, not code paths. `text-ramp`, `quadrant-block` and
  `pixel-hd` are kernel payloads, so a new vocabulary costs a JSON file and a
  golden vector, never a branch in the selector.
- Anchoring has one implementation with three modes, and the modes differ only in
  where the point is taken from — not in how frames are placed.
- Colour has one path. `SOURCE`, `TINT`, `MONO` and `PALETTE` are the kernel's own
  four identities; the sprite preset selects among them rather than adding a fifth.
- Library discovery has one interface with two providers — a curated index and a
  plain directory walk — and both answer the same queries. Categories derive from
  whatever structure the user already has.
- Configuration resolves in one place through one precedence chain. Nothing in the
  code knows a path on anyone's machine.

## What was deliberately not added

- No second renderer. Blender renders; the kernel quantises; the viewport
  rasterises a decimated preview. Each exists because the others cannot do its job
  at its latency, and none duplicates another's output.
- No second wire format. `TSF1` carries frames from every host, and the preview
  mesh is a separate format only because it carries geometry rather than pixels.
- No vendored copy of the kernel reference. It is imported, and a missing one is a
  loud failure rather than a silent fallback to a stale duplicate.
- No image-generation dependency anywhere, which is the product's whole premise.
- No bundled Blender.

## Where the seams are honest

- `render_adaptive` retries at fewer frames when a sheet repeats itself. That is a
  policy wrapper around `render`, not a second render path.
- `stage_asset` and the remote fetch both exist because the library and the
  renderer can be on different machines. They converge on one local path before
  anything else runs.
- The batch's audit and the kernel's QA are separate on purpose: QA judges a
  sheet, the audit judges whether the right sheets exist at all. Merging them
  would let a reader bug validate itself.

## What the environment taught the design

A batch is not only a producer of output, it is a claimant on a shared machine.
Two properties turned out to be load-bearing and neither was obvious from the code:

- **Singleton by construction.** Five orphaned supervisors accumulated in one
  session, each from a `nohup` whose parent shell exited. A lock held for the
  process lifetime, with the pid written into it, removes the whole class.
- **A blank failure is a scheduling fact, not an asset fact.** Concurrent Blenders
  return nothing rather than erroring, so an empty error means the environment
  contaminated the measurement. Believing it blames the subject for the harness.

## Known unevenness, stated rather than hidden

- `capture.py` has grown large and now carries clip discovery, framing, lighting,
  timing and dependency repair. Each was added against a real defect, but it wants
  splitting along those lines before it grows again.
- The Python reference and the Rust core must be changed together. That is
  enforced by a test rather than by structure, and a structural guarantee would be
  better.
- The Unity package is written but untested; it should not be listed as shipping
  until it has run once.
- `remote_batch.py` and `batch.py` overlap. Only the remote one is current; the
  local one should be folded into it or removed rather than left to rot.
