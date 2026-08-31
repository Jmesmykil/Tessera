"""Asset discovery, over whatever the user actually has.

Two providers behind one interface, because a library is not one shape. A curated
collection like this workstation's ships an INDEX.csv with rig/animated/category
metadata already computed, and reading it is both faster and richer than walking
115 GB. Someone else has a folder of .blend files and nothing else, and the tool
must still work for them — so the walk is a first-class provider, not a fallback
apology, and both answer the same queries.

Anything the walk cannot know (is it rigged? is it animated?) comes back as None
rather than False. A confident wrong answer would silently drop every rigged
character from a search whose whole purpose was to find them.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Asset:
    name: str
    path: Path
    category: str = ""
    top: str = ""
    rig: bool | None = None
    animated: bool | None = None
    faces: int | None = None
    size: int | None = None
    license: str = ""
    thumb: str = ""

    def label(self) -> str:
        marks = "".join((("R" if self.rig else "-") if self.rig is not None else "?",
                         ("A" if self.animated else "-") if self.animated is not None else "?"))
        faces = f"{self.faces:>8,}" if self.faces else "       ?"
        return f"[{marks}] {self.name[:44]:46} {faces} faces  {self.category[:18]}"


def _truthy(value) -> bool | None:
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y"):
        return True
    if text in ("0", "false", "no", "n"):
        return False
    return None


class IndexProvider:
    """Backed by a curated INDEX.csv."""

    def __init__(self, root: Path, index_csv: Path):
        self.root = Path(root)
        self.index = Path(index_csv)

    def assets(self):
        with self.index.open() as handle:
            for row in csv.DictReader(handle):
                rel = row.get("rel") or ""
                if not rel.endswith(".blend"):
                    continue
                size = row.get("size") or ""
                faces = row.get("faceCount") or ""
                yield Asset(
                    name=row.get("name") or Path(rel).stem,
                    path=self.root / rel,
                    category=row.get("category", ""),
                    top=row.get("top", ""),
                    rig=_truthy(row.get("rig")),
                    animated=_truthy(row.get("animated")),
                    faces=int(float(faces)) if faces else None,
                    size=int(float(size)) if size else None,
                    license=row.get("license", ""),
                    thumb=row.get("thumb", ""),
                )


class WalkProvider:
    """Backed by nothing but a directory of .blend files."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def assets(self):
        """Whatever folders the user keeps models in ARE the categories.

        Nothing is configured: the first directory under the root is the bucket
        and the rest is the subcategory, so an uncurated folder tree organises
        itself exactly as a curated index would.
        """
        for path in sorted(self.root.rglob("*.blend")):
            try:
                size = path.stat().st_size
            except OSError:
                size = None
            folders = path.relative_to(self.root).parts[:-1]
            yield Asset(name=path.stem, path=path, size=size,
                        top=folders[0] if folders else "library",
                        category="/".join(folders[1:]) if len(folders) > 1 else "")


CACHE = Path.home() / ".cache" / "tessera"


def ensure_index(library, host=None, refresh: bool = False) -> Path | None:
    """Make the catalogue readable from the machine running the UI.

    The library lives on the render host; the app runs on the workstation. Rather
    than shell out per keystroke, the INDEX.csv is cached locally once — it is the
    only part of a 115 GB library small enough to copy, and asset PATHS stay
    remote because that is where the render happens.
    """
    index = Path(library.index_csv).expanduser() if library.index_csv else None
    if not index:
        return None
    if index.is_file():
        return index
    if host is None or host.kind != "ssh":
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{library.name}-INDEX.csv"
    if cached.is_file() and not refresh:
        return cached
    import subprocess
    got = subprocess.run(["scp", "-q", f"{host.ssh_host}:{index}", str(cached)],
                         capture_output=True, text=True)
    if got.returncode != 0:
        return cached if cached.is_file() else None
    return cached


def provider_for(library, host=None, refresh: bool = False):
    root = Path(library.root).expanduser()
    index = ensure_index(library, host, refresh)
    if index and index.is_file():
        return IndexProvider(root, index)
    if not root.is_dir():
        raise SystemExit(
            f"library {library.name!r} is not reachable from this machine "
            f"({root}) and no index could be cached. Check the render host in "
            f"`tessera config`.")
    return WalkProvider(root)


def search(provider, query: str = "", *, rig=None, animated=None, top=None,
           max_faces=None, limit=40):
    results = []
    needle = query.lower()
    for asset in provider.assets():
        if needle and needle not in asset.name.lower() and needle not in asset.category.lower():
            continue
        if rig is not None and asset.rig is not rig:
            continue
        if animated is not None and asset.animated is not animated:
            continue
        if top and asset.top != top:
            continue
        if max_faces and asset.faces and asset.faces > max_faces:
            continue
        results.append(asset)
        if len(results) >= limit:
            break
    return results
