"""
The Blender half of boneka.

Blender is started once and left running. It reads one JSON command per line on
stdin and answers with one JSON event per line on stdout, each marked with
@@BK@@ so that Blender's own chatter can be ignored. Keeping one process alive
is what makes the buttons instant: the scene, the rig and the pose are all still
there from the last command.

    blender --background --python worker.py -- <session-dir>
"""

import json
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import bpy                                            # noqa: E402

import anim                                           # noqa: E402
import build                                          # noqa: E402
import recipes                                        # noqa: E402
import rig                                            # noqa: E402

MARK = "@@BK@@"
SESSION = sys.argv[-1] if "--" in sys.argv else os.path.join(HERE, "..", "sessions", "default")
SESSION = os.path.abspath(SESSION)

STATE = {"plan": None, "rig": None, "body": None, "anim": None, "counter": 0,
         "imported": False}


def emit(event, **fields):
    fields["event"] = event
    sys.stdout.write("%s %s\n" % (MARK, json.dumps(fields)))
    sys.stdout.flush()


def out_path(name):
    return os.path.join(SESSION, name)


def rel(path):
    return os.path.relpath(path, SESSION)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_build(msg):
    prompt = msg.get("prompt", "")
    plan = recipes.plan_from_prompt(prompt)
    STATE.update(plan=plan, rig=None, body=None, anim=None, imported=False)
    STATE["counter"] += 1
    tag = "b%03d" % STATE["counter"]

    emit("plan", plan={k: v for k, v in plan.items() if k != "steps"},
         total=len(plan["steps"]),
         parts=[s["label"] for s in plan["steps"]])

    def on_step(i, st, obj):
        part_file = out_path("%s_part_%03d.glb" % (tag, i))
        build.export_selection([obj], part_file)
        emit("step", i=i, total=len(plan["steps"]), label=st["label"],
             part=st["part"], file=rel(part_file), color=st["color"])

    build.build_plan(plan, on_step=on_step)

    whole = out_path("%s_model.glb" % tag)
    build.export_scene(whole)
    emit("built", file=rel(whole), name=plan["name"], archetype=plan["archetype"],
         height=plan["height"], parts=len(plan["steps"]),
         triangles=_triangle_count(), rig_profile=plan["rig_profile"])


def cmd_rig(msg):
    if STATE["imported"] or not STATE["plan"]:
        arm_obj, body, bones = rig.rig_fitted(msg.get("profile", "humanoid"))
        profile = msg.get("profile", "humanoid")
        exact = False
    else:
        arm_obj, body, bones = rig.rig_from_plan(STATE["plan"])
        profile = STATE["plan"]["rig_profile"]
        exact = True
    STATE.update(rig=arm_obj.name, body=body.name, anim=None)
    STATE["counter"] += 1
    path = out_path("r%03d_rigged.glb" % STATE["counter"])
    build.export_scene(path)
    emit("rigged", file=rel(path), bones=bones, count=len(bones),
         profile=profile, exact=exact)


def cmd_animate(msg):
    arm_obj = _require_rig()
    profile = (STATE["plan"] or {}).get("rig_profile", "humanoid")
    if STATE["imported"]:
        profile = msg.get("profile", "humanoid")
    wanted = anim.read_prompt(msg.get("prompt", "idle"))
    info = anim.bake(arm_obj, profile, wanted["move"], speed=wanted["speed"],
                     amount=wanted["amount"], loop=wanted["loop"])
    STATE["anim"] = info
    STATE["counter"] += 1
    path = out_path("a%03d_%s.glb" % (STATE["counter"], info["move"]))
    build.export_scene(path, animations=True)
    info["file"] = rel(path)
    info["speed"] = wanted["speed"]
    info["amount"] = wanted["amount"]
    emit("animated", **info)


def cmd_clip(msg):
    arm_obj = _require_rig()
    path = msg["path"]
    if not os.path.isabs(path):
        path = os.path.join(HERE, "..", "animations", path)
    info = anim.import_clip(os.path.abspath(path), arm_obj)
    STATE["anim"] = info
    STATE["counter"] += 1
    out = out_path("a%03d_clip.glb" % STATE["counter"])
    build.export_scene(out, animations=True)
    info["file"] = rel(out)
    emit("animated", **info)


