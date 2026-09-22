#!/usr/bin/env python3
"""
kulit — the skin.

The Dress stage. jaring hands over a clean grey mesh with a normal map and no
colour; pasar hands over a download whose materials are twelve slots of
somebody else's idea. kulit is where a model gets its surface: a colour and a
material for each part, and real maps rather than a flat slab.

None of the photograph-to-material work is written here. boneka already turns
one Texturelabs photograph into a detail map, a normal map and a roughness map
— see `boneka/tools/pbr.py` — and that is the same job, so kulit imports it
rather than growing a second version that drifts. The difference between the
two tools is what they dress: boneka dresses what it built and knows the name
of every part, kulit dresses a model that arrived from anywhere.

The licence matters here more than anywhere else in the workshop. Texturelabs
is free to use commercially and explicitly allows a texture inside a finished
game, but forbids handing someone a model with the texture extractable from
it. So every dressed export writes the restriction down beside itself.
"""

import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "common"))

from serve import Tool, HOME, SAFE_NAME     # noqa: E402

tool = Tool("kulit", __file__, "@@KULIT-READY@@", title="kulit")

BONEKA = os.path.join(os.path.dirname(tool.here), "boneka")


def borrow(name, path):
    """Load one of boneka's modules by path, so there is one of it."""
    if not os.path.exists(path):
        tool.log("boneka's %s is not where it should be (%s)" % (name, path))
        return None
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as err:
        tool.log("could not load %s: %s" % (name, err))
        return None


PBR = borrow("boneka_pbr", os.path.join(BONEKA, "tools", "pbr.py"))

# Where the photographs are. boneka has already downloaded a set and derived
# maps from them; anything pasar brings home lands beside them.
SOURCES = [
    os.path.join(BONEKA, "textures", "source"),
    os.path.join(HOME, "Documents", "bengkel", "pasar", "out", "texturelabs"),
]

# What a surface is called in the world, rather than in a file name.
SURFACE_NAMES = {
    "metal": "Metal", "wood": "Wood", "fabric": "Fabric", "leather": "Leather",
    "stone": "Stone", "concrete": "Concrete", "brick": "Brick", "soil": "Soil",
    "detail": "Plain",
}
SURFACE_ABOUT = {
    "metal": "Hard, shiny, picks up the light in streaks.",
    "wood": "Grain, mid roughness, never quite flat.",
    "fabric": "Soft and matte. Cloth, canvas, a robe.",
    "leather": "Creased, slightly glossy where it is worn.",
    "stone": "Rough and pitted. Rock, slab, statue.",
    "concrete": "Flat grey with a fine tooth to it.",
    "brick": "Deep relief. The strongest of them.",
    "soil": "Very rough, no shine at all. Earth, sand.",
    "detail": "No material, just a faint grain so it is not a plastic slab.",
}


def photographs():
    """Every Texturelabs photograph on the machine, by surface."""
    found = {}
    for folder in SOURCES:
        for dirpath, _dirs, names in os.walk(folder) if os.path.isdir(folder) else []:
            for name in names:
                if not name.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                # Texturelabs names them Texturelabs_Metal_126S.jpg, or just
                # Metal_126S.jpg once boneka has taken them in.
                bare = name.replace("Texturelabs_", "")
                kind = bare.split("_")[0].lower()
                if kind in SURFACE_NAMES:
                    found.setdefault(kind, []).append(os.path.join(dirpath, name))
    return {k: sorted(v) for k, v in found.items()}


@tool.get("/api/surfaces")
def surfaces(query):
    """What a part can be made of, and whether there is a photograph for it."""
    have = photographs()
    order = ["metal", "wood", "fabric", "leather", "stone", "concrete",
             "brick", "soil", "detail"]
    return {
        "surfaces": [{
            "id": key,
            "name": SURFACE_NAMES[key],
            "about": SURFACE_ABOUT[key],
            "photographs": len(have.get(key, [])),
            "ready": bool(have.get(key)),
        } for key in order],
        # No photographs at all means boneka's texture folder is missing and
        # everything here would silently come out plain, which is worth saying
        # rather than leaving him to wonder.
        "any": sum(len(v) for v in have.values()),
    }


@tool.get("/api/palettes")
def palettes(query):
    """The colour sets boneka already has, so the two tools agree on colour."""
    out = []
    folder = os.path.join(BONEKA, "palettes")
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name)) as f:
                doc = json.load(f)
            out.append({"slug": doc.get("slug") or name[:-5],
                        "name": doc.get("name") or name[:-5],
                        "colors": doc.get("colors") or []})
        except Exception:
            continue
    return {"palettes": out}


_derived = {}


