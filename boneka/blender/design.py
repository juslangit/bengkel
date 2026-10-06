"""
Recipes Claude designs, for what boneka has no recipe of its own.

recipes.py knows people, four-legged animals, birds, dragons and a shelf of
props. Ask it for a snail and it used to make a person, because a bare prompt
makes a character. Now a prompt that names nothing boneka knows is handed to
Claude, which designs a recipe for it - the same list of parts and bones the
built-in recipes are made of - and boneka builds that.

Claude designs data, never code. It is not asked for a Blender script,
because a script from a model run by pressing a button is a program nobody
read running with the run of the machine. A recipe is numbers, colours and
names, every one of them checked here before Blender sees it, and it is built
by the same code as every built-in model - so it is sculpted, rigged exactly
and animated like one, which a one-off script would not be.

The server asks (server.py, design_job); this module says what to ask, and
checks and turns the answer into a plan.
"""

import json
import math
import re

import palette as palettes
import recipes

SHAPES = ("loft", "limb", "sphere", "box", "capsule", "cylinder", "cone",
          "torus", "membrane")
PROFILES = ("humanoid", "quadruped", "bird", "dragon", "prop")
MAX_PARTS = 160
SKIN = "@skin"          # rig.SKIN: a plate that takes the body's own weights
REACH = 30.0            # metres. Nothing designed may reach further than this.

# the templates whose bone names each skeleton's moves are written for
PROFILE_EXAMPLES = {"humanoid": "a knight", "quadruped": "a dog",
                    "bird": "a chicken", "dragon": "a dragon"}

# words that describe a thing without naming it
MODIFIERS = {"happy", "sad", "angry", "old", "young", "new", "evil", "friendly",
             "scary", "funny", "fancy", "simple", "detailed", "realistic",
             "stylised", "stylized", "magic", "magical", "wooden", "metal",
             "stone", "glass", "golden", "dark", "light", "bright", "shiny",
             "fluffy", "furry", "spiky", "one", "two", "three", "four", "pair"}


# --------------------------------------------------------------------------
# when to ask
# --------------------------------------------------------------------------

def _known(words):
    names = {w for group in recipes.ARCHETYPES.values() for w in group}
    names |= {w for group in recipes.PROP_WORDS.values() for w in group}
    return names


def subject_words(prompt):
    """The words in a prompt that name something, rather than describe it."""
    describing = (set(recipes.STOPWORDS) | set(recipes.COLORS)
                  | set(recipes.SIZE_WORDS) | set(recipes.BULK_WORDS)
                  | set(recipes.STYLE_WORDS) | set(palettes.MOODS) | MODIFIERS
                  | {w for group in recipes.EXTRAS.values() for w in group})
    return [w for w in recipes._words(prompt)
            if w not in describing and not w.isdigit() and not w.startswith("#")]


def needs_design(prompt):
    """True when boneka has no recipe for what the prompt names."""
    names = _known(recipes._words(prompt))
    found = subject_words(prompt)
    for w in recipes._words(prompt):
        if w in names or (w.endswith("s") and w[:-1] in names):
            return False
    return bool(found)


# --------------------------------------------------------------------------
# what Claude is asked for
# --------------------------------------------------------------------------

_V3 = {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3}

SCHEMA = {
    "type": "object",
    "required": ["name", "rig_profile", "organic", "parts"],
    "properties": {
        "name": {"type": "string"},
        "rig_profile": {"type": "string", "enum": list(PROFILES)},
        "organic": {"type": "boolean"},
        "notes": {"type": "string"},
        "parts": {
            "type": "array", "minItems": 1, "maxItems": MAX_PARTS,
            "items": {
                "type": "object",
                "required": ["part", "shape", "color"],
                "properties": {
                    "part": {"type": "string"},
                    "shape": {"type": "string", "enum": list(SHAPES)},
                    "color": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"},
                    "rings": {"type": "array", "items": {
                        "type": "array", "items": {"type": "number"},
                        "minItems": 5, "maxItems": 5}},
                    "from": _V3, "to": _V3,
                    "r0": {"type": "number"}, "r1": {"type": "number"},
                    "at": _V3, "size": _V3, "rot": _V3,
                    "points": {"type": "array", "items": _V3},
                    "thickness": {"type": "number"},
                    "bone": {"type": "object", "required": ["name", "head", "tail"],
                             "properties": {"name": {"type": "string"},
                                            "head": _V3, "tail": _V3,
                                            "parent": {"type": "string"}}},
                    "attach": {"type": "string"},
                    "stage": {"type": "string"},
                    "hard": {"type": "boolean"},
                },
            },
        },
    },
}


