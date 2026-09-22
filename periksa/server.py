#!/usr/bin/env python3
"""
periksa — to inspect.

The Check stage: the last look at a model before it goes into a game, and the
place where the things that waste an afternoon are caught in a second.

Almost none of them are exotic. A downloaded character is ninety metres tall
because whoever made it worked in centimetres. Its origin is somewhere near
its left ear, so it rotates around nothing. It has no UVs, so every texture
will be one smeared pixel. It has forty materials, which is forty draw calls
for one prop. Each of those is obvious once you know, invisible until you do,
and every one of them is written down in the file itself.

So periksa reads the file. No Blender: a `.glb` carries its own table of
contents in a JSON chunk at the front — every mesh, every material, every
image, every animation, and the exact bounding box of each accessor — and that
is enough for everything here. It takes a few milliseconds, which is what
"light" was supposed to mean.

What it deliberately does not do is grade. Nothing here is wrong in the
abstract: a 400,000 triangle model is right for a cinematic and hopeless for a
crowd. Every finding says what it found, why it matters, and what to do — and
leaves the judgement where it belongs.
"""

import json
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "common"))

from serve import Tool, HOME     # noqa: E402

tool = Tool("periksa", __file__, "@@PERIKSA-READY@@", title="periksa")


# --------------------------------------------------------------------------
# reading a .glb without unpacking it
# --------------------------------------------------------------------------

def table_of_contents(path):
    """The JSON chunk at the front of a .glb, which describes everything."""
    with open(path, "rb") as f:
        header = f.read(12)
        if len(header) < 12 or header[:4] != b"glTF":
            raise ValueError("that is not a .glb")
        length = struct.unpack("<I", f.read(4))[0]
        kind = f.read(4)
        if kind != b"JSON":
            raise ValueError("that .glb does not start with its description")
        return json.loads(f.read(length))


def bounds(doc):
    """The whole model's box, in metres, from the accessors' own min and max.

    Every glTF accessor records the smallest and largest value it holds, so
    the model's extent is already written in the file and does not have to be
    worked out from the vertices. Node transforms are followed so a mesh
    scaled by its parent is measured at the size it will really be.
    """
    accessors = doc.get("accessors") or []
    meshes = doc.get("meshes") or []
    nodes = doc.get("nodes") or []

    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    found = False

    def visit(index, matrix):
        nonlocal found
        node = nodes[index]
        here = multiply(matrix, local(node))
        if node.get("mesh") is not None:
            for primitive in meshes[node["mesh"]].get("primitives", []):
                which = (primitive.get("attributes") or {}).get("POSITION")
                if which is None:
                    continue
                accessor = accessors[which]
                if not accessor.get("min") or not accessor.get("max"):
                    continue
                found = True
                for corner in corners(accessor["min"], accessor["max"]):
                    point = apply(here, corner)
                    for axis in range(3):
                        low[axis] = min(low[axis], point[axis])
                        high[axis] = max(high[axis], point[axis])
        for child in node.get("children", []):
            visit(child, here)

    roots = (doc.get("scenes") or [{}])[doc.get("scene", 0)].get("nodes", [])
    for index in roots:
        visit(index, IDENTITY)

    if not found:
        return None
    return [round(high[i] - low[i], 4) for i in range(3)], low, high


IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def local(node):
    """A node's own transform, as a column-major 4x4 the way glTF stores it."""
    if node.get("matrix"):
        return list(node["matrix"])
    t = node.get("translation") or [0, 0, 0]
    r = node.get("rotation") or [0, 0, 0, 1]
    s = node.get("scale") or [1, 1, 1]

    x, y, z, w = r
    rot = [
        1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w),
        2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w),
        2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y),
    ]
    return [
        rot[0] * s[0], rot[1] * s[0], rot[2] * s[0], 0,
        rot[3] * s[1], rot[4] * s[1], rot[5] * s[1], 0,
        rot[6] * s[2], rot[7] * s[2], rot[8] * s[2], 0,
        t[0], t[1], t[2], 1,
    ]


def multiply(a, b):
    out = [0.0] * 16
    for column in range(4):
        for row in range(4):
            out[column * 4 + row] = sum(
                a[k * 4 + row] * b[column * 4 + k] for k in range(4))
    return out


def apply(m, p):
    return [m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
            m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
            m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14]]


def corners(low, high):
    """All eight corners of a box. A rotated box cannot be measured from two
    of them — the other six may stick out further."""
    return [[low[0] if i & 1 else high[0],
             low[1] if i & 2 else high[1],
             low[2] if i & 4 else high[2]] for i in range(8)]


