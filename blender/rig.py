"""
The auto-rig button.

Two routes in here, and which one runs depends on where the model came from.

*Exact* - for a model boneka built itself. Every part already knows which bone
it belongs to and where that bone's two ends are, because the recipe said so
when it placed the part. Nothing is guessed: the elbow bone goes exactly where
the forearm starts.

*Fitted* - for a model that arrived as one lump of triangles, such as a Meshy
generation. There is nothing to read, so a standard skeleton is measured against
the mesh's own proportions and Blender works the weights out by heat diffusion.
"""

import math

import bpy
from mathutils import Vector


def _mesh_objects():
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def _closest_bone(point, bones):
    """Nearest bone to a point, measured to the bone segment rather than its ends."""
    best, best_d = None, 1e18
    for b in bones:
        a, c = Vector(b["head"]), Vector(b["tail"])
        ab = c - a
        t = 0.0 if ab.length_squared == 0 else max(
            0.0, min(1.0, (point - a).dot(ab) / ab.length_squared))
        d = (point - (a + ab * t)).length
        if d < best_d:
            best, best_d = b["name"], d
    return best


# --------------------------------------------------------------------------
# exact rig, from the plan the model was built with
# --------------------------------------------------------------------------

def rig_from_plan(plan, smooth_passes=6):
    bones = [st["bone"] for st in plan["steps"] if st.get("bone")]
    if not bones:
        raise RuntimeError("this model has no joints to rig")

    meshes = _mesh_objects()
    if not meshes:
        raise RuntimeError("there is no model to rig yet")

    # 1. every part is put into the vertex group of its own bone, before the
    #    parts are joined, because joining merges groups that share a name
    known = {b["name"] for b in bones}
    for obj in meshes:
        bone_name = obj.get("bk_bone")
        if bone_name not in known:
            centre = obj.matrix_world @ (
                sum((Vector(c) for c in obj.bound_box), Vector()) / 8.0)
            bone_name = _closest_bone(centre, bones)
        group = obj.vertex_groups.new(name=bone_name)
        group.add([v.index for v in obj.data.vertices], 1.0, "REPLACE")

    body = _join(meshes, name="%s_mesh" % plan.get("name", "model").replace(" ", "_"))
    arm_obj = _build_armature(bones, name="%s_rig" % plan.get("name", "model").replace(" ", "_"))

    # 2. bind, keeping the groups we just made rather than letting Blender guess
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.parent_set(type="ARMATURE_NAME")

    # 3. rigid weights bend like wood, so soften them across the joints
    if smooth_passes:
        _smooth_weights(body, smooth_passes)

    return arm_obj, body, [b["name"] for b in bones]


def _join(meshes, name):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    body = bpy.context.active_object
    body.name = name
    return body


def _build_armature(bones, name):
    bpy.ops.object.select_all(action="DESELECT")
    bpy.ops.object.armature_add(enter_editmode=False, location=(0, 0, 0))
    arm_obj = bpy.context.active_object
    arm_obj.name = name
    arm_obj.data.name = name + "_data"
    arm_obj.show_in_front = True

    bpy.ops.object.mode_set(mode="EDIT")
    edit_bones = arm_obj.data.edit_bones
    for b in list(edit_bones):
        edit_bones.remove(b)

    made = {}
    # parents must exist before their children
    ordered, seen = [], set()

    def visit(b):
        if b["name"] in seen:
            return
        seen.add(b["name"])
        parent = b.get("parent")
        if parent:
            for other in bones:
                if other["name"] == parent:
                    visit(other)
                    break
        ordered.append(b)

    for b in bones:
        visit(b)

    for b in ordered:
        eb = edit_bones.new(b["name"])
        eb.head = Vector(b["head"])
        eb.tail = Vector(b["tail"])
        if eb.length < 1e-4:
            eb.tail = eb.head + Vector((0, 0, 0.02))
        made[b["name"]] = eb
    for b in ordered:
        parent = b.get("parent")
        if parent and parent in made:
            eb = made[b["name"]]
            eb.parent = made[parent]
            eb.use_connect = (eb.head - made[parent].tail).length < 1e-4

    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