def to_design(plan):
    """A built-in plan written the way Claude is asked to write one."""
    parts = []
    for st in plan["steps"]:
        d = st.get("detail") or {}
        p = {"part": st["part"], "shape": st["shape"], "color": st["color"]}
        if st["shape"] == "loft":
            p["rings"] = [[round(v, 3) for v in r["c"]] + [round(r["rx"], 3), round(r["ry"], 3)]
                          for r in d["rings"]]
        elif st["shape"] == "limb":
            p.update({"from": [round(v, 3) for v in d["head"]],
                      "to": [round(v, 3) for v in d["tail"]],
                      "r0": round(d["r0"], 3), "r1": round(d["r1"], 3)})
        elif st["shape"] == "membrane":
            p.update({"points": [[round(v, 3) for v in q] for q in d["points"]],
                      "thickness": round(d["thickness"], 4)})
        else:
            p.update({"at": [round(v, 3) for v in st["loc"]],
                      "size": [round(v, 3) for v in st["size"]]})
            if any(st.get("rot") or []):
                p["rot"] = [round(v, 3) for v in st["rot"]]
        if st.get("bone"):
            b = st["bone"]
            p["bone"] = {"name": b["name"], "head": [round(v, 3) for v in b["head"]],
                         "tail": [round(v, 3) for v in b["tail"]]}
            if b.get("parent"):
                p["bone"]["parent"] = b["parent"]
        if st.get("attach"):
            p["attach"] = st["attach"]
        if st.get("stage", "body") != "body":
            p["stage"] = st["stage"]
        parts.append(p)
    return {"name": plan["name"], "rig_profile": plan["rig_profile"],
            "organic": plan["organic"], "parts": parts}


def _bone_names(profile):
    plan = recipes.plan_from_prompt(PROFILE_EXAMPLES[profile])
    return [st["bone"]["name"] for st in plan["steps"] if st.get("bone")]


def brief(prompt, references):
    """What Claude is told. `references` are image files in its folder."""
    example = json.dumps(to_design(recipes.plan_from_prompt("a dragon")),
                         separators=(",", ":"))
    skeletons = "\n".join("  %s: %s" % (p, ", ".join(_bone_names(p)))
                          for p in PROFILE_EXAMPLES)
    looking = (("Reference photographs of the real thing are in your folder: %s. "
                "Read every one of them before you design anything, and take the "
                "proportions from them, not from memory.\n\n")
               % ", ".join(references)) if references else ""
    return f"""You are designing a 3D model for boneka, a tool that builds models in Blender
from a recipe: a list of simple parts, each with a colour, and the bones that
move them. You write the recipe; boneka builds it, fuses the soft parts into
one smooth skin, rigs it from your bones and animates it.

What to make: "{prompt}"

{looking}HOW TO DESIGN IT
First decide what makes this thing read as itself at a glance - the handful
of features a person would draw first - and make sure every one of them is
there and exaggerated a little, the way a good stylised game model is. A
recognisable silhouette matters more than detail. Then build it as a sculptor
blocks one out: big forms first (body, head), then the forms on them, then
the small parts that carry the character (eyes, horns, claws, spikes).

COORDINATES
Metres. Z is up, the model faces -Y (its front is towards -Y, its back
towards +Y), X is its left (+X) and right (-X). It stands on the floor, z = 0,
centred on x = 0. Make it the size of the real thing, or about 1-2 m tall if
it has no real size. Mirror left and right exactly; name left parts ".L" and
right parts ".R".

SHAPES
- loft: the main tool. A form built from cross-sections, like a drawn figure:
  "rings": [[x, y, z, rx, ry], ...] run along the form; each ring is an
  ellipse laid across the path through its neighbours, rx its half-width and
  ry its half-height (or half-depth, for a vertical form). Use 3-8 rings to
  make a torso swell and narrow, a neck, a head with a snout, a tail.
- limb: a tapered tube with round ends: "from", "to", "r0", "r1".
- sphere, box, capsule, cylinder, cone, torus: "at" (centre), "size" (half
  sizes x, y, z; a torus uses size[0] as its ring radius and size[1] as its
  tube radius), optional "rot" (radians about X, Y, Z). A cone points up +Z
  before rotation.
- membrane: a thin flat skin through "points" (3-24 corners in order, may be
  concave) with "thickness" - wing skin, fins, leaves, sails.

HOW PARTS JOIN
Soft parts of the same colour are fused into one smooth skin by a voxel
remesh, so overlap them generously - a leg should start well inside the
body, a head well inside the neck. Nothing thinner than about 1 cm survives
that, so thin parts (claws, spikes, eyes, horns, membranes) are kept as they
are: mark them "hard": true. Parts of different colours stay separate, so a
belly plate or a shell sits proud of the body it lies on.

COLOURS
"#rrggbb" per part. Use a small, deliberate palette of 3-5 colours that suits
the subject, with one strong accent. Eyes are what make a creature alive: give
it eyes with a white and a dark pupil unless the real thing has none.

BONES AND MOVEMENT
Give each moving part a "bone": {{"name", "head", "tail", "parent"}} - the
bone runs from head to tail through that part. The first bone has no parent;
every other bone's parent must be a bone you defined. A part that rides a
bone without making one uses "attach": "<bone name>"; a plate lying over the
body across several bones uses "attach": "@skin".
Pick "rig_profile" by how it should move, and when you do, use exactly these
bone names, because the moves are written for them:
{skeletons}
  prop: anything that does not walk; give it a root bone and only what moves.
Extra bones beyond these are fine (a tail, wings, antennae): wings named
wing.L / wing_outer.L flap, and tail_00 to tail_03 sway.

AMOUNT
Aim for 40 to 120 parts. Fewer reads as a toy made of blocks; the dragon
below has 76.

"organic": true for anything alive or soft (it is sculpted into one skin),
false for machines and hard objects (every part keeps its edges).

EXAMPLE
The dragon boneka already knows, as a recipe:
{example}

Answer with the recipe only."""


