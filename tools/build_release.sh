#!/bin/bash
# Build the macOS release: kernel, app, bundle, DMG, manifest.
#
# This exists because the first DMG was assembled by hand. It went stale the
# moment the Rust core was rebuilt — the shipped bundle carried a kernel three
# hours older than the one every test had been run against, and nothing said so.
# A release you cannot reproduce from one command is a release you cannot trust.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
VERSION="$(grep -m1 '^version:' app/pubspec.yaml | sed 's/version: *//' | cut -d+ -f1)"
DYLIB="rust/target/release/libtessera_core.dylib"
BUILT="app/build/macos/Build/Products/Release/tessera_studio.app"
APP="$BUILT"
STAGE="/tmp/tessera-dmg-stage"
DMG="dist/TesseraStudio.dmg"

echo "==> kernel"
cargo build --release --manifest-path rust/Cargo.toml
cargo test  --release --manifest-path rust/Cargo.toml >/dev/null
test -f "$DYLIB" || { echo "no dylib at $DYLIB"; exit 1; }

echo "==> app"
( cd app && flutter build macos --release )
test -d "$BUILT" || { echo "flutter produced no bundle at $BUILT"; exit 1; }

echo "==> bundle the kernel"
# The app searches the repo first and the bundle second, so a developer gets
# their own build and an installed copy gets this one. Without it the shipped
# app falls back to a bare library name and cannot start.
mkdir -p "$APP/Contents/Frameworks"
cp "$DYLIB" "$APP/Contents/Frameworks/"
codesign --force --deep --sign - "$APP" 2>/dev/null || echo "  (ad-hoc signing skipped)"

echo "==> staging"
rm -rf "$STAGE"; mkdir -p "$STAGE"
# Flutter names the bundle from the pubspec; present it under the product name.
cp -R "$APP" "$STAGE/Tessera Studio.app"
cp release/dmg/"READ ME FIRST.txt" "$STAGE/" 2>/dev/null || true
cp release/RELEASE-NOTES.md "$STAGE/Release Notes.md" 2>/dev/null || true
ln -s /Applications "$STAGE/Applications"

echo "==> dmg"
mkdir -p dist; rm -f "$DMG"
hdiutil create -volname "Tessera Studio" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo "==> manifest"
python3 - "$ROOT" "$VERSION" "$DMG" "$DYLIB" <<'PY'
import hashlib, json, pathlib, sys, datetime
root, version, dmg, dylib = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
def digest(p):
    b = (root / p).read_bytes()
    return len(b), hashlib.sha256(b).hexdigest()
m = json.loads((root / "release/PACKAGE-MANIFEST.json").read_text())
m["version"] = version
m["built"] = datetime.date.today().isoformat()
n, h = digest(dmg);   m["artifact"]["macos_dmg"].update(path=dmg, bytes=n, sha256=h)
n, h = digest(dylib); m["artifact"]["kernel_dylib"].update(path=dylib, bytes=n, sha256=h)
(root / "release/PACKAGE-MANIFEST.json").write_text(json.dumps(m, indent=1) + "\n")
print(f"  dmg {n if False else ''}", m["artifact"]["macos_dmg"]["bytes"], "bytes",
      m["artifact"]["macos_dmg"]["sha256"][:16])
PY

echo "==> verify the shipped bundle carries THIS kernel"
# Compare the linker UUID, not the file hash: `codesign --deep` re-signs the
# dylib inside the bundle, so its bytes legitimately differ from the one on
# disk. The UUID is stamped at link time and survives signing, so it answers
# the question actually being asked — is this the kernel the tests ran against?
uuid_of() { otool -l "$1" | awk '/LC_UUID/{getline; getline; print $2}'; }
hdiutil attach "$DMG" -nobrowse -readonly -mountpoint /tmp/tessera-verify >/dev/null
SHIPPED="/tmp/tessera-verify/Tessera Studio.app/Contents/Frameworks/libtessera_core.dylib"
WANT="$(uuid_of "$DYLIB")"
GOT="$([ -f "$SHIPPED" ] && uuid_of "$SHIPPED" || echo missing)"
hdiutil detach /tmp/tessera-verify >/dev/null
if [ -n "$WANT" ] && [ "$WANT" = "$GOT" ]; then
  echo "  OK: bundled kernel is the build the tests ran against (uuid ${WANT})"
else
  echo "  FAIL: want uuid ${WANT:-none}, bundle has ${GOT}"; exit 1
fi
echo "==> done: $DMG"