def cmd_rest(msg):
    arm_obj = _require_rig()
    anim.clear_pose(arm_obj)
    STATE["anim"] = None
    STATE["counter"] += 1
    path = out_path("r%03d_rest.glb" % STATE["counter"])
    build.export_scene(path)
    emit("animated", move="rest", frames=1, fps=30, loop=False, bones=[],
         file=rel(path))


def cmd_import(msg):
    """A file from somewhere else - a Meshy download, or any .glb/.fbx/.obj."""
    path = os.path.abspath(msg["path"])
    build.clear_scene()
    ext = os.path.splitext(path)[1].lower()
    if ext == ".glb" or ext == ".gltf":
        bpy.ops.import_scene.gltf(filepath=path)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=path)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=path)
    else:
        raise RuntimeError("boneka can read .glb, .gltf, .fbx and .obj files")
    STATE.update(plan=None, rig=None, body=None, anim=None, imported=True)
    STATE["counter"] += 1
    out = out_path("i%03d_model.glb" % STATE["counter"])
    build.export_scene(out)
    emit("built", file=rel(out), name=os.path.basename(path), archetype="imported",
         height=_scene_height(), parts=len(build._mesh_names()) if hasattr(
             build, "_mesh_names") else 0,
         triangles=_triangle_count(), rig_profile="humanoid")


def cmd_export(msg):
    fmt = msg.get("format", "glb")
    name = (STATE["plan"] or {}).get("name", "model").replace(" ", "_") or "model"
    animated = STATE["anim"] is not None
    path = out_path("export_%s.%s" % (name, fmt))
    if fmt == "glb":
        build.export_scene(path, animations=animated)
    elif fmt == "fbx":
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.export_scene.fbx(filepath=path, use_selection=False,
                                 add_leaf_bones=False, bake_anim=animated,
                                 path_mode="COPY", embed_textures=True)
    elif fmt == "blend":
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
    else:
        raise RuntimeError("boneka exports glb, fbx or blend")
    emit("exported", file=rel(path), format=fmt, animated=animated)


def cmd_ping(msg):
    emit("pong", blender=bpy.app.version_string, session=SESSION)


def _require_rig():
    name = STATE.get("rig")
    obj = bpy.context.scene.objects.get(name) if name else None
    if obj is None:
        raise RuntimeError("press Auto-Rig first - there are no bones to move yet")
    return obj


def _triangle_count():
    total = 0
    depsgraph = bpy.context.evaluated_depsgraph_get()
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        mesh = obj.evaluated_get(depsgraph).to_mesh()
        total += sum(max(len(p.vertices) - 2, 0) for p in mesh.polygons)
        obj.evaluated_get(depsgraph).to_mesh_clear()
    return total


def _scene_height():
    zs = []
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            for corner in obj.bound_box:
                zs.append((obj.matrix_world @ __import__("mathutils").Vector(corner)).z)
    return round(max(zs) - min(zs), 3) if zs else 0.0


COMMANDS = {"build": cmd_build, "rig": cmd_rig, "animate": cmd_animate,
            "clip": cmd_clip, "rest": cmd_rest, "import": cmd_import,
            "export": cmd_export, "ping": cmd_ping}


def main():
    os.makedirs(SESSION, exist_ok=True)
    build.clear_scene()
    emit("ready", blender=bpy.app.version_string, session=SESSION,
         moves=sorted(anim.MOVES), props=sorted(recipes.PROPS))
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            emit("error", message="could not read that command")
            continue
        name = msg.get("cmd")
        handler = COMMANDS.get(name)
        if handler is None:
            emit("error", message="unknown command %r" % name)
            continue
        try:
            handler(msg)
        except Exception as exc:                       # noqa: BLE001
            emit("error", message=str(exc) or exc.__class__.__name__,
                 detail=traceback.format_exc()[-1200:], cmd=name)
        emit("idle", cmd=name)


if __name__ == "__main__":
    main()
