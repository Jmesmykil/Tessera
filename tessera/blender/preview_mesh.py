"""Export a small, spinnable preview mesh — once per asset, then never again.

The point of this file is to get Blender OUT of the interaction loop. Dragging a
light or spinning a character must not cost a render on another machine; it must
cost a frame in the app. So Blender runs once, hands over a decimated snapshot of
the geometry with baked vertex colour, and the real-time viewport takes it from
there.

Decimation is aggressive on purpose. This is a thumbnail-sized interactive view,
not the render: at a few thousand triangles a character still reads clearly enough
to judge silhouette, pose and lighting, and the whole animation fits in under a
megabyte. The final sheet still comes from the full-resolution asset.

  TPM1 format, little-endian
    magic "TPM1", u32 frames, u32 vertices, u32 indices, f32 radius,
    f32 centre[3]
    u32  index[indices]
    f32  colour[vertices * 3]          baked once; materials do not animate here
    per frame: f32 position[vertices * 3], f32 normal[vertices * 3]
"""

from __future__ import annotations

import struct
from pathlib import Path

import bpy
import bmesh
from mathutils import Vector

TARGET_TRIANGLES = 4000
TEXTURED_TARGET_TRIANGLES = 9000


DEFAULT_COLOUR = (0.72, 0.72, 0.74)
SAMPLE_SIZE = 128
_texture_cache: dict[str, tuple] = {}


def _base_colour_node(material):
    """Walk back from the Principled BSDF's Base Color to whatever feeds it."""
    if not material or not material.use_nodes:
        return None, None
    for node in material.node_tree.nodes:
        if node.type != "BSDF_PRINCIPLED":
            continue
        socket = node.inputs["Base Color"]
        if not socket.is_linked:
            return None, tuple(socket.default_value[:3])
        # Follow the chain past mixes and colour adjustments to the first image.
        seen, queue = set(), [socket.links[0].from_node]
        while queue:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            if current.type == "TEX_IMAGE" and current.image:
                return current.image, None
            for candidate in current.inputs:
                if candidate.is_linked:
                    queue.append(candidate.links[0].from_node)
        return None, None
    return None, None


def _sampled_texture(image):
    """A small RGB grid from an image, read once per material.

    Reading `image.pixels` on a 4K texture pulls 67 million floats through Python
    and takes long enough to feel broken. A copy scaled to 128x128 carries all the
    colour a vertex-sampled preview can express, and reads in milliseconds.
    """
    key = image.name_full
    if key in _texture_cache:
        return _texture_cache[key]
    grid = None
    try:
        copy = image.copy()
        try:
            copy.scale(SAMPLE_SIZE, SAMPLE_SIZE)
            pixels = list(copy.pixels)
            grid = (SAMPLE_SIZE, pixels)
        finally:
            bpy.data.images.remove(copy)
    except Exception:
        grid = None
    _texture_cache[key] = grid
    return grid


def _sample(grid, u, v):
    size, pixels = grid
    x = int((u % 1.0) * (size - 1))
    y = int((v % 1.0) * (size - 1))
    o = (y * size + x) * 4
    return (pixels[o], pixels[o + 1], pixels[o + 2])


def _material_colour(obj, index):
    """The flat fallback, for materials with no texture behind Base Color."""
    if index < len(obj.material_slots):
        material = obj.material_slots[index].material
        if material:
            _, constant = _base_colour_node(material)
            if constant:
                return constant
            return tuple(material.diffuse_color[:3])
    return DEFAULT_COLOUR


