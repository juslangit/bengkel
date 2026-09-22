#!/usr/bin/env python3
"""
hantar — to deliver.

The last stage. A model is finished, and finished is not the same as *in the
game*. The last mile is four small things that are each easy to get wrong:

    the right place       every project has its own layout, and none of them
                          is the layout a tool would have chosen
    the right name        one project spells a file boss-walk.glb and another
                          Boss_Walk.glb, and an engine cares
    the right size        periksa says the origin is at its ear and it is
                          ninety metres tall; something has to actually move it
    the right format      Godot takes .glb, Unreal wants .fbx

hantar does not invent a layout. It looks at where each project already keeps
its models and what those files are already called, and follows that. A tool
that imposes its own convention on twelve existing projects is a tool that
makes work rather than saving it.
"""

import os
import re
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "common"))

from serve import Tool, HOME     # noqa: E402

tool = Tool("hantar", __file__, "@@HANTAR-READY@@", title="hantar")

GAMES = os.path.join(HOME, "Desktop", "project", "game")
MODEL_EXT = (".glb", ".gltf", ".fbx", ".obj", ".blend")


# --------------------------------------------------------------------------
# what a project is and what it wants
# --------------------------------------------------------------------------

def engine_of(folder):
    """Which engine a project is, from the file only that engine leaves."""
    if os.path.exists(os.path.join(folder, "project.godot")):
        return "godot"
    for name in os.listdir(folder):
        if name.endswith(".uproject"):
            return "unreal"
    if os.path.exists(os.path.join(folder, "index.html")) \
            or os.path.exists(os.path.join(folder, "package.json")):
        return "web"
    return "unknown"


# What each engine takes, and what it does about a model's size.
ENGINES = {
    "godot":   {"name": "Godot", "format": "glb", "unit": 1.0,
                "about": ".glb, one metre to the unit."},
    "unreal":  {"name": "Unreal", "format": "fbx", "unit": 100.0,
                "about": ".fbx, and Unreal counts in centimetres — a 1.8 m "
                         "character is 180 units there."},
    "web":     {"name": "Web", "format": "glb", "unit": 1.0,
                "about": ".glb, which three.js and Babylon both read."},
    "unknown": {"name": "Unknown", "format": "glb", "unit": 1.0,
                "about": ".glb, the safest thing to hand anything."},
}


def style_of(names):
    """Work out how a folder already spells its file names.

    Not to be clever — to be consistent. A project that has boss-walk.glb and
    walker-walk.glb in it should not gain a Boss_Walk.glb because a tool had
    its own opinion.
    """
    stems = [os.path.splitext(n)[0] for n in names
             if n.lower().endswith(MODEL_EXT)]
    if not stems:
        return "kebab"
    dashes = sum(1 for s in stems if "-" in s)
    unders = sum(1 for s in stems if "_" in s)
    camels = sum(1 for s in stems if re.match(r"^[A-Z][a-z]", s))
    if unders > dashes and unders >= camels:
        return "snake"
    if camels > dashes and camels > unders:
        return "pascal"
    return "kebab"


def spell(name, style):
    """Put a name into a folder's own style."""
    words = [w for w in re.split(r"[^A-Za-z0-9]+|(?<=[a-z])(?=[A-Z])", name) if w]
    words = [w.lower() for w in words]
    if not words:
        return "model"
    if style == "snake":
        return "_".join(words)
    if style == "pascal":
        return "".join(w.capitalize() for w in words)
    return "-".join(words)


def places(folder):
    """Where this project already keeps models, most-used first.

    Found rather than assumed: the folder with the most models in it is where
    the next one belongs, and a project that keeps nothing yet gets the one
    sensible suggestion instead of a guess dressed up as knowledge.
    """
    found = {}
    for dirpath, dirnames, filenames in os.walk(folder):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in
                       ("node_modules", "build", "dist", "__pycache__",
                        ".godot", "Binaries", "Intermediate", "Saved")]
        models = [f for f in filenames if f.lower().endswith(MODEL_EXT)]
        if models:
            found[dirpath] = models

    def rank(item):
        """How likely a folder is to be where the next model belongs.

        Not simply the one with the most in it. A per-download folder holds
        exactly one model named after itself, and `docs/` holds working copies
        rather than what the game loads — both would otherwise win on count
        alone and send the model somewhere nobody looks.
        """
        path, models = item
        here = os.path.relpath(path, folder)
        score = min(len(models), 20)
        if "/assets/" in "/%s/" % here:
            score += 25
        if "/docs/" in "/%s/" % here or here.startswith("docs"):
            score -= 30
        if len(models) == 1:
            stem = os.path.splitext(models[0])[0].lower()
            if os.path.basename(path).lower() in (stem, stem.replace("_", "-")):
                score -= 25       # a folder named after its one download
        score -= here.count(os.sep) * 3      # shallower is more likely the home
        return -score

    out = []
    for path, models in sorted(found.items(), key=rank):
        out.append({
            "path": path,
            "shown": os.path.relpath(path, folder),
            "count": len(models),
            "style": style_of(models),
            "examples": sorted(models)[:3],
        })

    # An empty assets/models is still somewhere a model belongs — it was made
    # for exactly this and has simply not been used yet. Without it, a project
    # whose only models sit in per-download folders would be offered nothing
    # but those.
    for likely in ("assets/models", "assets/characters", "assets/meshes"):
        path = os.path.join(folder, *likely.split("/"))
        if os.path.isdir(path) and path not in found:
            out.append({"path": path, "shown": likely, "count": 0,
                        "style": "kebab", "examples": [], "empty": True})

    if not out:
        # Nowhere yet, and nothing made for it. One suggestion, marked as one.
        suggested = os.path.join(folder, "assets", "models")
        out.append({"path": suggested, "shown": "assets/models", "count": 0,
                    "style": "kebab", "examples": [], "new": True})
    return out[:8]


