"""Tessera for Blender — the capture step, run inside `blender --background`.

  blender --background --factory-startup <asset.blend> \
          --python tessera/blender/capture.py -- \
          --out frames.tsf --yaws 8 --frames 6 --size 512 --profile dark-subject

Four decisions here each have a plausible-looking wrong alternative, and three of
them were arrived at by getting it wrong first:

ORTHOGRAPHIC, ALWAYS. Perspective makes the same subject a different size at
different yaws, which breaks the uniform-cell invariant the sheet driver exists
to hold.

THE ORTHO SCALE IS ONE NUMBER for the whole capture, taken from the largest
sampled frame. Scale must never change or the cells stop agreeing. But the AIM
tracks the subject per frame — aiming once at frame one walked a 250-frame ninja
clean out of view and emptied three quarters of a sheet.

LIGHTS RIDE THE CAMERA by default. A world-fixed key lights the front view and
silhouettes the back, so one character reads as two. `world_locked` is there for
when a shadow has to agree with a pre-lit plate.

NO TONEMAP. Blender defaults `view_transform` to AgX, which drains saturation by
design. The product's rule is that colour comes from the model; AgX guarantees
the colour reaching the kernel is not the colour the artist authored.
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tessera.frames import write_frames                       # noqa: E402
from tessera.lighting import LightingProfile                  # noqa: E402
from tessera.timing import Timing                             # noqa: E402


ASSET_CACHE = Path.home() / ".cache" / "tessera" / "assets"
CACHE_BUDGET_BYTES = 60 * 1024 ** 3


def stage_asset(blend_path: str, enabled: bool = True) -> str:
    """Copy the asset onto fast local storage before opening it.

    MEASURED, not assumed: this library lives on exFAT over USB at 100 MB/s while
    the machine's root disk reads at 4.7 GB/s — a 47x difference. A half-gigabyte
    character therefore spends about five seconds crossing the bus before Blender
    has parsed a single byte, and a two-gigabyte one spends twenty. That, not
    Blender's start-up, is why a preview felt slow.

    The copy costs one slow read the first time and removes it every time after,
    which is exactly the shape of a UI where a person re-renders the same asset
    while tuning a light. A budget keeps the cache from eating the boot disk;
    eviction is least-recently-used, since the working set is whatever is being
    worked on right now.
    """
    source = Path(blend_path)
    if not enabled or not source.is_file():
        return blend_path
    try:
        # Already fast? Staging a local file onto the same disk buys nothing.
        if not str(source).startswith(("/mnt/", "/media/", "/Volumes/")):
            return blend_path
        ASSET_CACHE.mkdir(parents=True, exist_ok=True)
        cached = ASSET_CACHE / f"{abs(hash(str(source))):x}-{source.name}"
        if cached.is_file() and cached.stat().st_size == source.stat().st_size:
            cached.touch()
            print(f"asset      cached ({cached.stat().st_size / 1e6:.0f} MB, fast disk)")
            return str(cached)

        entries = sorted(ASSET_CACHE.glob("*.blend"), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in entries)
        need = source.stat().st_size
        while entries and total + need > CACHE_BUDGET_BYTES:
            victim = entries.pop(0)
            total -= victim.stat().st_size
            victim.unlink(missing_ok=True)

        started = time.time()
        shutil.copy2(source, cached)
        seconds = time.time() - started
        print(f"asset      staged {need / 1e6:.0f} MB to fast disk in {seconds:.1f}s "
              f"({need / 1e6 / max(seconds, 1e-6):.0f} MB/s) — subsequent loads skip this")
        return str(cached)
    except Exception as error:                                # never block a render
        print(f"asset      staging skipped: {error}")
        return blend_path


def argv() -> dict:
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    return {raw[i].lstrip("-"): raw[i + 1] for i in range(0, len(raw) - 1, 2)}


def subject_bounds():
    """World-space bounds of every visible mesh, from EVALUATED geometry.

    `object.dimensions` is the LOCAL box and lies the moment an object carries a
    rotation or a modifier, so the corners are transformed explicitly.
    """
    lo = Vector((math.inf,) * 3)
    hi = Vector((-math.inf,) * 3)
    found = False
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not obj.visible_get():
            continue
        evaluated = obj.evaluated_get(depsgraph)
        for corner in evaluated.bound_box:
            world = evaluated.matrix_world @ Vector(corner)
            lo = Vector((min(lo[i], world[i]) for i in range(3)))
            hi = Vector((max(hi[i], world[i]) for i in range(3)))
            found = True
    if not found:
        raise SystemExit("no visible mesh in this .blend — nothing to capture")
    return lo, hi


def disable_broken_dependencies(scene) -> list[str]:
    """Turn off modifiers whose external files are missing, and say which.

    Third-party assets routinely ship with absolute paths from the machine they
    were authored on. One character in this library carries a MeshSequenceCache
    pointing at `D:/Pictures/.../Rumba Dance.abc`, and Blender retries that
    unreadable cache once per object per frame — for tens of minutes, emitting
    warnings and never finishing. It never errors, so from outside it is
    indistinguishable from a slow render, and it blocked three separate runs
    before anyone read the log.

    A dependency that cannot be read cannot contribute, so muting it changes
    nothing about the output except that it arrives.
    """
    disabled = []
    for obj in scene.objects:
        for modifier in list(getattr(obj, "modifiers", [])):
            path = getattr(getattr(modifier, "cache_file", None), "filepath", None)
            if path is None:
                continue
            resolved = bpy.path.abspath(path)
            if not Path(resolved).is_file():
                modifier.show_viewport = False
                modifier.show_render = False
                disabled.append(f"{obj.name}/{modifier.name}")
    if disabled:
        print(f"deps       disabled {len(disabled)} modifier(s) with missing files: "
              f"{', '.join(disabled[:3])}{'…' if len(disabled) > 3 else ''}")
    return disabled


def tracking_point(scene, mode: str):
    """What the camera follows. Not the bounding box, if anything better exists.

    A bbox centroid moves whenever a limb extends, so a sword raised overhead
    drags the camera up and the character appears to sink in that frame. The ROOT
    is the stable reference an animator actually authored against: it carries the
    character's travel and nothing else.

      root    the root bone's world position (the parentless bone of the armature,
              preferring a conventionally-named one). Correct for rigged subjects.
      origin  the object origin. Correct for props and for rigs whose motion was
              authored on the object rather than a bone.
      bbox    the mesh bounding-box centre. The fallback, and the only option for
              geometry with neither a rig nor meaningful travel on its origin.
    """
    if mode in ("root", "auto"):
        for obj in scene.objects:
            if obj.type != "ARMATURE":
                continue
            bones = obj.pose.bones
            named = [b for b in bones
                     if b.name.lower() in ("root", "hips", "pelvis", "cog", "torso")]
            parentless = [b for b in bones if b.parent is None]
            bone = (named or parentless or list(bones) or [None])[0]
            if bone is not None:
                return obj.matrix_world @ bone.head, f"root:{obj.name}/{bone.name}"
        if mode == "root":
            print("tracking   no armature found; falling back to origin")
        mode = "origin"
    if mode == "origin":
        for obj in scene.objects:
            if obj.type in ("ARMATURE", "MESH"):
                return obj.matrix_world.translation.copy(), f"origin:{obj.name}"
    lo, hi = subject_bounds()
    return (lo + hi) / 2.0, "bbox"


def action_frame_range(action, strip=None):
    """The real extent of an action, measured from its keys.

    `Action.frame_range` is not trustworthy on Blender 5's slotted actions: a
    rooster with eleven animations reports every one of them as a single frame, so
    a clip picker sees eleven poses and one usable clip. The keys are the truth, so
    they are what gets measured — walk
    `layers[].strips[].channelbags[].fcurves[].keyframe_points` and take the widest
    span found. An NLA strip's own start/end is used as a fallback, since a strip
    at least knows how long it plays.
    """
    lo, hi = math.inf, -math.inf
    for layer in getattr(action, "layers", []):
        for inner in getattr(layer, "strips", []):
            for bag in getattr(inner, "channelbags", []):
                for curve in bag.fcurves:
                    for key in curve.keyframe_points:
                        frame = float(key.co[0])
                        lo, hi = min(lo, frame), max(hi, frame)
    if lo <= hi:
        return lo, hi
    if strip is not None:
        return float(strip.frame_start), float(strip.frame_end)
    span = action.frame_range
    return float(span[0]), float(span[1])


def list_clips(scene):
    """Every animation in the file, however the author stored it.

    This is the fix for "none of the animations are working". A rigged BlendKit
    asset routinely leaves `animation_data.action` EMPTY and keeps its motion as
    NLA strips — Dragon Man Blue has six (Idle 1-40, Walk 1-32, Run 1-22, plus A/T
    poses) and no assigned action at all. Reading only `.action` finds nothing,
    concludes the subject is static, and renders eight copies of a bind pose.

    Both sources are enumerated, deduplicated by action name, and a single-frame
    entry is marked as a pose rather than a clip so a picker can default to real
    motion instead of a T-pose.
    """
    clips = {}
    for obj in scene.objects:
        data = obj.animation_data
        if not data:
            continue
        if data.action:
            lo, hi = action_frame_range(data.action)
            clips[data.action.name] = (lo, hi, "action", obj.name)
        for track in data.nla_tracks:
            for strip in track.strips:
                if strip.action:
                    lo, hi = action_frame_range(strip.action, strip)
                    clips.setdefault(strip.action.name, (lo, hi, "nla", obj.name))
    # Actions present in the file but wired to nothing are still usable.
    for action in bpy.data.actions:
        lo, hi = action_frame_range(action)
        clips.setdefault(action.name, (lo, hi, "library", None))
    out = [{"name": name, "start": lo, "end": hi, "source": src, "object": owner,
            "frames": int(round(hi - lo)) + 1, "pose": (hi - lo) < 1.0}
           for name, (lo, hi, src, owner) in clips.items()]
    out.sort(key=lambda c: (c["pose"], -c["frames"], c["name"]))
    return out


def apply_clip(scene, clip_name):
    """Make one clip the thing that plays. Returns its (start, end).

    Two traps, both silent. NLA strips keep evaluating unless their tracks are
    muted, so an assigned action fights whatever was already stacked. And in
    Blender 4.4+/5.x assigning `animation_data.action` WITHOUT also setting
    `action_slot` evaluates to nothing at all — no motion, no error, which reads as
    a broken rig rather than a broken assignment.
    """
    action = bpy.data.actions.get(clip_name)
    if action is None:
        raise SystemExit(f"no clip named {clip_name!r}")
    applied = False
    for obj in scene.objects:
        data = obj.animation_data
        if not data:
            continue
        owns = any(strip.action is action
                   for track in data.nla_tracks for strip in track.strips)
        if not owns and data.action is not action and obj.type != "ARMATURE":
            continue
        for track in data.nla_tracks:
            track.mute = True
        data.action = action
        slots = getattr(action, "slots", None)
        if slots:
            for slot in slots:
                try:
                    data.action_slot = slot
                    break
                except (TypeError, AttributeError):
                    continue
        applied = True
    if not applied:
        raise SystemExit(f"clip {clip_name!r} could not be applied to any object")
    lo, hi = action_frame_range(action)
    scene.frame_start, scene.frame_end = int(lo), int(hi)
    return lo, hi


def action_range(scene):
    """The range of the motion, not the range of the container holding it.

    A .blend's scene range is set by whoever exported it and routinely overshoots
    the action — Ninja Girl's scene says 1..250 while her action ends at 75. Frames
    sampled past the end return the rig's held final pose, which surfaces as
    DUPLICATE cells in the sheet and timing that matches nothing.
    """
    ranges = []
    for obj in scene.objects:
        data = obj.animation_data
        if data and data.action:
            lo, hi = data.action.frame_range
            ranges.append((float(lo), float(hi), data.action.name))
    if not ranges:
        # No animation data at all. Saying so matters: a static prop sampled at
        # eight frames returns eight identical images, and a duplicate check that
        # does not know the subject is static reports a defect that is not one.
        return float(scene.frame_start), float(scene.frame_end), None
    lo = min(r[0] for r in ranges)
    hi = max(r[1] for r in ranges)
    return lo, hi, ", ".join(sorted({r[2] for r in ranges}))


def set_frame(scene, value: float):
    """Sub-frame accurate. Rounding here is what makes an 8-frame cycle judder."""
    whole = int(value)
    scene.frame_set(whole, subframe=float(value) - whole)


def apply_colour(scene, profile: LightingProfile) -> None:
    view = scene.view_settings
    for candidate in (profile.view_transform, "Standard", "Raw"):
        try:
            view.view_transform = candidate
            break
        except TypeError:
            continue
    view.exposure = profile.exposure
    view.gamma = profile.gamma
    print(f"colour     view_transform {view.view_transform}  exposure {view.exposure}")


def apply_world(scene, profile: LightingProfile) -> None:
    world = bpy.data.worlds.new("TesseraWorld")
    world.use_nodes = True
    background = world.node_tree.nodes["Background"]
    background.inputs[0].default_value = (*profile.ambient_color, 1.0)
    background.inputs[1].default_value = profile.ambient_strength
    scene.world = world


def make_sun(name: str, energy: float, colour, angle_deg: float):
    data = bpy.data.lights.new(name, type="SUN")
    data.energy = energy
    data.color = colour
    data.angle = math.radians(angle_deg)
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def build_lights(profile: LightingProfile):
    if profile.use_scene_lights:
        print("lighting   using the asset's own lights")
        return []
    lights = []
    if profile.key_energy > 0:
        lights.append((make_sun("TesseraKey", profile.key_energy, profile.key_color,
                                profile.key_angle),
                       profile.key_azimuth, profile.key_elevation))
    if profile.fill_energy > 0:
        lights.append((make_sun("TesseraFill", profile.fill_energy, profile.fill_color, 25.0),
                       profile.fill_azimuth, 15.0))
    if profile.rim_energy > 0:
        lights.append((make_sun("TesseraRim", profile.rim_energy, profile.rim_color, 8.0),
                       profile.rim_azimuth, profile.rim_elevation))
    print(f"lighting   {profile.name}: {len(lights)} lamp(s), "
          f"{'world-locked' if profile.world_locked else 'camera-locked'}, "
          f"ambient {profile.ambient_strength}")
    return lights


def aim_light(obj, azimuth_deg: float, elevation_deg: float,
              camera_yaw: float, centre: Vector, radius: float, world_locked: bool):
    yaw = math.radians(azimuth_deg) + (0.0 if world_locked else camera_yaw)
    elevation = math.radians(elevation_deg)
    obj.location = centre + Vector((
        math.sin(yaw) * math.cos(elevation),
        -math.cos(yaw) * math.cos(elevation),
        math.sin(elevation),
    )) * radius * 6.0
    obj.rotation_euler = (centre - obj.location).to_track_quat("-Z", "Y").to_euler()


def run_capture(args: dict) -> int:
    """One capture. Callable repeatedly inside a resident Blender."""
    out_path = Path(args.get("out", "frames.tsf")).expanduser()
    yaws = int(args.get("yaws", 8))
    size = int(args.get("size", 256))
    frames = int(args.get("frames", 1))
    elevation = math.radians(float(args.get("elevation", 30.0)))
    margin = float(args.get("margin", 1.06))
    center_mode = args.get("center", "root")
    root_motion = args.get("root-motion", args.get("root_motion", "strip"))

    spec = args.get("profile", "studio")
    profile = (LightingProfile.from_json(spec) if spec.endswith(".json")
               else LightingProfile.named(spec))
    # Every profile field is overridable from the command line so a UI can expose
    # a light the user drags without inventing a second configuration format.
    overrides = {
        "ambient": "ambient_strength", "key": "key_energy", "rim": "rim_energy",
        "fill": "fill_energy", "exposure": "exposure", "samples": "samples",
        "key-azimuth": "key_azimuth", "key-elevation": "key_elevation",
        "key-angle": "key_angle", "rim-azimuth": "rim_azimuth",
        "fill-azimuth": "fill_azimuth", "gamma": "gamma",
    }
    for flag, field in overrides.items():
        if flag in args:
            value = args[flag]
            setattr(profile, field, int(value) if field == "samples" else float(value))
    if "world-locked" in args:
        profile.world_locked = str(args["world-locked"]).lower() not in ("0", "false", "no")

    scene = bpy.context.scene
    engines = {item.identifier for item in
               bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
    for candidate in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE", "BLENDER_WORKBENCH"):
        if candidate in engines:
            scene.render.engine = candidate
            break
    else:                                                     # pragma: no cover
        raise SystemExit(f"no usable engine; this build offers {sorted(engines)}")
    print(f"engine     {scene.render.engine}")

    scene.render.resolution_x = scene.render.resolution_y = size
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    if hasattr(scene, "eevee"):
        scene.eevee.taa_render_samples = profile.samples

    disable_broken_dependencies(scene)
    clips = list_clips(scene)
    # `--clips-json-also` writes the list and CONTINUES; `--clips-json` writes it
    # and stops. One caller wants the catalogue, the other wants both without
    # paying a second cold start for it.
    also = args.get("clips-json-also") or args.get("clips_json_also")
    if also:
        target = Path(also).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(
            {"clips": clips, "actions_in_file": len(bpy.data.actions)}, indent=2))
    if args.get("clips-json") or args.get("clips_json"):
        target = Path(args.get("clips-json") or args.get("clips_json")).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(
            {"clips": clips, "actions_in_file": len(bpy.data.actions)}, indent=2))
        print(f"wrote {target}  {len(clips)} clip(s) "
              f"from {len(bpy.data.actions)} action(s)")
        return 0

    requested = args.get("clip")
    if requested is None and clips and not clips[0]["pose"]:
        requested = clips[0]["name"]        # longest real motion, never a T-pose
    if requested:
        act_lo, act_hi = apply_clip(scene, requested)
        act_name = requested
        print(f"clip       {requested!r} ({len(clips)} available: "
              f"{', '.join(c['name'] for c in clips[:4])}{'…' if len(clips) > 4 else ''})")
    else:
        act_lo, act_hi, act_name = action_range(scene)
    fps = scene.render.fps / max(scene.render.fps_base, 1e-6)
    timing = Timing(
        start=float(args["start"]) if "start" in args else None,
        end=float(args["end"]) if "end" in args else None,
        frames=int(args["frames"]) if "frames" in args else None,
        source_fps=fps,
        target_fps=float(args["fps"]) if "fps" in args else None,
        phase=float(args.get("phase", 0.0)),
        speed=float(args.get("speed", 1.0)),
        loop=str(args.get("loop", "1")).lower() not in ("0", "false", "no"),
    )
    static = act_name is None or act_hi - act_lo < 1e-6
    if static and frames > 1:
        print(f"timing     subject is STATIC (no action) — collapsing "
              f"{frames} frames to 1; a still prop has nothing to sample")
        timing.frames = 1
    samples = timing.resolve(act_lo, act_hi, fps)
    print(f"action     {act_name!r} range {act_lo:.0f}..{act_hi:.0f}  "
          f"(scene says {scene.frame_start}..{scene.frame_end})")
    print(f"timing     {timing.describe(samples, fps)}")
    print(f"samples    {[round(s, 2) for s in samples]}")

    # Track the root, and size the view from the subject's extent AROUND that
    # root — not from the extent around its own centre, or a pose that reaches far
    # to one side would be framed off-centre at every yaw.
    aims = {}
    radius = 1e-6
    label = "bbox"
    for frame_number in samples:
        set_frame(scene, frame_number)
        point, label = tracking_point(scene, center_mode)
        aims[frame_number] = point
        lo, hi = subject_bounds()
        for corner in (lo, hi):
            radius = max(radius, (corner - point).length)
    centre = sum(aims.values(), Vector((0, 0, 0))) / len(aims)
    if root_motion == "keep":
        aims = {n: centre for n in samples}
    drift = max((a - centre).length for a in aims.values())
    print(f"tracking   {label}  root_motion={root_motion}  radius {radius:.3f}  "
          f"travel {drift:.3f}")

    # A preview mesh, if asked for: exported ONCE per asset so the app's live
    # viewport never needs Blender again for spinning or relighting.
    preview_mesh = args.get("preview-mesh") or args.get("preview_mesh")
    if preview_mesh:
        from tessera.blender import preview_mesh as preview_export
        preview_export.export(Path(preview_mesh).expanduser(), samples,
                              lambda f: set_frame(scene, f))
        if str(args.get("preview-only", "0")).lower() in ("1", "true", "yes"):
            return 0

    apply_colour(scene, profile)
    apply_world(scene, profile)
    lights = build_lights(profile)

    cam_data = bpy.data.cameras.new("TesseraCam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = radius * 2.0 * margin
    camera = bpy.data.objects.new("TesseraCam", cam_data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    distance = radius * 6.0

    tmp = Path(bpy.app.tempdir) / "tessera_capture.png"
    views = []
    for yaw_index in range(yaws):
        yaw = yaw_index * (2 * math.pi / yaws)
        for frame_index, frame_number in enumerate(samples):
            set_frame(scene, frame_number)
            aim = aims[frame_number]
            camera.location = aim + Vector((
                math.sin(yaw) * math.cos(elevation),
                -math.cos(yaw) * math.cos(elevation),
                math.sin(elevation),
            )) * distance
            camera.rotation_euler = (aim - camera.location).to_track_quat("-Z", "Y").to_euler()
            for obj, azimuth, elev in lights:
                aim_light(obj, azimuth, elev, yaw, aim, radius, profile.world_locked)

            scene.render.filepath = str(tmp)
            bpy.ops.render.render(write_still=True)
            image = bpy.data.images.load(str(tmp), check_existing=False)
            flat = list(image.pixels)                          # RGBA float, BOTTOM-UP
            bpy.data.images.remove(image)
            row = size * 4
            rgba = [v for y in range(size - 1, -1, -1) for v in flat[y * row:(y + 1) * row]]
            views.append((yaw_index, frame_index, math.degrees(yaw),
                          int(round(frame_number)), rgba))
        print(f"  yaw {yaw_index + 1}/{yaws}  {math.degrees(yaw):6.1f} deg  "
              f"{len(samples)} frame(s)", flush=True)

    write_frames(out_path, size, size, views)
    print(f"wrote {out_path}  {len(views)} views  {size}x{size}  ortho {cam_data.ortho_scale:.3f}")
    return 0


def main() -> int:
    return run_capture(argv())


if __name__ == "__main__":
    raise SystemExit(main())
