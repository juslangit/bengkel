"""
Turn a build plan into real Blender geometry, one part at a time.

Sizes in a plan are half-extents: for a box they are half its width, depth and
height; for a sphere they are its three radii; for a cylinder or cone they are
the radius in X, the radius in Y and half the height. One rule, so nothing is
ever accidentally twice the size it should be.

Each part is exported on its own as a small .glb the moment it is made, and the
browser adds it to the view. That is why you see the model appear piece by piece
instead of waiting for a finished file.
"""

import math
import os

import bpy
from mathutils import Vector, Quaternion


# --------------------------------------------------------------------------
# scene housekeeping
# --------------------------------------------------------------------------

def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.armatures,
                  bpy.data.actions, bpy.data.objects):
        for item in list(block):
            if item.users == 0:
                block.remove(item)
    bpy.context.scene.frame_set(1)


def hex_to_rgb(h):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    # glTF stores linear colour, so convert out of sRGB or everything looks washed out
    lin = []
    for c in srgb:
        lin.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return lin + [1.0]


def material_for(color, detail):
    emissive = float(detail.get("emissive", 0) or 0)
    glass = bool(detail.get("glass"))
    key = "bk_%s%s%s" % (color.lstrip("#"),
                         "_e%g" % emissive if emissive else "",
                         "_glass" if glass else "")
    if key in bpy.data.materials:
        return bpy.data.materials[key]

    mat = bpy.data.materials.new(key)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    rgba = hex_to_rgb(color)
    bsdf.inputs["Base Color"].default_value = rgba
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.3 if glass else 0.62
    if glass:
        if "Alpha" in bsdf.inputs:
            bsdf.inputs["Alpha"].default_value = 0.55
        mat.blend_method = "BLEND" if hasattr(mat, "blend_method") else mat.blend_method
    if emissive:
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = rgba
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = emissive
    return mat


def _finish(obj, st, smooth):
    obj.name = st["part"]
    obj.data.materials.append(material_for(st["color"], st.get("detail") or {}))
    obj["bk_part"] = st["part"]
    if st.get("bone"):
        obj["bk_bone"] = st["bone"]["name"]
    elif st.get("attach"):
        obj["bk_bone"] = st["attach"]
    if smooth:
        for poly in obj.data.polygons:
            poly.use_smooth = True
    return obj


def _bevel(obj, width, segments=3):
    mod = obj.modifiers.new("bk_round", "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(35)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=mod.name)


# --------------------------------------------------------------------------
# the shapes
# --------------------------------------------------------------------------

def make_part(st, style="round"):
    shape = st["shape"]
    sx, sy, sz = st["size"]
    loc = Vector(st["loc"])
    detail = st.get("detail") or {}
    segments = int(detail.get("segments", 0) or 0)

    if shape == "limb":
        obj = _make_limb(st, style)
    elif shape in ("box", "capsule") or (style == "blocky" and shape in ("sphere",)):
        bpy.ops.mesh.primitive_cube_add(size=2, location=loc)
        obj = bpy.context.active_object
        obj.scale = (max(sx, 1e-4), max(sy, 1e-4), max(sz, 1e-4))
        _apply_scale(obj)
        smallest = min(sx, sy, sz)
        if shape == "capsule":
            _bevel(obj, smallest * 0.60, 4)
            obj = _finish(obj, st, True)
        elif style == "round":
            _bevel(obj, smallest * 0.16, 2)
            obj = _finish(obj, st, False)
        else:
            obj = _finish(obj, st, False)
    elif shape == "sphere":
        bpy.ops.mesh.primitive_uv_sphere_add(radius=1, segments=24, ring_count=12,
                                             location=loc)
        obj = bpy.context.active_object
        obj.scale = (sx, sy, sz)
        _apply_scale(obj)
        obj = _finish(obj, st, True)
    elif shape == "cylinder":
        verts = segments or (8 if style == "blocky" else 20)
        bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=1, depth=2,
                                            location=loc)
        obj = bpy.context.active_object
        obj.scale = (sx, sy, sz)
        _apply_scale(obj)
        obj = _finish(obj, st, style != "blocky")
    elif shape == "cone":
        verts = segments or (6 if style == "blocky" else 18)
        bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=1, radius2=0,
                                        depth=2, location=loc)
        obj = bpy.context.active_object
        obj.scale = (sx, sy, sz)
        _apply_scale(obj)
        obj = _finish(obj, st, verts > 8)
    elif shape == "torus":
        bpy.ops.mesh.primitive_torus_add(major_radius=max(sx, 1e-3),
                                         minor_radius=max(sy, 1e-3),
                                         major_segments=20, minor_segments=8,
                                         location=loc)
        obj = bpy.context.active_object
        obj = _finish(obj, st, True)
    else:
        raise ValueError("unknown shape %r" % shape)

    rot = st.get("rot") or (0, 0, 0)
    if any(rot):
        obj.rotation_euler = rot
    return obj


def _apply_scale(obj):
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)


def _make_limb(st, style):
    """A tapered tube running from one joint to the next, with rounded ends."""
    d = st["detail"]
    head, tail = Vector(d["head"]), Vector(d["tail"])
    r0, r1 = max(float(d["r0"]), 1e-4), max(float(d["r1"]), 1e-4)
    direction = tail - head
    length = direction.length or 1e-4
    mid = (head + tail) / 2.0

    verts = 6 if style == "blocky" else 16
    bpy.ops.mesh.primitive_cone_add(vertices=verts, radius1=r0, radius2=r1,
                                    depth=length, location=mid)
    obj = bpy.context.active_object
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(direction.normalized())

    if style != "blocky":
        # caps, so the joints read as joints rather than as cut pipes
        for point, radius in ((head, r0), (tail, r1)):
            bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, segments=16,
                                                 ring_count=8, location=point)
            cap = bpy.context.active_object
            cap.select_set(True)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.join()
            obj = bpy.context.active_object

    return _finish(obj, st, style != "blocky")


# --------------------------------------------------------------------------
# running a plan
# --------------------------------------------------------------------------

def build_plan(plan, on_step=None):
    """
    Make every part of the plan. `on_step` is called after each one with
    (index, step, object) so the caller can export a snapshot and report
    progress while the build is still going.
    """
    clear_scene()
    style = plan.get("style", "round")
    made = []
    for i, st in enumerate(plan["steps"]):
        obj = make_part(st, style)
        made.append(obj)
        if on_step:
            on_step(i, st, obj)
    return made


def export_selection(objects, path, animations=False):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
    _gltf_export(path, use_selection=True, animations=animations)


def export_scene(path, animations=False):
    bpy.ops.object.select_all(action="DESELECT")
    _gltf_export(path, use_selection=False, animations=animations)


def _gltf_export(path, use_selection, animations):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    kwargs = dict(filepath=path, export_format="GLB",
                  use_selection=use_selection,
                  export_apply=True,
                  export_yup=True)
    if animations:
        kwargs.update(export_animations=True, export_frame_range=True,
                      export_force_sampling=True, export_nla_strips=False)
    else:
        kwargs.update(export_animations=False)
    try:
        bpy.ops.export_scene.gltf(**kwargs)
    except TypeError:
        # older or newer Blender with a different argument set - drop the extras
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB",
                                  use_selection=use_selection)