@tool.get("/api/projects")
def projects(query):
    """Every game project on the machine, and what each one takes."""
    out = []
    for name in sorted(os.listdir(GAMES)) if os.path.isdir(GAMES) else []:
        folder = os.path.join(GAMES, name)
        if not os.path.isdir(folder) or name.startswith("."):
            continue
        engine = engine_of(folder)
        out.append({
            "id": name,
            "name": name,
            "folder": folder,
            "engine": engine,
            "engineName": ENGINES[engine]["name"],
            "format": ENGINES[engine]["format"],
            "about": ENGINES[engine]["about"],
            "places": places(folder),
        })
    return {"projects": out, "where": GAMES.replace(HOME, "~")}


# --------------------------------------------------------------------------
# delivering
# --------------------------------------------------------------------------

@tool.post("/api/send")
def send(body):
    """Put a model into a project, in the shape that project wants."""
    source = os.path.expanduser(body.get("path") or "")
    if not source or not os.path.exists(source):
        return {"ok": False, "problems": ["that file is not there any more"]}
    if not tool.allowed(source):
        return {"ok": False, "problems": ["that file is somewhere hantar is "
                                          "not allowed to read"]}

    into = body.get("into") or ""
    # Only inside a game project. Nothing here should be able to write to an
    # arbitrary path just because a page asked it to.
    real = os.path.realpath(into)
    if not real.startswith(os.path.realpath(GAMES) + os.sep):
        return {"ok": False, "problems": [
            "hantar only delivers into %s" % GAMES.replace(HOME, "~")]}

    engine = body.get("engine") or "godot"
    fmt = ENGINES.get(engine, ENGINES["godot"])["format"]
    unit = ENGINES.get(engine, ENGINES["godot"])["unit"]
    name = spell(body.get("name") or os.path.splitext(os.path.basename(source))[0],
                 body.get("style") or "kebab")
    target = os.path.join(real, "%s.%s" % (name, fmt))

    if os.path.exists(target) and not body.get("overwrite"):
        return {"ok": False, "problems": [
            "%s is already there. Rename it, or say to replace it."
            % os.path.basename(target)],
            "exists": True}

    answer = tool.blender("ship.py", {
        "job": "ship",
        "source": source,
        "target": target,
        "format": fmt,
        "unit": unit,
        "ground": bool(body.get("ground", True)),
        "height": float(body.get("height") or 0),
    }, timeout=600)

    if answer.get("ok"):
        tool.permit(target)
        answer["shown"] = target.replace(HOME, "~")
        answer["folder"] = real
        answer["name"] = os.path.basename(target)
        note(real, source, answer, engine)
        tool.log("delivered %s into %s" % (answer["name"],
                                           real.replace(HOME, "~")))
    return answer


def note(folder, source, answer, engine):
    """A line in the folder's own record, rather than a file per model.

    Twelve separate notes beside twelve models is twelve files nobody reads.
    One growing list in the folder they all live in is a thing you can glance
    down.
    """
    path = os.path.join(folder, "WHERE-THESE-CAME-FROM.md")
    fresh = not os.path.exists(path)
    with open(path, "a") as f:
        if fresh:
            f.write("# Where these came from\n\n"
                    "Written by hantar, one line per model delivered here.\n\n"
                    "| Model | From | Fixed on the way in |\n"
                    "|---|---|---|\n")
        fixes = ", ".join(answer.get("fixed") or []) or "nothing needed"
        f.write("| `%s` | %s | %s |\n"
                % (answer["name"], source.replace(HOME, "~"), fixes))


@tool.get("/api/landing")
def landing(query):
    """Where a model would land, before anything is written.

    Answered without touching the disk, because a delivery you cannot see in
    advance is one you find out about by looking in Finder afterwards.
    """
    name = spell(query.get("name") or "model", query.get("style") or "kebab")
    engine = query.get("engine") or "godot"
    fmt = ENGINES.get(engine, ENGINES["godot"])["format"]
    into = query.get("into") or ""
    target = os.path.join(into, "%s.%s" % (name, fmt))
    return {"name": "%s.%s" % (name, fmt),
            "target": target,
            "shown": target.replace(HOME, "~"),
            "exists": os.path.exists(target)}


if __name__ == "__main__":
    sys.exit(tool.run())