def _collect(depsgraph):
    """One merged triangle soup in world space, with a colour per vertex."""
    positions, normals, colours, indices = [], [], [], []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not obj.visible_get():
            continue
        evaluated = obj.evaluated_get(depsgraph)
        try:
            mesh = evaluated.to_mesh()
        except RuntimeError:
            continue
        mesh.calc_loop_triangles()
        matrix = evaluated.matrix_world
        rotation = matrix.to_3x3().inverted_safe().transposed()
        base = len(positions)
        for vertex in mesh.vertices:
            positions.append(matrix @ vertex.co)
            normals.append((rotation @ vertex.normal).normalized())
        slots = range(max(1, len(evaluated.material_slots)))
        slot_colour = {i: _material_colour(evaluated, i) for i in slots}
        slot_texture = {}
        for i in slots:
            material = (evaluated.material_slots[i].material
                        if i < len(evaluated.material_slots) else None)
            image, _ = _base_colour_node(material)
            slot_texture[i] = _sampled_texture(image) if image else None

        # Texture colour is sampled PER VERTEX at its UV. A preview this size has
        # a vertex every few pixels, so vertex-sampled colour reads as textured —
        # and it keeps the wire format and the rasteriser unchanged, which a real
        # UV atlas would not.
        uv_layer = mesh.uv_layers.active
        vertex_colour = [slot_colour.get(0, DEFAULT_COLOUR)] * len(mesh.vertices)
        for tri in mesh.loop_triangles:
            grid = slot_texture.get(tri.material_index)
            flat = slot_colour.get(tri.material_index, DEFAULT_COLOUR)
            for slot, v in enumerate(tri.vertices):
                if grid and uv_layer:
                    uv = uv_layer.data[tri.loops[slot]].uv
                    vertex_colour[v] = _sample(grid, uv[0], uv[1])
                else:
                    vertex_colour[v] = flat
            indices.extend(base + v for v in tri.vertices)
        colours.extend(vertex_colour)
        evaluated.to_mesh_clear()
    return positions, normals, colours, indices


def _decimate_scene(ratio: float):
    """Thin every mesh, BEFORE the armature deforms it.

    Modifier order is the whole trick here. Collapse decimation run on a deformed
    mesh chooses different edges for different poses, so the vertex count drifts
    frame to frame and an animation cannot share one index buffer — which is why a
    twelve-frame export first came back with one usable frame. Moved to the top of
    the stack it thins the REST mesh once, and skinning then deforms that fixed
    topology, exactly as the rig would deform any lower-detail model.
    """
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH" or not obj.visible_get():
            continue
        modifier = obj.modifiers.new("TesseraPreviewDecimate", "DECIMATE")
        modifier.ratio = max(0.01, min(1.0, ratio))
        if len(obj.modifiers) > 1:
            try:
                with bpy.context.temp_override(object=obj):
                    bpy.ops.object.modifier_move_to_index(
                        modifier=modifier.name, index=0)
            except Exception as error:
                print(f"preview    could not reorder decimate on {obj.name}: {error}")


def export(path, samples, set_frame):
    """Write the preview mesh. `set_frame` is the caller's sub-frame setter."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    set_frame(samples[0])
    positions, _, _, indices = _collect(depsgraph)
    triangles = len(indices) // 3
    textured = any(
        _base_colour_node(slot.material)[0] is not None
        for obj in bpy.context.scene.objects if obj.type == "MESH"
        for slot in obj.material_slots)
    target = TEXTURED_TARGET_TRIANGLES if textured else TARGET_TRIANGLES
    if triangles > target:
        _decimate_scene(target / triangles)
        depsgraph = bpy.context.evaluated_depsgraph_get()

    frames = []
    colours = None
    for frame in samples:
        set_frame(frame)
        depsgraph = bpy.context.evaluated_depsgraph_get()
        pos, nrm, col, idx = _collect(depsgraph)
        if colours is None:
            colours, reference_indices, count = col, idx, len(pos)
        # A frame whose topology moved cannot share one index buffer; skinning
        # keeps it stable, and anything that does not is dropped rather than
        # silently mismatched.
        if len(pos) != count:
            continue
        frames.append((pos, nrm))
    if not frames:
        raise SystemExit("preview mesh: no usable frames")

    flat = [v for pos, _ in frames for v in pos]
    lo = Vector((min(v[i] for v in flat) for i in range(3)))
    hi = Vector((max(v[i] for v in flat) for i in range(3)))
    centre = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 1e-6)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as fh:
        fh.write(b"TPM1")
        fh.write(struct.pack("<III", len(frames), count, len(reference_indices)))
        fh.write(struct.pack("<4f", radius, centre.x, centre.y, centre.z))
        fh.write(struct.pack(f"<{len(reference_indices)}I", *reference_indices))
        fh.write(struct.pack(f"<{count * 3}f",
                             *[c for colour in colours for c in colour]))
        for pos, nrm in frames:
            fh.write(struct.pack(f"<{count * 3}f", *[c for v in pos for c in v]))
            fh.write(struct.pack(f"<{count * 3}f", *[c for v in nrm for c in v]))
    size = path.stat().st_size
    print(f"preview    {path.name}  {len(frames)} frames, {count} verts, "
          f"{len(reference_indices) // 3} tris, {size / 1024:.0f} KB, "
          f"{'textured' if _texture_cache else 'flat materials'}")
    return path