def derive(photograph, surface, folder, problems):
    """The three maps for one photograph, worked out once and kept.

    Deriving them is a second or two of image work and the same surface is
    usually asked for by several parts of the same model, so the answer is
    remembered for as long as kulit is running.
    """
    key = (photograph, surface)
    if key in _derived:
        return _derived[key]
    if not PBR:
        problems.append("boneka's map generator could not be loaded, so "
                        "everything came out as flat colour.")
        _derived[key] = {}
        return {}
    try:
        _derived[key] = PBR.build(photograph, surface, folder)
        tool.log("derived %s maps from %s" % (surface, os.path.basename(photograph)))
    except Exception as err:
        problems.append("could not derive %s maps (%s)" % (surface, err))
        _derived[key] = {}
    return _derived[key]


@tool.post("/api/dress")
def dress(body):
    """Give every part a colour and a material, and export it."""
    source = os.path.expanduser(body.get("path") or "")
    if not source or not os.path.exists(source):
        return {"ok": False, "problems": ["that file is not there any more"]}
    if not tool.allowed(source):
        return {"ok": False, "problems": ["that file is somewhere kulit is not "
                                          "allowed to read"]}

    parts = body.get("parts") or []
    if not parts:
        return {"ok": False, "problems": ["nothing to dress"]}

    have = photographs()
    maps_folder = os.path.join(tool.data, "maps")
    os.makedirs(maps_folder, exist_ok=True)
    problems = []

    for part in parts:
        kind = part.get("surface") or "detail"
        part["surface"] = kind
        pick = have.get(kind) or []
        if not pick:
            part["maps"] = {}
            continue
        # One photograph per surface, chosen by a stable rule rather than at
        # random, so the same part dressed twice comes out the same both times.
        photograph = pick[sum(map(ord, kind)) % len(pick)]
        part["photograph"] = photograph
        part["maps"] = derive(photograph, kind, maps_folder, problems)

    # The maps are worked out here, in system Python, and not inside Blender.
    # Blender ships its own Python without Pillow or numpy, which is what
    # boneka's generator is written in - and installing them into a Blender
    # nobody controls is not a thing to do on somebody's machine. So the maps
    # are made first and Blender is handed three file paths.

    stem = SAFE_NAME.sub("-", os.path.splitext(os.path.basename(source))[0]
                         .lower()).strip("-") or "model"
    out = os.path.join(tool.out, stem)

    answer = tool.blender("dress.py", {
        "job": "dress",
        "source": source,
        "out": out,
        "name": stem,
        "parts": parts,
    }, timeout=900)

    if problems:
        answer.setdefault("notes", []).extend(problems)

    if answer.get("ok"):
        tool.permit(answer["glb"])
        answer["shown"] = answer["glb"].replace(HOME, "~")
        answer["folder"] = out
        note(out, source, answer, parts)
        tool.log("dressed %s: %d parts" % (stem, len(parts)))
    return answer


def note(folder, source, answer, parts):
    """Write down what is inside it, and what may be done with it.

    Texturelabs allows a texture inside a finished game and forbids handing
    somebody a model they can pull it back out of. That obligation has to
    travel with the file rather than rely on anyone remembering it, so it is
    written every single time.
    """
    used = sorted({p.get("surface") or "detail" for p in parts})
    with open(os.path.join(folder, "WHAT-IS-IN-IT.md"), "w") as f:
        f.write("# %s\n\n" % os.path.basename(answer["glb"]))
        f.write("- **From:** %s\n" % source.replace(HOME, "~"))
        f.write("- **Parts dressed:** %d\n" % len(parts))
        f.write("- **Surfaces used:** %s\n" % ", ".join(used))
        f.write("\n## The textures inside this file\n\n")
        f.write("The maps in this model are derived from **Texturelabs** "
                "photographs — a detail map, a normal map and a roughness map "
                "worked out from each photograph's greyscale.\n\n")
        f.write("> Texturelabs resources cannot be distributed or sold as part "
                "of a 3D model in a way that allows a third party to use, "
                "download, extract or access the Texturelabs asset.\n\n")
        f.write("**Using this model inside a finished game is fine.** Handing "
                "someone the `.glb` is not. Do not commit this file to a "
                "public repository.\n")


@tool.get("/api/mine")
def mine(query):
    out = []
    if os.path.isdir(tool.out):
        for name in sorted(os.listdir(tool.out)):
            glb = os.path.join(tool.out, name, "%s.glb" % name)
            if not os.path.exists(glb):
                continue
            tool.permit(glb)
            out.append({"id": name, "title": name, "path": glb,
                        "shown": glb.replace(HOME, "~"),
                        "bytes": os.path.getsize(glb), "model": True})
    out.sort(key=lambda i: -os.path.getmtime(i["path"]))
    return {"items": out}


if __name__ == "__main__":
    sys.exit(tool.run())