def _smooth_weights(body, passes):
    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    bpy.context.view_layer.objects.active = body
    try:
        bpy.ops.object.vertex_group_smooth(group_select_mode="ALL", factor=0.5,
                                           repeat=passes, expand=0.0)
    except RuntimeError:
        pass          # a model with a single group has nothing to smooth


# --------------------------------------------------------------------------
# fitted rig, for a mesh that arrived with no part names
# --------------------------------------------------------------------------

def rig_fitted(profile="humanoid"):
    meshes = _mesh_objects()
    if not meshes:
        raise RuntimeError("there is no model to rig yet")
    body = _join(meshes, name="imported_mesh")

    lo, hi = _world_bounds(body)
    height = hi.z - lo.z
    if height < 1e-4:
        raise RuntimeError("the model is flat, so there is nothing to fit a skeleton to")

    bones = (_fit_humanoid(lo, hi) if profile == "humanoid"
             else _fit_spine(lo, hi))
    arm_obj = _build_armature(bones, name="imported_rig")

    bpy.ops.object.select_all(action="DESELECT")
    body.select_set(True)
    arm_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    return arm_obj, body, [b["name"] for b in bones]


def _world_bounds(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    lo = Vector((min(c.x for c in corners), min(c.y for c in corners),
                 min(c.z for c in corners)))
    hi = Vector((max(c.x for c in corners), max(c.y for c in corners),
                 max(c.z for c in corners)))
    return lo, hi


def _fit_humanoid(lo, hi):
    """A standard skeleton scaled onto whatever the mesh's bounding box is."""
    H = hi.z - lo.z
    cx, cy, z0 = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z
    half_w = (hi.x - lo.x) / 2
    x_arm = min(half_w * 0.78, 0.15 * H)
    x_hip = min(half_w * 0.34, 0.08 * H)

    def P(x, z):
        return [cx + x, cy, z0 + z * H]

    out = [
        {"name": "hips", "head": P(0, 0.53), "tail": P(0, 0.60), "parent": None},
        {"name": "spine", "head": P(0, 0.60), "tail": P(0, 0.81), "parent": "hips"},
        {"name": "neck", "head": P(0, 0.81), "tail": P(0, 0.86), "parent": "spine"},
        {"name": "head", "head": P(0, 0.86), "tail": P(0, 1.0), "parent": "neck"},
    ]
    for side, sx in (("L", 1), ("R", -1)):
        out += [
            {"name": "shoulder." + side, "head": P(0.04 * H * sx, 0.79),
             "tail": P(x_arm * sx, 0.79), "parent": "spine"},
            {"name": "upperarm." + side, "head": P(x_arm * sx, 0.79),
             "tail": P(x_arm * sx, 0.62), "parent": "shoulder." + side},
            {"name": "forearm." + side, "head": P(x_arm * sx, 0.62),
             "tail": P(x_arm * sx, 0.47), "parent": "upperarm." + side},
            {"name": "hand." + side, "head": P(x_arm * sx, 0.47),
             "tail": P(x_arm * sx, 0.40), "parent": "forearm." + side},
            {"name": "thigh." + side, "head": P(x_hip * sx, 0.53),
             "tail": P(x_hip * sx, 0.28), "parent": "hips"},
            {"name": "shin." + side, "head": P(x_hip * sx, 0.28),
             "tail": P(x_hip * sx, 0.045), "parent": "thigh." + side},
            {"name": "foot." + side, "head": P(x_hip * sx, 0.045),
             "tail": [cx + x_hip * sx, cy - 0.09 * H, z0 + 0.02 * H],
             "parent": "shin." + side},
        ]
    return out


def _fit_spine(lo, hi):
    """Four bones up the middle - enough to bend, wave or topple anything."""
    H = hi.z - lo.z
    cx, cy, z0 = (lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z
    out, prev = [], None
    for i in range(4):
        name = "spine_%02d" % i
        out.append({"name": name,
                    "head": [cx, cy, z0 + H * i / 4.0],
                    "tail": [cx, cy, z0 + H * (i + 1) / 4.0],
                    "parent": prev})
        prev = name
    return out