def triangles(doc):
    total = 0
    accessors = doc.get("accessors") or []
    for mesh in doc.get("meshes") or []:
        for primitive in mesh.get("primitives", []):
            mode = primitive.get("mode", 4)
            if mode != 4:                      # only TRIANGLES has triangles
                continue
            if primitive.get("indices") is not None:
                total += accessors[primitive["indices"]].get("count", 0) // 3
            else:
                which = (primitive.get("attributes") or {}).get("POSITION")
                if which is not None:
                    total += accessors[which].get("count", 0) // 3
    return total


# --------------------------------------------------------------------------
# what is worth saying about it
# --------------------------------------------------------------------------

# What a thing is for, and what that means for its weight. These are the
# numbers a game artist works to; none of them is a law.
ROLES = {
    "hero":       {"name": "Hero character", "tris": 60000,
                   "about": "The one the camera looks at. A main character, a boss."},
    "character":  {"name": "Character", "tris": 20000,
                   "about": "Someone in the world. An enemy, an NPC."},
    "prop":       {"name": "Prop", "tris": 5000,
                   "about": "A crate, a lamp, a sword. There are a lot of them."},
    "background": {"name": "Background", "tris": 1500,
                   "about": "Far away, or there are fifty on screen at once."},
}


def look(path, role):
    """Everything worth saying about one file."""
    doc = table_of_contents(path)
    size = os.path.getsize(path)
    box = bounds(doc)
    extent = box[0] if box else None
    low = box[1] if box else None

    meshes = doc.get("meshes") or []
    materials = doc.get("materials") or []
    images = doc.get("images") or []
    animations = doc.get("animations") or []
    skins = doc.get("skins") or []
    nodes = doc.get("nodes") or []
    tris = triangles(doc)

    bones = sum(len(s.get("joints") or []) for s in skins)
    has_uv = all(
        "TEXCOORD_0" in (p.get("attributes") or {})
        for m in meshes for p in m.get("primitives", []))
    has_normals = all(
        "NORMAL" in (p.get("attributes") or {})
        for m in meshes for p in m.get("primitives", []))

    facts = {
        "triangles": tris,
        "meshes": len(meshes),
        "materials": len(materials),
        "images": len(images),
        "animations": [a.get("name") or "unnamed" for a in animations],
        "bones": bones,
        "nodes": len(nodes),
        "bytes": size,
        "extent": extent,
        "uvs": has_uv,
        "normals": has_normals,
        "generator": (doc.get("asset") or {}).get("generator", ""),
    }

    return {"facts": facts, "findings": judge(facts, low, role, meshes)}


