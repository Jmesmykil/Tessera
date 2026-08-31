"""Configuration — generic everywhere, pre-pointed at this workstation.

The rule: nothing in Tessera's code knows a path on anyone's machine. Paths come
from layered configuration, and the layers resolve in the order a person would
expect — an explicit flag beats an environment variable, which beats the user's
config file, which beats the shipped defaults.

The defaults that ship are still USEFUL rather than empty: `profiles/` carries a
`default.json` describing this machine's actual library and render host, so
the tool works out of the box here without a single path being compiled in.
Someone else drops in their own profile and nothing about the code changes.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

CONFIG_ENV = "TESSERA_CONFIG"
USER_CONFIG = Path.home() / ".config" / "tessera" / "config.json"
PROFILES = Path(__file__).resolve().parent.parent / "profiles"


@dataclass
class RenderHost:
    """Where Blender runs. Local by default; remote when the box is elsewhere."""
    kind: str = "local"                      # "local" | "ssh"
    ssh_host: str = ""
    blender: str = "blender"
    workdir: str = "~/Tessera"
    env: dict = field(default_factory=dict)  # e.g. {"DRI_PRIME": "1"}


@dataclass
class Library:
    """One searchable source of .blend assets."""
    name: str = "default"
    root: str = ""
    index_csv: str = ""                      # optional; a walk is used when absent
    thumbs: str = ""


@dataclass
class Config:
    libraries: list = field(default_factory=list)
    host: RenderHost = field(default_factory=RenderHost)
    out_dir: str = "~/Tessera/out"
    kernel_reference: str = ""
    default_profile: str = "studio"
    default_tileset: str = "pixel-hd"

    @classmethod
    def _coerce(cls, data: dict) -> "Config":
        host = RenderHost(**data.get("host", {}))
        libraries = [Library(**entry) for entry in data.get("libraries", [])]
        rest = {k: v for k, v in data.items()
                if k in {f.name for f in fields(cls)} and k not in ("host", "libraries")}
        return cls(libraries=libraries, host=host, **rest)

    @classmethod
    def load(cls, explicit: str | None = None) -> "Config":
        for candidate in (explicit, os.environ.get(CONFIG_ENV), USER_CONFIG,
                          PROFILES / "default.json"):
            if not candidate:
                continue
            path = Path(candidate).expanduser()
            if path.is_file():
                config = cls._coerce(json.loads(path.read_text()))
                config.source = str(path)
                return config
        config = cls()
        config.source = "built-in defaults"
        return config

    def save(self, path: str | Path = USER_CONFIG) -> Path:
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self)
        payload.pop("source", None)
        path.write_text(json.dumps(payload, indent=2))
        return path

    def library(self, name: str | None = None) -> Library:
        if not self.libraries:
            raise SystemExit("no libraries configured — run `tessera config --init`")
        if name is None:
            return self.libraries[0]
        for entry in self.libraries:
            if entry.name == name:
                return entry
        raise SystemExit(f"no library named {name!r}; have "
                         f"{[e.name for e in self.libraries]}")
