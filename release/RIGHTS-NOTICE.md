# Rights notice

Copyright 2026 Jamesmykil Weber. All rights reserved.

The customer licence selected by the publisher on the distribution storefront
controls customer use and redistribution. This archive separately grants no right
to redistribute its contents outside that licence.

## What is in this package

Tessera's own source and the compiled kernel that runs it. Nothing else.

## What is deliberately excluded

**Source 3D models and their project files.** Tessera renders models it is pointed
at; it ships none. Every asset shown in the demo material belongs to its own
author under its own licence, and no asset is redistributed here.

**Rendered sprite sheets of third-party models.** A sheet is a derivative of the
model it was made from. Sheets produced by a user stay with that user, and none
are included in this package.

**The ASCII universal kernel payload's authorship.** `assets/kernel.json` and its
golden vector implement the `com.astral.ascii.kernel/1` contract owned by the
ASCII product. Tessera is a host of that contract, not its owner, and carries the
payload verbatim so that every host produces identical output.

## Third-party components

The Rust core depends on `serde`, `serde_json` and `flate2` (MIT/Apache-2.0). The
Flutter client depends on `ffi` (BSD-3-Clause). SHA-256 is implemented in this
repository rather than taken from a dependency, so the value that decides whether
a release is valid has no third-party code on its path.

Blender is a separate installation the user provides. It is never bundled,
modified, or redistributed.