def judge(f, low, role, meshes):
    """Turn the facts into things worth saying. Never a grade, always a why."""
    out = []
    budget = ROLES.get(role, ROLES["prop"])

    def say(level, what, why, todo=""):
        out.append({"level": level, "what": what, "why": why, "todo": todo})

    # ── size ───────────────────────────────────────────────────────────
    extent = f["extent"]
    if not extent:
        say("bad", "It has no geometry with a recorded size",
            "Every glTF accessor records its own bounds, so a file without "
            "them is either empty or was written by something broken.")
    else:
        tall = max(extent)
        if tall > 50:
            say("bad", "It is %.0f metres across" % tall,
                "Almost always a unit mix-up: whoever made it worked in "
                "centimetres and the exporter believed them. In a game engine "
                "this will fill the sky.",
                "Scale it by 0.01 before anything else.")
        elif tall < 0.02:
            say("bad", "It is %.0f millimetres across" % (tall * 1000),
                "The other half of the same mistake — metres read as "
                "millimetres. It will be a speck on the floor.",
                "Scale it by 100.")
        elif role in ("hero", "character") and not (1.2 <= tall <= 2.6):
            say("watch", "It is %.2f m tall, which is unusual for a person" % tall,
                "Characters are made to human size so animation, cameras and "
                "collision all agree with each other. An adult is about 1.7 m.",
                "Check the scale unless it is meant to be a child or a giant.")
        else:
            say("good", "It is %.2f × %.2f × %.2f m"
                % (extent[0], extent[1], extent[2]),
                "A believable real-world size, so it will drop into a scene "
                "at the size you expect.")

    # ── where its origin is ────────────────────────────────────────────
    if low and extent:
        tall = max(extent)
        # A model's origin should sit on the ground between its feet: that is
        # where an engine puts it, where it rotates about, and where a
        # navigation mesh meets it.
        off_ground = abs(low[1]) / tall if tall else 0
        drift = max(abs(low[0] + extent[0] / 2), abs(low[2] + extent[2] / 2)) / tall
        if off_ground > 0.08 or drift > 0.12:
            say("watch", "Its origin is not on the ground beneath it",
                "An engine places, rotates and grounds a model about its "
                "origin. Anywhere else and it hovers, sinks, or swings around "
                "a point outside itself.",
                "Move the origin to the floor, centred between its feet.")
        else:
            say("good", "Its origin sits on the ground beneath it",
                "It will stand on the floor and turn about itself.")

    # ── weight ─────────────────────────────────────────────────────────
    tris = f["triangles"]
    limit = budget["tris"]
    if tris > limit * 2:
        say("bad", "%s triangles, for a %s" % (f"{tris:,}", budget["name"].lower()),
            "More than twice what that job usually gets. On a machine with "
            "8 GB and an integrated GPU this is felt, not measured.",
            "Send it through jaring — %s is the usual budget." % f"{limit:,}")
    elif tris > limit:
        say("watch", "%s triangles, a little over budget" % f"{tris:,}",
            "A %s is usually about %s. Fine for one of them; not for thirty."
            % (budget["name"].lower(), f"{limit:,}"))
    else:
        say("good", "%s triangles" % f"{tris:,}",
            "Within what a %s usually gets (%s)."
            % (budget["name"].lower(), f"{limit:,}"))

    # ── the things that make a texture not work ────────────────────────
    if not f["uvs"]:
        say("bad", "Some of it has no UVs",
            "A texture needs UVs to know where to sit. Without them it shows "
            "as one smeared pixel, and nothing anywhere says why.",
            "jaring unwraps it as part of a remesh.")
    if not f["normals"]:
        say("watch", "Some of it has no normals",
            "The engine will work them out flat, so every face catches the "
            "light on its own and a smooth surface reads as faceted.")
    if f["materials"] == 0 and f["meshes"]:
        say("watch", "It has no materials at all",
            "It will arrive as default grey. That is fine if you are about to "
            "give it one — kulit is next door.")
    elif f["materials"] > 8:
        say("watch", "%d materials" % f["materials"],
            "Each one is its own draw call. A prop with a dozen is a dozen "
            "times the cost of a prop with one.",
            "Merge the ones that are really the same.")

    # ── animation ──────────────────────────────────────────────────────
    if f["bones"]:
        say("good", "Rigged: %d bones, %d %s"
            % (f["bones"], len(f["animations"]),
               "clip" if len(f["animations"]) == 1 else "clips"),
            "It can be animated as it is." if f["animations"] else
            "It has a skeleton but no clips yet — gerak is where those are made.")
        unnamed = [a for a in f["animations"] if a == "unnamed"]
        if unnamed:
            say("watch", "%d clip%s with no name"
                % (len(unnamed), "" if len(unnamed) == 1 else "s"),
                "An engine calls a clip by name. Unnamed ones have to be "
                "picked by number, which changes whenever the file is "
                "re-exported.")
    elif f["animations"]:
        say("watch", "It has clips but no skeleton",
            "The animation moves whole objects rather than a rig. That works, "
            "but nothing can be retargeted onto it.")

    # ── weight on disk ─────────────────────────────────────────────────
    if f["bytes"] > 25 * 1024 * 1024:
        say("watch", "%.0f MB in one file" % (f["bytes"] / 1048576),
            "Usually the textures rather than the mesh. Every one of them has "
            "to fit in video memory at the same time as everything else.",
            "Halve the texture size; 4K on a prop is rarely seen.")

    order = {"bad": 0, "watch": 1, "good": 2}
    out.sort(key=lambda i: order[i["level"]])
    return out


# --------------------------------------------------------------------------
# routes
# --------------------------------------------------------------------------

@tool.get("/api/roles")
def roles(query):
    return {"roles": [dict(v, id=k) for k, v in ROLES.items()]}


@tool.get("/api/look")
def api_look(query):
    path = os.path.expanduser(query.get("path") or "")
    role = query.get("role") or "prop"
    if not path or not os.path.exists(path):
        return {"ok": False, "problem": "that file is not there any more"}
    if not tool.allowed(path):
        return {"ok": False, "problem": "that file is somewhere periksa is "
                                        "not allowed to read"}
    if not path.lower().endswith((".glb",)):
        return {"ok": False, "problem": "periksa reads .glb files. Export one "
                                        "from wherever this came from."}
    try:
        answer = look(path, role)
    except Exception as err:
        return {"ok": False, "problem": str(err)}

    answer["ok"] = True
    answer["path"] = path
    answer["shown"] = path.replace(HOME, "~")
    answer["name"] = os.path.basename(path)
    counts = {level: sum(1 for f in answer["findings"] if f["level"] == level)
              for level in ("bad", "watch", "good")}
    answer["counts"] = counts
    tool.log("looked at %s: %d bad, %d to watch"
             % (answer["name"], counts["bad"], counts["watch"]))
    return answer


if __name__ == "__main__":
    sys.exit(tool.run())
