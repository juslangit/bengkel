"""
Put a model into the shape an engine wants, inside a headless Blender.

Three things, in this order, because each depends on the one before:

    1. ground     move the origin to the floor, centred between its feet
    2. scale      to a real height if one was asked for, then into the
                  engine's units
    3. export     .glb for Godot and the web, .fbx for Unreal

periksa says an origin is in the wrong place and a model is the wrong size.
This is the thing that actually moves them — a checker that only reports leaves
you to do the work by hand, which is the work you were trying to avoid.

Job:

    {"job": "ship", "source": "...glb", "target": "...fbx",
     "format": "fbx", "unit": 100.0, "ground": true, "height": 1.8}

`unit` is what the engine counts in: 1.0 for Godot and the web, 100.0 for
Unreal, which measures in centimetres.
"""

import json
import os
import sys
import time

import bpy
from mathutils import Vector

ANSWER = "@@JOB@@"


def load(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    lower = path.lower()
    if lower.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    elif lower.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    elif lower.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path)
    elif lower.endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        raise RuntimeError("hantar does not know how to open %s"
                           % os.path.splitext(path)[1])
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def world_box(objects):
    """The box around everything, in world space."""
    low = Vector((float("inf"),) * 3)
    high = Vector((float("-inf"),) * 3)
    for obj in objects:
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner)
            for axis in range(3):
                low[axis] = min(low[axis], point[axis])
                high[axis] = max(high[axis], point[axis])
    return low, high


def roots():
    """The top of the tree — moving a child moves it out from under its parent."""
    return [o for o in bpy.context.scene.objects if o.parent is None]


def run(job):
    source = job["source"]
    target = job["target"]
    os.makedirs(os.path.dirname(target), exist_ok=True)

    meshes = load(source)
    if not meshes:
        raise RuntimeError("there is no mesh in that file")

    low, high = world_box(meshes)
    was = [round(high[i] - low[i], 4) for i in range(3)]
    fixed = []

    # Blender is Z-up, so "how tall" is Z here. glTF and the engines are Y-up,
    # and the exporters convert; doing it in Blender's own axes and letting
    # them convert is the only way not to be wrong in one of the two.
    tall = high.z - low.z

    # ── 1. put it on the floor ────────────────────────────────────────
    #
    # An engine places, rotates and grounds a model about its origin. Anywhere
    # else and it hovers, sinks, or swings around a point outside itself.
    if job.get("ground") and tall > 0:
        middle = (low + high) / 2
        offset = Vector((-middle.x, -middle.y, -low.z))
        if offset.length > tall * 0.02:
            for obj in roots():
                obj.location += offset
            fixed.append("moved the origin to the floor")
        low, high = low + offset, high + offset

    # ── 2. make it the right size ─────────────────────────────────────
    want = float(job.get("height") or 0)
    if want > 0 and tall > 0:
        factor = want / tall
        if abs(factor - 1.0) > 0.02:
            for obj in roots():
                obj.scale *= factor
                obj.location *= factor
            fixed.append("scaled it to %.2f m (x%.3f)" % (want, factor))
            tall = want

    # Unreal counts in centimetres: a 1.8 m character is 180 units there. The
    # FBX exporter has its own scale setting, so this is done there rather than
    # by moving the geometry, and the .blend stays in metres.
    unit = float(job.get("unit") or 1.0)

    bpy.context.view_layer.update()
    low, high = world_box([o for o in bpy.context.scene.objects if o.type == "MESH"])
    now = [round(high[i] - low[i], 4) for i in range(3)]

    for obj in bpy.context.scene.objects:
        obj.select_set(True)

    fmt = job.get("format", "glb")
    if fmt == "fbx":
        bpy.ops.export_scene.fbx(
            filepath=target, use_selection=False,
            apply_unit_scale=True, global_scale=unit,
            # Unreal reads -Z forward, Y up. Anything else arrives lying on
            # its side, which is the other half of every "why is my model
            # sideways" afternoon.
            axis_forward="-Z", axis_up="Y",
            bake_space_transform=True,
            add_leaf_bones=False, path_mode="COPY", embed_textures=True)
        if unit != 1.0:
            fixed.append("exported at %g units to the metre, the way %s counts"
                         % (unit, "Unreal"))
    else:
        bpy.ops.export_scene.gltf(filepath=target, export_format="GLB",
                                  use_selection=False, export_yup=True,
                                  export_apply=True)

    return {"ok": True, "target": target, "was": was, "now": now,
            "fixed": fixed, "bytes": os.path.getsize(target)}


def main():
    job_file = sys.argv[sys.argv.index("--") + 1]
    with open(job_file) as f:
        job = json.load(f)
    started = time.time()
    try:
        answer = run(job)
    except Exception as err:
        answer = {"ok": False, "problems": [str(err)]}
    answer["seconds"] = round(time.time() - started, 1)
    print(ANSWER + json.dumps(answer), flush=True)


if __name__ == "__main__":
    main()
