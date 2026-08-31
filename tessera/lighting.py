"""Lighting and shading profiles — simple by default, fully open underneath.

Two things make sprite lighting different from render lighting, and both are the
kind of mistake that looks like an asset problem rather than a rig problem:

RIG THE KEY LIGHT TO THE CAMERA, NOT THE WORLD. On a turnaround, a world-fixed
sun lights the front view beautifully and turns the back view into a silhouette,
so the same character reads as two different characters depending on which way
they face. Locking the key to the camera gives every direction the same light.
`world_locked = True` is there for the case where the shadow direction has to
agree with a pre-lit background plate.

DO NOT TONEMAP. Blender's default `view_transform` is AgX, a filmic curve that
rolls off highlights and drains saturation on purpose. It is right for a
photographic render and wrong for a sprite, whose whole contract is that the
colour reaching the kernel is the colour the artist authored.

Everything below is one flat dataclass so the simple path is a preset name, the
power path is a JSON file, and there is no third representation in between for
the two to disagree about.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class LightingProfile:
    name: str = "studio"
    # colour management
    view_transform: str = "Standard"       # "Standard" | "AgX" | "Filmic" | "Raw"
    exposure: float = 0.0
    gamma: float = 1.0
    # ambient / world
    ambient_strength: float = 0.35
    ambient_color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    # key
    key_energy: float = 3.0
    key_color: tuple[float, float, float] = (1.0, 0.98, 0.94)
    key_elevation: float = 35.0            # degrees above the horizon
    key_azimuth: float = -35.0             # degrees from the camera's own axis
    key_angle: float = 6.0                 # soft-shadow cone
    # fill and rim, both optional
    fill_energy: float = 0.9
    fill_color: tuple[float, float, float] = (0.86, 0.90, 1.0)
    fill_azimuth: float = 60.0
    rim_energy: float = 2.0
    rim_color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    rim_azimuth: float = 165.0
    rim_elevation: float = 25.0
    # behaviour
    world_locked: bool = False             # False = lights orbit with the camera
    samples: int = 64
    use_scene_lights: bool = False         # True = keep the asset's own lighting

    def to_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.write_text(json.dumps(asdict(self), indent=2))
        return path

    @classmethod
    def from_json(cls, path: str | Path) -> "LightingProfile":
        data = json.loads(Path(path).read_text())
        typed = {f.name: f for f in fields(cls)}
        unknown = set(data) - set(typed)
        if unknown:
            raise ValueError(f"unknown lighting keys: {sorted(unknown)}")
        # JSON has no tuple, so every colour comes back as a list. Coerce on the
        # way in, or a profile stops comparing equal to itself across a save and
        # load — which is the shape of bug that makes a cache look haunted.
        for key, value in list(data.items()):
            if isinstance(value, list) and "tuple" in str(typed[key].type):
                data[key] = tuple(value)
        return cls(**data)

    @classmethod
    def named(cls, name: str) -> "LightingProfile":
        if name not in PRESETS:
            raise ValueError(f"unknown profile {name!r}; have {sorted(PRESETS)}")
        return cls(**{"name": name, **PRESETS[name]})


PRESETS: dict[str, dict] = {
    # Even, shadowless, colour-accurate. The safest match for a flat-shaded or
    # 2D-styled game, and the one to reach for when the sprite must be recoloured
    # downstream — baked shading fights a palette swap.
    "flat": dict(ambient_strength=1.0, key_energy=0.0, fill_energy=0.0,
                 rim_energy=0.0, samples=16),
    # A neutral three-point rig. The default: enough form to read as 3D, not so
    # much contrast that a dark costume loses its silhouette.
    "studio": dict(),
    # For dark or high-gloss subjects. Lifts the ambient floor and adds rim so a
    # black outfit still separates from the background — the Ninja Girl case.
    "dark-subject": dict(ambient_strength=0.75, key_energy=4.5, fill_energy=2.0,
                         rim_energy=4.0, samples=96),
    # Hard key, low fill, strong rim. Reads at small sizes where subtlety is lost.
    "dramatic": dict(ambient_strength=0.15, key_energy=6.0, key_angle=1.5,
                     fill_energy=0.3, rim_energy=3.5),
    # Warm sun and cool sky, shadows agreeing with a world direction. Use when the
    # sprite drops onto a pre-lit background and its shadow must not disagree.
    "outdoor": dict(ambient_strength=0.5, ambient_color=(0.72, 0.82, 1.0),
                    key_energy=4.0, key_color=(1.0, 0.95, 0.84),
                    key_elevation=55.0, world_locked=True),
}