# --------------------------------------------------------------------------
# checking what came back, and turning it into a plan
# --------------------------------------------------------------------------

class DesignError(ValueError):
    pass


def _num(v, what, positive=False):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise DesignError("%s is not a number" % what)
    if not math.isfinite(f) or abs(f) > REACH:
        raise DesignError("%s is out of range (%r)" % (what, v))
    if positive and f <= 0:
        raise DesignError("%s must be more than zero" % what)
    return f


def _vec(v, what):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise DesignError("%s must be three numbers" % what)
    return [_num(x, what) for x in v]


def _name(v, fallback):
    n = re.sub(r"[^a-z0-9_.]", "_", str(v or fallback).lower())[:48].strip("_")
    return n or fallback


def _colour(v, what):
    if not isinstance(v, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", v):
        raise DesignError("%s is not a #rrggbb colour" % what)
    return v.lower()


def _lowest(p):
    """The lowest a raw part reaches, near enough to stand the model on the floor."""
    shape = p.get("shape")
    if shape == "loft":
        return min(r[2] - max(abs(r[3]), abs(r[4])) for r in p["rings"])
    if shape == "limb":
        return min(p["from"][2] - abs(p["r0"]), p["to"][2] - abs(p["r1"]))
    if shape == "membrane":
        return min(q[2] for q in p["points"])
    return p["at"][2] - max(abs(s) for s in p["size"])


def check(design):
    """Every problem with a design, as sentences Claude can act on; [] if none."""
    problems = []
    try:
        steps_from(design)
    except DesignError as exc:
        problems.append(str(exc))
    return problems


def steps_from(design):
    """Validate a design and build its steps. Raises DesignError."""
    if not isinstance(design, dict):
        raise DesignError("the design is not an object")
    raw = design.get("parts")
    if not isinstance(raw, list) or not raw:
        raise DesignError("the design has no parts")
    if len(raw) > MAX_PARTS:
        raise DesignError("too many parts (%d, at most %d)" % (len(raw), MAX_PARTS))

    # read every number first, so a bad one is reported before anything is built
    parts, bone_names, used = [], set(), set()
    for i, p in enumerate(raw):
        if not isinstance(p, dict):
            raise DesignError("part %d is not an object" % (i + 1))
        name = _name(p.get("part"), "part_%d" % (i + 1))
        base, n = name, 2
        while name in used:
            name, n = "%s_%d" % (base, n), n + 1
        used.add(name)
        where = "part %d (%s)" % (i + 1, name)
        shape = p.get("shape")
        if shape not in SHAPES:
            raise DesignError("%s has an unknown shape %r" % (where, shape))
        q = {"part": name, "shape": shape, "color": _colour(p.get("color"), where + " colour"),
             "stage": _name(p.get("stage"), "body"), "hard": p.get("hard")}
        if q["hard"] is not None and not isinstance(q["hard"], bool):
            q["hard"] = None
        if shape == "loft":
            rings = p.get("rings")
            if not isinstance(rings, list) or not 2 <= len(rings) <= 32:
                raise DesignError("%s needs 2 to 32 rings" % where)
            q["rings"] = []
            for r in rings:
                if not isinstance(r, (list, tuple)) or len(r) != 5:
                    raise DesignError("%s has a ring that is not [x, y, z, rx, ry]" % where)
                q["rings"].append([_num(r[0], where), _num(r[1], where), _num(r[2], where),
                                   _num(r[3], where, True), _num(r[4], where, True)])
        elif shape == "limb":
            q["from"], q["to"] = _vec(p.get("from"), where + " from"), _vec(p.get("to"), where + " to")
            q["r0"], q["r1"] = _num(p.get("r0"), where + " r0", True), _num(p.get("r1"), where + " r1", True)
        elif shape == "membrane":
            pts = p.get("points")
            if not isinstance(pts, list) or not 3 <= len(pts) <= 24:
                raise DesignError("%s needs 3 to 24 points" % where)
            q["points"] = [_vec(v, where + " point") for v in pts]
            q["thickness"] = _num(p.get("thickness", 0.01), where + " thickness", True)
        else:
            q["at"] = _vec(p.get("at"), where + " at")
            q["size"] = [abs(v) for v in _vec(p.get("size"), where + " size")]
            if min(q["size"]) <= 0:
                raise DesignError("%s has a size of zero" % where)
            q["rot"] = _vec(p.get("rot") or [0, 0, 0], where + " rot")
        b = p.get("bone")
        if b:
            if not isinstance(b, dict):
                raise DesignError("%s has a bone that is not an object" % where)
            bn = _name(b.get("name"), name)
            if bn in bone_names:
                raise DesignError("two bones are both called %r" % bn)
            bone_names.add(bn)
            q["bone"] = {"name": bn, "head": _vec(b.get("head"), where + " bone head"),
                         "tail": _vec(b.get("tail"), where + " bone tail"),
                         "parent": _name(b.get("parent"), "") or None}
        q["attach"] = p.get("attach")
        parts.append(q)

    for q in parts:
        b = q.get("bone")
        if b and b["parent"] and b["parent"] not in bone_names:
            raise DesignError("bone %r has a parent %r that is not a bone in the design"
                              % (b["name"], b["parent"]))
        if q["attach"] == SKIN:
            continue
        att = _name(q["attach"], "") if q["attach"] else None
        # an attachment to a bone that does not exist is left for the rig to
        # place by distance, rather than failing the whole design over it
        q["attach"] = att if att in bone_names else None

    # stand it on the floor, whatever height Claude put it at
    drop = min(_lowest(q) for q in parts)
    for q in parts:
        for key in ("from", "to", "at"):
            if key in q:
                q[key][2] -= drop
        for r in q.get("rings", []):
            r[2] -= drop
        for v in q.get("points", []):
            v[2] -= drop
        if q.get("bone"):
            q["bone"]["head"][2] -= drop
            q["bone"]["tail"][2] -= drop

    steps = []
    for q in parts:
        bone_def = recipes.bone(q["bone"]["name"], q["bone"]["head"], q["bone"]["tail"],
                                q["bone"]["parent"]) if q.get("bone") else None
        kw = dict(attach=q["attach"], stage=q["stage"], hard=q["hard"])
        if q["shape"] == "loft":
            st = recipes.loft(q["part"], [recipes.ring(*r) for r in q["rings"]],
                              q["color"], bone_def, **kw)
        elif q["shape"] == "limb":
            st = recipes.limb(q["part"], q["from"], q["to"], q["r0"], q["r1"],
                              q["color"], bone_def, **kw)
        elif q["shape"] == "membrane":
            st = recipes.membrane(q["part"], q["points"], q["color"], q["thickness"],
                                  attach=q["attach"] or (bone_def or {}).get("name"))
            st["bone"] = bone_def
        else:
            st = recipes.step(q["part"], q["shape"], q["size"], q["at"], q["color"],
                              rot=tuple(q["rot"]), bone=bone_def, **kw)
        steps.append(st)
    return steps


def plan_from_design(design, prompt, palette=None):
    """A checked design as a plan boneka builds like any other."""
    steps = steps_from(design)
    profile = design.get("rig_profile")
    if profile not in PROFILES:
        profile = "prop"
    height = max(_top(st) for st in steps)
    if height < 0.02:
        raise DesignError("the model is flat (%.3f m tall)" % height)
    if not any(st.get("bone") for st in steps):
        # the rig needs one bone at least; a thing with none moves as one piece
        steps.insert(0, recipes.step("root", "sphere", [0.001] * 3, [0, 0, 0.001],
                                     steps[0]["color"], label="root", hard=True,
                                     bone=recipes.bone("root", [0, 0, 0],
                                                       [0, 0, max(height * 0.3, 0.05)])))
        profile = "prop"
    words = recipes._words(prompt)
    meta = {"rig_profile": profile, "height": height, "style": "round",
            "organic": bool(design.get("organic", True)),
            "subject": " ".join(subject_words(prompt)[:3]) or "model"}
    plan = recipes._assemble(prompt, words, steps, meta, "designed", None, None,
                             1.0, 1.0, [], palette)
    plan["name"] = _name(design.get("name"), plan["name"]).replace("_", " ")
    plan["designed"] = True
    return plan


def _top(st):
    return st["loc"][2] + abs(st["size"][2])
