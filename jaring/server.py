#!/usr/bin/env python3
"""
jaring — the net.

The third stage of the pipeline, between finding something and moving it.

A model off Sketchfab looks right and is useless: half a million triangles, no
UVs worth the name, and a surface nobody can rig. A game wants a tenth of that,
laid out in even quads, with the lost detail baked into a normal map. Blender
can do every step of that, and doing it by hand is five minutes of clicking
through four different panels, each of which asks a question in the wrong
units.

jaring asks one question — how fine? — in centimetres, which is a thing you can
actually picture, and does the rest with nobody watching.

The heavy work is in blender/remesh.py, run headless. This file is only the
door: it takes the model, asks Blender, and hands back what came out.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "common"))

from serve import Tool, HOME, SAFE_NAME     # noqa: E402

tool = Tool("jaring", __file__, "@@JARING-READY@@", title="jaring")


# The three answers to "how fine?", in the only unit that means anything when
# you are looking at a model: how wide one quad is. A 2 cm quad on a human-
# sized character is roughly a knuckle.
PRESETS = {
    "hero":       {"quad_cm": 0.8, "texture": 4096, "lods": 3,
                   "name": "Hero", "about": "Close to the camera. Heavy, detailed."},
    "game":       {"quad_cm": 2.0, "texture": 2048, "lods": 2,
                   "name": "Game", "about": "The usual choice. Light enough to animate."},
    "background": {"quad_cm": 6.0, "texture": 1024, "lods": 1,
                   "name": "Background", "about": "Far away, or there are fifty of them."},
}


@tool.get("/api/presets")
def presets(query):
    return {"presets": [dict(v, id=k) for k, v in PRESETS.items()]}


@tool.get("/api/estimate")
def estimate(query):
    """How many faces a given quad size works out to, for a given surface area.

    The page already knows the model's surface area — it loaded the thing to
    show it — so this is the same arithmetic the remesher will do, done here so
    the number can move while he drags the slider instead of appearing after a
    minute of Blender.
    """
    try:
        area = float(query.get("area") or 0)
        quad_cm = float(query.get("quad_cm") or 2.0)
    except ValueError:
        return {"faces": 0}
    side = max(quad_cm, 0.01) / 100.0
    return {"faces": max(20, min(int(area / (side * side)), 500000))}


@tool.post("/api/remesh")
def remesh(body):
    """Put one model through the whole chain."""
    source = os.path.expanduser(body.get("path") or "")
    if not source or not os.path.exists(source):
        return {"ok": False, "problems": ["that file is not there any more"]}
    if not tool.allowed(source):
        return {"ok": False, "problems": ["that file is somewhere jaring is not "
                                          "allowed to read"]}

    preset = PRESETS.get(body.get("preset") or "", PRESETS["game"])
    stem = SAFE_NAME.sub("-", os.path.splitext(os.path.basename(source))[0]
                         .lower()).strip("-") or "model"
    out = os.path.join(tool.out, stem)

    job = {
        "job": "remesh",
        "source": source,
        "out": out,
        "name": stem,
        "quad_cm": float(body.get("quad_cm") or preset["quad_cm"]),
        "texture": int(body.get("texture") or preset["texture"]),
        "lods": int(body.get("lods") if body.get("lods") is not None
                    else preset["lods"]),
        "bake": bool(body.get("bake", True)),
        "symmetry": bool(body.get("symmetry", True)),
        "sharp": bool(body.get("sharp", True)),
    }

    # Quadriflow on a heavy mesh is minutes, not seconds, and a bake at 4K on
    # top of it is minutes again. Twenty is generous rather than optimistic.
    answer = tool.blender("remesh.py", job, timeout=1200)

    if answer.get("ok"):
        for level in answer.get("lods", []):
            tool.permit(level["path"])
        if answer.get("normal"):
            tool.permit(answer["normal"])
        answer["shown"] = answer["glb"].replace(HOME, "~")
        answer["folder"] = out
        answer["saved"] = round(
            100.0 * (1 - answer["after"] / max(answer["before"], 1)))

        # A quad size finer than the model needs rebuilds it with more faces
        # than it started with. That is not a failure - the result still has
        # clean quads, real UVs and a baked map, which the download did not -
        # but it is not the lighter model he pressed the button for, and
        # saying "-2% lighter" is no way to tell him.
        if answer["saved"] <= 0:
            answer["notes"].append(
                "It came out %s heavier, not lighter: %s cm quads are finer "
                "than this model needed. It is cleaner than it was — even "
                "quads, real UVs, a baked map — but for a lighter one, drag "
                "the quad size up."
                % ("%d%%" % abs(answer["saved"]) if answer["saved"] else "no",
                   job["quad_cm"]))
        note(out, source, answer, job)
        tool.log("remeshed %s: %d → %d triangles"
                 % (stem, answer["before"], answer["after"]))
    return answer


def note(folder, source, answer, job):
    """Write down what was done to it, beside the result.

    A month later the question is always the same — what settings gave me this,
    and what was it before? — and the answer is never anywhere.
    """
    with open(os.path.join(folder, "WHAT-JARING-DID.md"), "w") as f:
        f.write("# %s\n\n" % os.path.basename(answer["glb"]))
        f.write("- **From:** %s\n" % source.replace(HOME, "~"))
        f.write("- **Was:** %s triangles\n" % f"{answer['before']:,}")
        f.write("- **Now:** %s triangles (%d%% %s)\n"
                % (f"{answer['after']:,}", abs(answer["saved"]),
                   "lighter" if answer["saved"] >= 0 else "heavier"))
        f.write("- **Quad size:** %s cm\n" % job["quad_cm"])
        f.write("- **Remeshed with:** %s\n" % answer["how"])
        f.write("- **Normal map:** %s\n"
                % (("%d x %d" % (job["texture"], job["texture"]))
                   if answer.get("normal") else "none"))
        f.write("- **UV islands fill:** %s%% of the map\n" % answer["coverage"])
        if len(answer.get("lods", [])) > 1:
            f.write("- **LODs:** %s\n" % ", ".join(
                "LOD%d %s tris" % (l["level"], f"{l['tris']:,}")
                for l in answer["lods"]))
        for problem in answer.get("notes", []):
            f.write("\n> %s\n" % problem)
        f.write("\nThe normal map is already wired into the .glb's material, so "
                "the model carries its detail wherever it goes.\n")


@tool.get("/api/mine")
def mine(query):
    """Everything jaring has already made."""
    out = []
    if os.path.isdir(tool.out):
        for name in sorted(os.listdir(tool.out)):
            folder = os.path.join(tool.out, name)
            glb = os.path.join(folder, "%s.glb" % name)
            if not os.path.exists(glb):
                continue
            tool.permit(glb)
            out.append({
                "id": name, "title": name, "path": glb,
                "shown": glb.replace(HOME, "~"),
                "bytes": os.path.getsize(glb),
                "model": True,
            })
    out.sort(key=lambda i: -os.path.getmtime(i["path"]))
    return {"items": out}


if __name__ == "__main__":
    sys.exit(tool.run())
