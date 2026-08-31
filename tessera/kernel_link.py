"""Locating the ASCII universal kernel WITHOUT forking it.

Tessera is the fourth host of `com.astral.ascii.kernel/1`, after ASCII itself,
ASCII Studio for Blender and ASCII Studio for Unity. The other three each
implement the kernel's arithmetic in their own language and copy the canonical
payload verbatim for self-contained distribution; a release is invalid the
moment any host's `kernel.json` or golden vector diverges from the others.

So Tessera copies the PAYLOAD (assets/), which is the sanctioned pattern, and
IMPORTS the reference implementation rather than copying it. Python already has
a dependency-free reference inside the Blender addon, and a second Python copy
of the same 361 lines would be exactly the duplicate build path PD-3 exists to
stop — two implementations that drift silently until a sprite renders wrong and
nobody knows which one is lying.

The import is therefore a hard dependency with a loud failure, not a fallback to
a vendored copy. A missing kernel is a setup problem with one obvious fix; a
silently forked kernel is a bug that outlives the person who caused it.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
KERNEL_JSON = ASSETS / "kernel.json"
GOLDEN_VECTOR = ASSETS / "golden-vector.json"

# Override when the reference lives elsewhere; the default is where the Blender
# host keeps it on this machine.
REFERENCE_ENV = "TESSERA_KERNEL_REFERENCE"
DEFAULT_REFERENCE = Path.home() / "ASCII-Blender" / "ascii_studio" / "kernel.py"


class KernelUnavailable(RuntimeError):
    """The kernel reference could not be imported. Never silently substituted."""


class KernelDiverged(RuntimeError):
    """Tessera's payload no longer matches the kernel it is running against."""


def reference_path() -> Path:
    return Path(os.environ.get(REFERENCE_ENV, str(DEFAULT_REFERENCE))).expanduser()


def load_kernel_module():
    """Import the reference implementation from wherever it actually lives."""
    path = reference_path()
    if not path.is_file():
        raise KernelUnavailable(
            f"ASCII kernel reference not found at {path}.\n"
            f"Set {REFERENCE_ENV} to the path of ascii_studio/kernel.py. "
            "Tessera deliberately does not carry its own copy — see this module's docstring."
        )
    spec = importlib.util.spec_from_file_location("tessera._ascii_kernel", path)
    if spec is None or spec.loader is None:            # pragma: no cover - import plumbing
        raise KernelUnavailable(f"could not build an import spec for {path}")
    module = importlib.util.module_from_spec(spec)
    # Register BEFORE executing: kernel.py is built from frozen dataclasses, and
    # dataclasses resolves field types via sys.modules[cls.__module__], which is
    # None for a module that is still mid-import.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def canonical_fingerprint(payload: dict) -> str:
    """The kernel's own fingerprint rule, restated so we can check it independently."""
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


class KernelBundle:
    """Everything a host needs from the kernel, resolved once."""

    def __init__(self, module, kernel):
        self.module = module
        self.kernel = kernel
        self.Settings = module.KernelSettings
        self.GlyphCell = module.GlyphCell
        self.GlyphFrame = module.GlyphFrame


def open_kernel():
    """Return a KernelBundle with the divergence gate already enforced.

    The check is the point of this function. Every host asserts the same thing in
    its own test suite; doing it at load time means Tessera cannot render a single
    sprite against a kernel that has drifted away from the payload it shipped.
    """
    module = load_kernel_module()
    kernel = module.AsciiKernel(KERNEL_JSON)

    payload = json.loads(KERNEL_JSON.read_text(encoding="utf-8"))
    expected = canonical_fingerprint(payload)
    if kernel.fingerprint != expected:
        raise KernelDiverged(
            f"kernel fingerprint {kernel.fingerprint[:16]} does not match Tessera's "
            f"payload {expected[:16]}"
        )

    golden = json.loads(GOLDEN_VECTOR.read_text(encoding="utf-8"))
    if golden.get("kernel_fingerprint") != kernel.fingerprint:
        raise KernelDiverged(
            "golden vector was produced against a different kernel: "
            f"{str(golden.get('kernel_fingerprint'))[:16]} vs {kernel.fingerprint[:16]}"
        )
    return KernelBundle(module, kernel)
