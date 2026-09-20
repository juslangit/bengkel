"""
Turn a plain-English prompt into a build plan.

A build plan is a list of steps. Each step makes exactly one part of the model,
and the app draws the model again after every step - that is what you see when
you watch it being built.

This file never imports bpy, so it can be read and tested with normal Python.

Coordinates are Blender's: X is right, Y is depth, Z is up, and the model faces -Y.
Everything is measured in real metres, because a model at the wrong scale is the
single most common thing wrong with a downloaded asset.
"""

import re

import palette as palettes

# --------------------------------------------------------------------------
# words the parser understands
# --------------------------------------------------------------------------

COLORS = {
    "red": "#c0392b", "crimson": "#a01f2e", "scarlet": "#d62828",
    "orange": "#e67e22", "amber": "#f0a500",
    "yellow": "#f1c40f", "gold": "#d4a017", "golden": "#d4a017",
    "green": "#27ae60", "lime": "#7ed321", "olive": "#6b7a2f",
    "teal": "#16a085", "cyan": "#1abc9c", "turquoise": "#1abc9c",
    "blue": "#2e6fdb", "navy": "#1b3a6b", "sky": "#6fb1e8",
    "purple": "#8e44ad", "violet": "#7d3c98", "magenta": "#c2398b",
    "pink": "#e88fb0", "rose": "#e0607e",
    "brown": "#7a5230", "tan": "#b08968", "beige": "#d8c3a5",
    "black": "#1d1f21", "grey": "#808a8f", "gray": "#808a8f",
    "silver": "#b6bfc5", "white": "#ecf0f1", "ivory": "#e8e2d0",
    "steel": "#7f8c9b", "bronze": "#9c6b3f", "copper": "#b06a3b",
    "skin": "#d9a07a",
}

# archetype -> the words that pick it
ARCHETYPES = {
    "humanoid": [
        "human", "person", "people", "man", "woman", "boy", "girl", "guy",
        "character", "figure", "hero", "villain", "knight", "warrior", "soldier",
        "wizard", "mage", "witch", "ninja", "pirate", "viking", "king", "queen",
        "robot", "android", "mech", "golem", "zombie", "skeleton", "orc", "goblin",
        "elf", "dwarf", "alien", "astronaut", "farmer", "chef", "doctor", "guard",
        "player", "referee", "footballer", "mascot", "doll", "puppet", "avatar",
    ],
    "quadruped": [
        "dog", "cat", "wolf", "fox", "horse", "cow", "bull", "goat", "sheep",
        "pig", "deer", "lion", "tiger", "bear", "rat", "mouse", "elephant",
        "dinosaur", "dragon", "lizard", "creature", "beast", "animal", "quadruped",
        "puppy", "kitten", "pony", "donkey", "camel",
    ],
    "bird": [
        "bird", "chicken", "duck", "eagle", "owl", "penguin", "parrot", "crow",
        "hen", "rooster", "seagull", "dove", "pigeon", "flamingo",
    ],
}

# every prop the library can build, and the words that reach it
PROP_WORDS = {
    "tree": ["tree", "oak", "pine", "palm"],
    "bush": ["bush", "shrub", "hedge"],
    "mushroom": ["mushroom", "toadstool", "fungus"],
    "rock": ["rock", "stone", "boulder"],
    "crystal": ["crystal", "gem", "gemstone", "diamond", "shard"],
    "chair": ["chair", "stool", "seat"],
    "table": ["table", "desk", "bench"],
    "barrel": ["barrel", "keg", "cask"],
    "crate": ["crate", "box", "cube", "block"],
    "chest": ["chest", "treasure", "coffer"],
    "sword": ["sword", "blade", "katana", "sabre", "saber"],
    "axe": ["axe", "hatchet"],
    "hammer": ["hammer", "mallet"],
    "staff": ["staff", "wand", "sceptre", "scepter", "stick"],
    "shield": ["shield", "buckler"],
    "house": ["house", "hut", "cottage", "cabin", "building", "shack"],
    "tower": ["tower", "turret", "lighthouse"],
    "rocket": ["rocket", "missile", "spaceship", "spacecraft"],
    "car": ["car", "truck", "van", "vehicle", "lorry"],
    "lamp": ["lamp", "lantern", "streetlight"],
    "torch": ["torch", "flame"],
    "potion": ["potion", "bottle", "flask", "vial"],
    "key": ["key"],
    "coin": ["coin", "money", "medal"],
    "book": ["book", "tome", "grimoire"],
    "barrier": ["fence", "barrier", "railing"],
    "ball": ["ball", "sphere", "orb", "football", "planet", "moon"],
    "cone": ["cone", "traffic cone"],
    "signpost": ["sign", "signpost", "post"],
    "flag": ["flag", "banner"],
    "well": ["well"],
    "cactus": ["cactus"],
    "snowman": ["snowman"],
    "campfire": ["campfire", "fire", "bonfire"],
}

# add-ons that hang off a humanoid or animal
EXTRAS = {
    "hat": ["hat", "cap", "helmet", "crown", "tophat"],
    "horns": ["horn", "horns", "antlers"],
    "wings": ["wing", "wings"],
    "tail": ["tail"],
    "cape": ["cape", "cloak", "robe"],
    "backpack": ["backpack", "bag", "rucksack"],
    "eyes": ["eye", "eyes", "face"],
    "ears": ["ear", "ears"],
    "beard": ["beard", "moustache"],
    "shield": ["shield"],
    "sword": ["sword", "blade", "katana"],
    "staff": ["staff", "wand"],
    "antenna": ["antenna", "aerial"],
}

SIZE_WORDS = {
    "tiny": 0.35, "miniature": 0.4, "small": 0.6, "little": 0.65, "short": 0.75,
    "normal": 1.0, "medium": 1.0,
    "big": 1.35, "large": 1.35, "tall": 1.25, "huge": 1.8, "giant": 2.2,
    "massive": 2.4, "enormous": 2.4, "colossal": 3.0, "baby": 0.45,
}

BULK_WORDS = {
    "thin": 0.7, "skinny": 0.62, "slim": 0.78, "slender": 0.75, "lanky": 0.7,
    "normal": 1.0,
    "chunky": 1.3, "fat": 1.45, "chubby": 1.35, "buff": 1.25, "muscular": 1.28,
    "stocky": 1.3, "heavy": 1.35, "round": 1.25, "bulky": 1.4,
}

STYLE_WORDS = {
    "blocky": "blocky", "boxy": "blocky", "minecraft": "blocky", "voxel": "blocky",
    "cube": "blocky", "pixel": "blocky", "lego": "blocky", "robot": "blocky",
    "round": "round", "rounded": "round", "soft": "round", "cute": "round",
    "chibi": "round", "cartoon": "round", "toy": "round", "smooth": "round",
}

STOPWORDS = {
    "a", "an", "the", "of", "with", "and", "make", "create", "build", "generate",
    "me", "please", "some", "it", "that", "has", "have", "wearing", "holding",
    "is", "very", "really", "kind", "sort", "like", "in", "on", "for", "model",
    "asset", "3d", "low", "poly", "lowpoly", "style", "styled",
}


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _words(prompt):
    return re.findall(r"[a-z0-9#]+", prompt.lower())


def _find(words, table):
    """First table key whose word list contains one of the prompt words."""
    for key, synonyms in table.items():
        for w in words:
            if w in synonyms:
                return key
    return None


def _find_all(words, table):
    hits = []
    for key, synonyms in table.items():
        for w in words:
            if w in synonyms and key not in hits:
                hits.append(key)
    return hits


def pick_colors(words, default_body, default_accent, default_skin=None):
    """
    Colour words in a prompt are taken in the order they appear:
    the first paints the body, the second the accent.
    """
    found = [COLORS[w] for w in words if w in COLORS]
    found += [w for w in words if re.fullmatch(r"#[0-9a-f]{6}", w)]
    body = found[0] if len(found) > 0 else default_body
    accent = found[1] if len(found) > 1 else (found[0] if found else default_accent)
    if accent == body and len(found) < 2:
        accent = default_accent
    skin = default_skin or body
    if found and default_skin:
        skin = found[0]
    return {"body": body, "accent": accent, "skin": skin,
            "dark": _shade(body, 0.6), "light": _shade(body, 1.3)}


def _shade(hex_color, factor):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    f = lambda v: max(0, min(255, int(v * factor)))
    return "#%02x%02x%02x" % (f(r), f(g), f(b))


def _title(words, fallback):
    kept = [w for w in words if w not in STOPWORDS]
    return " ".join(kept[:4]) if kept else fallback


# Sculpting is for organic forms. A crate that has been voxel-remeshed and
# smoothed is a crate with soft corners, which is worse than a crate.
ORGANIC_PROPS = {"tree", "bush", "mushroom", "rock", "cactus", "snowman", "ball"}

# Things worn, held or stuck on. They are not part of the body's form, so they
# keep their own shape however organic the creature is. Anything else that is
# simply too thin to survive a voxel grid is caught later, by measurement,
# rather than by being listed here.
ACCESSORIES = (
    "eye", "nose", "beak", "comb", "wattle", "horn", "antenna", "antenna_tip",
    "hat", "hat_brim", "crown", "helmet", "beard", "sword", "staff", "shield",
    "cape", "backpack", "spot", "band", "rail", "window", "door", "lock",
    "gem", "frond", "stripe", "boss", "rim", "tooth",
)


def _is_accessory(part):
    stem = part.split(".")[0].rstrip("_0123456789")
    return stem in ACCESSORIES or any(part.startswith(a + "_") for a in ACCESSORIES)


# --------------------------------------------------------------------------
# what each part is made of
#
# Surfaces are textured by what they are, not by being asked. The mapping is
# done here by part name rather than by tagging a hundred call sites, so a new
# recipe gets sensible material for free as long as it names its parts the way
# everything else does.
#
# Anything not listed gets "detail": a faint grunge, multiplied over whatever
# colour the part already has, so no surface is perfectly flat.
# --------------------------------------------------------------------------

MATERIALS = {
    "metal": ("helmet", "visor", "nose_guard", "breastplate", "pauldron",
              "gauntlet", "greave", "tassets", "crown", "crest", "sword",
              "axe", "hammer", "shield", "dome", "buckle", "collar_ring",
              "blade", "guard", "tip", "key", "coin", "rim", "band", "lock",
              "engine", "antenna", "nail", "housing", "chassis", "cabin",
              "wheel", "fin", "hull", "turret"),
    "wood": ("staff", "trunk", "handle", "shaft", "log", "post", "pole",
             "plank", "rail", "board", "table", "top", "seat", "backrest",
             "crate", "barrel", "lid", "signpost", "cover", "upright",
             "stalk", "oar"),
    "fabric": ("tunic", "robe", "sleeve", "cape", "hood", "cowl", "mask",
               "mantle", "apron", "loincloth", "flag", "cloth", "pages",
               "wrap", "trouser", "plume", "cushion"),
    "leather": ("belt", "boot", "boot_shaft", "backpack", "strap", "eyepatch",
                "grip", "saddle"),
    "stone": ("rock", "shard", "crystal", "gem", "stone", "boulder", "well",
              "roof", "headstone"),
    "concrete": ("wall", "walls", "tower", "chimney", "cone", "door",
                 "window", "pavement"),
    "soil": ("ground", "mound", "dirt", "sand"),
    # leaves are not made of anything on the site, and must be named here so
    # a tree's "mostly wood" default does not put plank grain on its canopy
    "detail": ("canopy", "leaves", "frond", "bush", "flame", "water", "eye",
               "skin", "cloud", "smoke", "spot"),
}

DEFAULT_MATERIAL = "detail"

_MATERIAL_BY_WORD = {}
for _surface, _parts in MATERIALS.items():
    for _p in _parts:
        _MATERIAL_BY_WORD.setdefault(_p, _surface)


# A prop's own parts are often named too generically to read - a barrel's
# "body", a crate's "box" - so each prop says what it is mostly made of, and
# that is used wherever the part name itself gives nothing away.
PROP_MATERIAL = {
    "barrel": "wood", "crate": "wood", "chest": "wood", "chair": "wood",
    "table": "wood", "book": "wood", "signpost": "wood", "barrier": "wood",
    "torch": "wood", "campfire": "wood", "tree": "wood", "cactus": "wood",
    "house": "concrete", "tower": "concrete", "lamp": "metal",
    "well": "stone", "rock": "stone", "crystal": "stone",
    "sword": "metal", "axe": "metal", "hammer": "metal", "shield": "metal",
    "staff": "wood", "key": "metal", "coin": "metal", "car": "metal",
    "rocket": "metal", "flag": "fabric", "ball": "leather",
}


def material_for(part, prop=None):
    """
    The surface a part should be textured with: what the part is called, and
    failing that what the whole object is mostly made of.
    """
    stem = part.split(".")[0].rstrip("_0123456789")
    if stem in _MATERIAL_BY_WORD:
        return _MATERIAL_BY_WORD[stem]
    for word, surface in _MATERIAL_BY_WORD.items():
        if stem.startswith(word) or stem.endswith("_" + word):
            return surface
    if prop and prop in PROP_MATERIAL:
        return PROP_MATERIAL[prop]
    return DEFAULT_MATERIAL


def _subject(words, synonyms, fallback):
    """
    The noun the prompt is really about, so the app can go and find a photo of
    it. "a tall blue knight with a sword" is about a knight, not a sword.
    """
    for w in words:
        if w in synonyms:
            return w
    return fallback


def step(part, shape, size, loc, color, rot=(0, 0, 0), bone=None, label=None,
         detail=None, attach=None, stage="body", hard=None):
    """
    One part of the model.

    `bone` makes a new bone and is what makes the auto-rig button exact.
    `attach` names a bone made by some other part, for things that ride along
    rather than bend - an eye, a hat, a sword in a hand, a pauldron.
    `stage` says which pass of the build this part belongs to, so a model is
    assembled the way a modeller would assemble it: the body first, then the
    face, then what it is wearing, then what it is carrying.
    `hard` overrides the sculpt pass's own judgement - armour keeps its edges.
    """
    return {
        "part": part,
        "shape": shape,
        "size": [round(v, 4) for v in size],
        "loc": [round(v, 4) for v in loc],
        "rot": list(rot),
        "color": color,
        "bone": bone,
        "attach": attach,
        "stage": stage,
        "hard": hard,
        "label": label or part.replace("_", " ").replace(".", " "),
        "detail": detail or {},
    }


def bone(name, head, tail, parent=None):
    return {"name": name, "head": [round(v, 4) for v in head],
            "tail": [round(v, 4) for v in tail], "parent": parent}


# --------------------------------------------------------------------------
# the main entry point
# --------------------------------------------------------------------------

def plan_from_prompt(prompt, palette=None):
    """
    `palette` is a list of hex colours to build the whole model from. The
    prompt can also name one of the built-in moods, which needs no network.
    """
    words = _words(prompt)

    style = _find(words, {k: [k] for k in STYLE_WORDS}) or None
    if style:
        style = STYLE_WORDS[style]

    scale = 1.0
    for w in words:
        if w in SIZE_WORDS:
            scale = SIZE_WORDS[w]
            break
    bulk = 1.0
    for w in words:
        if w in BULK_WORDS:
            bulk = BULK_WORDS[w]
            break

    archetype = None
    for kind, synonyms in ARCHETYPES.items():
        if any(w in synonyms for w in words):
            archetype = kind
            break

    prop = _find(words, PROP_WORDS)

    # a named creature always wins over a prop word that also appears
    if archetype is None and prop is None:
        archetype = "humanoid"           # a bare prompt makes a character
    if archetype is None:
        archetype = "prop"

    extras = _find_all(words, EXTRAS)

    if archetype == "humanoid":
        planner = build_humanoid
    elif archetype == "quadruped":
        planner = build_quadruped
    elif archetype == "bird":
        planner = build_bird
    else:
        planner = lambda **kw: build_prop(prop, **kw)

    steps, meta = planner(words=words, scale=scale, bulk=bulk, style=style,
                          extras=extras)

    final_style = style or meta.get("style", "round")
    # a blocky model is blocky on purpose, so it is never sculpted
    organic = bool(meta.get("organic")) and final_style != "blocky"
    for st in steps:
        # only an actual prop lends its material: "a knight with a sword"
        # sets prop to "sword", and a knight is not made of sword
        st["material"] = material_for(
            st["part"], prop if archetype == "prop" else None)
        if st.get("hard") is None:
            st["hard"] = (not organic) or _is_accessory(st["part"])
        elif organic is False:
            st["hard"] = True

    if archetype == "prop":
        for st in steps:
            if st["stage"] == "body":
                st["stage"] = "structure"

    # everything on the model goes onto one palette, including the shades,
    # so it hangs together instead of being a body colour plus two guesses
    mood = palettes.mood_in(words)
    chosen = palettes.normalise(palette) or (palettes.MOODS[mood] if mood else [])
    palette_map = palettes.snap_plan(steps, chosen) if chosen else {}

    stages = []
    for st in steps:
        if st["stage"] not in stages:
            stages.append(st["stage"])
    surfaces = sorted({st["material"] for st in steps})

    return {
        "prompt": prompt,
        "archetype": archetype,
        "stages": stages,
        "palette": palettes.normalise(chosen),
        "surfaces": surfaces,
        "palette_name": mood or "",
        "prop": prop,
        "subject": meta.get("subject", archetype),
        "name": _title(words, archetype),
        "style": final_style,
        "organic": organic,
        "scale": scale,
        "bulk": bulk,
        "extras": extras,
        "rig_profile": meta.get("rig_profile", "generic"),
        "height": round(meta.get("height", 1.0), 3),
        "steps": steps,
    }


# --------------------------------------------------------------------------
# a limb is a tapered tube from one joint to the next
# --------------------------------------------------------------------------

def limb(part, head, tail, r0, r1, color, bone_def=None, label=None,
         stage="body", attach=None, hard=None):
    """
    A part that runs between two points. The mesh builder works out the
    direction itself, so nothing here has to do trigonometry.
    """
    mid = [(head[i] + tail[i]) / 2.0 for i in range(3)]
    return step(part, "limb", [r0, r1, 0], mid, color, bone=bone_def,
                label=label, stage=stage, attach=attach, hard=hard,
                detail={"head": list(head), "tail": list(tail),
                        "r0": r0, "r1": r1})


def loft(part, rings, color, bone_def=None, label=None, segments=None,
         attach=None, stage="body", hard=None):
    """
    A part described by its cross-sections rather than by a primitive.

    `rings` runs along the form: [{"c": [x, y, z], "rx": .., "ry": ..}, ...].
    The bounding box is worked out with the same frame maths the builder uses,
    so the floor checks and the sculpt pass can measure a loft exactly the way
    they measure a box.
    """
    lo = [1e18, 1e18, 1e18]
    hi = [-1e18, -1e18, -1e18]
    centres = [r["c"] for r in rings]
    for i, r in enumerate(rings):
        c = centres[i]
        if i == 0:
            t = _sub(centres[1], c)
        elif i == len(rings) - 1:
            t = _sub(c, centres[-2])
        else:
            t = _sub(centres[i + 1], centres[i - 1])
        t = _unit(t) or [0.0, 0.0, 1.0]
        reference = [0.0, 0.0, 1.0]
        if abs(_dot(t, reference)) > 0.985:
            reference = [0.0, 1.0, 0.0]
        ax = _unit(_cross(t, reference)) or [1.0, 0.0, 0.0]
        ay = _unit(_cross(t, ax)) or [0.0, 1.0, 0.0]
        rx, ry = r["rx"], r.get("ry", r["rx"])
        for axis in range(3):
            # the widest this ring reaches along one world axis
            reach = (rx * ax[axis] ** 2 + ry * ay[axis] ** 2) ** 0.5 if False else \
                ((rx * ax[axis]) ** 2 + (ry * ay[axis]) ** 2) ** 0.5
            lo[axis] = min(lo[axis], c[axis] - reach)
            hi[axis] = max(hi[axis], c[axis] + reach)
    size = [(hi[i] - lo[i]) / 2.0 for i in range(3)]
    centre = [(hi[i] + lo[i]) / 2.0 for i in range(3)]
    detail = {"rings": rings}
    if segments:
        detail["segments"] = segments
    return step(part, "loft", size, centre, color, bone=bone_def, label=label,
                detail=detail, attach=attach, stage=stage, hard=hard)


def _sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0]]


def _unit(v):
    length = _dot(v, v) ** 0.5
    return [v[0] / length, v[1] / length, v[2] / length] if length > 1e-12 else None


def ring(x, y, z, rx, ry=None):
    return {"c": [round(x, 5), round(y, 5), round(z, 5)],
            "rx": round(rx, 5), "ry": round(ry if ry is not None else rx, 5)}



def mirrored(part, head, tail, r0, r1, color, parent_bone, label):
    """Build the same limb on both sides. Returns two steps."""
    out = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        h = [head[0] * sx, head[1], head[2]]
        t = [tail[0] * sx, tail[1], tail[2]]
        pb = parent_bone
        if pb and pb.endswith(".X"):
            pb = pb[:-2] + "." + side
        out.append(limb("%s.%s" % (part, side), h, t, r0, r1, color,
                        bone(("%s.%s" % (part, side)), h, t, pb),
                        "%s %s" % (label, "left" if side == "L" else "right")))
    return out


# --------------------------------------------------------------------------
# humanoid
# --------------------------------------------------------------------------

def build_humanoid(words, scale, bulk, style, extras):
    """
    Built from cross-sections, the way a figure is constructed on paper: the
    ribcage as an oval, the waist narrowing between ribcage and pelvis, the
    deltoid capping the shoulder, a swell for the bicep and one for the calf.

    Vertical landmarks follow the eight-head canon (head = H/8; crotch at 4
    heads; chin at 7; shoulders a third of a head below the chin; elbow at the
    navel, wrist at the crotch). Widths follow anthropometry rather than the
    drawing canon, because the canon measures the fleshed silhouette and this
    has to build the flesh: biacromial breadth is about 0.234 H and the
    shoulder-to-hip ratio about 1.4 for a man, so the skeletal shoulder ring is
    narrower than the finished figure and the deltoids make up the difference.

    Sources: thedrawingsource.com figure-drawing proportions; CDC/NHANES
    biacromial and bi-iliac breadth; howtodrawcomicsacademy.com on the torso
    front view (ribcage oval, waist narrowing, deltoid caps).
    """
    H = 1.8 * scale
    style = style or ("blocky" if any(w in words for w in
                      ("robot", "android", "mech", "golem")) else "round")
    chibi = any(w in words for w in ("chibi", "cute", "toy", "baby", "doll"))

    kit, kit_name = kit_for(words)
    fallback = KIT_COLOURS.get(kit_name, ("#4a7ab8", "#d4a017"))
    pal = pick_colors(words, fallback[0], fallback[1], default_skin="#d9a07a")
    body, accent, skin = pal["body"], pal["accent"], pal["skin"]
    is_machine = any(w in words for w in ("robot", "android", "mech", "golem",
                                          "skeleton"))
    if is_machine:
        skin = pal["light"]

    # what this character is assembled from. Whatever the clothes cover
    # becomes an under-layer, so the garment reads as a garment on top of a
    # body rather than as a differently shaped body.
    dressed_torso = any(m in TORSO_MODULES for m in kit)
    dressed_legs = any(m in LEG_MODULES for m in kit)
    under = pal["dark"] if dressed_torso else body
    leg_col = pal["dark"] if (is_machine or dressed_legs) else body

    B = bulk                                   # every girth scales with build
    R = lambda x, y, z, rx, ry=None: ring(x * H, y * H, z * H, rx * H * B,
                                          (ry if ry is not None else rx) * H * B)

    # ---- torso: one stack of sections, split at the waist so the pelvis and
    # the ribcage can each carry their own bone. The two share their middle
    # rings, so the overlap has no step in it for the sculpt pass to find.
    torso = [
        R(0, +0.002, 0.478, 0.056, 0.046),     # underside of the pelvis
        R(0, +0.004, 0.512, 0.077, 0.056),     # crotch
        R(0, +0.002, 0.565, 0.088, 0.060),     # hip crest
        R(0, -0.006, 0.625, 0.071, 0.050),     # waist, the narrowest point
        R(0,  0.000, 0.695, 0.085, 0.061),     # lower ribs
        R(0, +0.006, 0.762, 0.096, 0.066),     # chest
        R(0, +0.004, 0.820, 0.098, 0.060),     # shoulder line (skeletal)
        R(0, +0.002, 0.852, 0.060, 0.051),     # trapezius, sloping in
        R(0, -0.002, 0.872, 0.041, 0.041),     # neck base
    ]

    S = []
    S.append(loft("hips", torso[0:5], under,
                  bone("hips", [0, 0, 0.500 * H], [0, 0, 0.625 * H]),
                  "pelvis"))
    S.append(loft("chest", torso[3:9], under,
                  bone("spine", [0, 0, 0.625 * H], [0, 0, 0.833 * H], "hips"),
                  "ribcage"))
    S.append(loft("neck", [R(0, +0.002, 0.828, 0.038),
                           R(0, -0.001, 0.858, 0.034),
                           R(0, -0.004, 0.884, 0.032)], skin,
                  bone("neck", [0, 0, 0.833 * H], [0, 0, 0.875 * H], "spine"),
                  "neck"))

    # ---- head: chin, jaw, cheek, cranium, crown - not an egg
    head_scale = 1.55 if chibi else 1.0
    z_chin, z_top = 0.873, 0.873 + 0.125 * head_scale   # exactly one head
    def HR(t, rx, ry, y=0.0):
        return ring(0, y * H, (z_chin + (z_top - z_chin) * t) * H,
                    rx * H * head_scale, ry * H * head_scale)
    S.append(loft("head", [
        HR(0.00, 0.028, 0.033, -0.010),
        HR(0.17, 0.042, 0.050, -0.006),
        HR(0.36, 0.048, 0.056, -0.004),
        HR(0.58, 0.049, 0.058, -0.002),
        HR(0.81, 0.042, 0.048, +0.000),
        HR(1.00, 0.020, 0.024, +0.002),
    ], skin, bone("head", [0, 0, 0.875 * H], [0, 0, z_top * H], "neck"), "head"))

    # ---- arms, held a little away from the body. The gap between arm and
    # torso is most of what makes a standing figure read as a person.
    for side, sx in (("L", 1.0), ("R", -1.0)):
        tag = lambda n: "%s.%s" % (n, side)
        S.append(step(tag("deltoid"), "sphere",
                      [0.042 * H * B, 0.044 * H * B, 0.045 * H * B],
                      [0.101 * H * sx, 0.002 * H, 0.816 * H], under,
                      bone=bone(tag("shoulder"), [0.032 * H * sx, 0, 0.834 * H],
                                [0.100 * H * sx, 0, 0.810 * H], "spine"),
                      label="deltoid"))
        S.append(loft(tag("upperarm"), [
            R(0.100 * sx, 0.002, 0.810, 0.033),
            R(0.111 * sx, 0.002, 0.755, 0.036),      # bicep
            R(0.123 * sx, 0.001, 0.688, 0.030),
            R(0.131 * sx, 0.000, 0.632, 0.025),      # elbow
        ], under, bone(tag("upperarm"), [0.100 * H * sx, 0, 0.810 * H],
                      [0.132 * H * sx, 0, 0.625 * H], tag("shoulder")),
            "upper arm"))
        S.append(loft(tag("forearm"), [
            R(0.132 * sx, 0.000, 0.628, 0.026),
            R(0.139 * sx, 0.000, 0.588, 0.029),      # flexor swell
            R(0.146 * sx, 0.000, 0.540, 0.022),
            R(0.150 * sx, 0.000, 0.503, 0.018),      # wrist
        ], skin, bone(tag("forearm"), [0.132 * H * sx, 0, 0.625 * H],
                      [0.150 * H * sx, 0, 0.500 * H], tag("upperarm")),
            "forearm"))
        S.append(loft(tag("hand"), [
            R(0.150 * sx, 0.000, 0.500, 0.013, 0.022),
            R(0.153 * sx, -0.002, 0.466, 0.017, 0.029),   # knuckles
            R(0.155 * sx, -0.002, 0.424, 0.014, 0.025),
            R(0.156 * sx, -0.002, 0.406, 0.008, 0.013),
        ], skin, bone(tag("hand"), [0.150 * H * sx, 0, 0.500 * H],
                      [0.156 * H * sx, 0, 0.405 * H], tag("forearm")),
            "hand"))

    # ---- legs, with the mass on the thigh and a calf that tapers to the ankle
    for side, sx in (("L", 1.0), ("R", -1.0)):
        tag = lambda n: "%s.%s" % (n, side)
        S.append(loft(tag("thigh"), [
            R(0.052 * sx, 0.000, 0.505, 0.060),
            R(0.053 * sx, 0.000, 0.430, 0.058),
            R(0.054 * sx, 0.000, 0.330, 0.046),
            R(0.055 * sx, 0.000, 0.272, 0.038),      # knee
        ], leg_col, bone(tag("thigh"), [0.052 * H * sx, 0, 0.500 * H],
                         [0.055 * H * sx, 0, 0.260 * H], "hips"), "thigh"))
        S.append(loft(tag("shin"), [
            R(0.055 * sx, 0.000, 0.266, 0.037),
            R(0.056 * sx, 0.004, 0.205, 0.040),      # calf
            R(0.057 * sx, 0.002, 0.120, 0.027),
            R(0.058 * sx, 0.000, 0.048, 0.021),      # ankle
        ], leg_col, bone(tag("shin"), [0.055 * H * sx, 0, 0.260 * H],
                         [0.058 * H * sx, 0, 0.045 * H], tag("thigh")), "shin"))
        # the foot runs forward, so its rings stack along Y rather than Z
        S.append(loft(tag("foot"), [
            ring(0.058 * H * sx, +0.030 * H, 0.032 * H, 0.021 * H, 0.026 * H),
            ring(0.058 * H * sx, -0.005 * H, 0.026 * H, 0.026 * H, 0.024 * H),
            ring(0.066 * H * sx, -0.048 * H, 0.020 * H, 0.028 * H, 0.019 * H),
            ring(0.076 * H * sx, -0.080 * H, 0.013 * H, 0.023 * H, 0.012 * H),
        ], pal["dark"], bone(tag("foot"), [0.058 * H * sx, 0, 0.045 * H],
                             [0.060 * H * sx, -0.070 * H, 0.020 * H],
                             tag("shin")),
            "foot %s" % ("left" if side == "L" else "right")))

    head_r = 0.066 * H * head_scale
    z_head = (z_chin + (z_top - z_chin) * 0.45) * H
    head_taken = any(m in HEAD_MODULES for m in kit)

    # the face goes on before the clothes, the clothes before what it carries
    S += humanoid_extras(extras, words, H, head_r, z_head, 0.150 * H, pal,
                         style, is_machine, head_taken=head_taken)
    S += dress(Fit(H, B, pal, skin, style, head_scale), kit)
    S += humanoid_hands(extras, H, pal)

    return S, {"rig_profile": "humanoid", "height": H, "style": style,
               "subject": _subject(words, ARCHETYPES["humanoid"], "person"),
               "organic": not is_machine or style != "blocky"}


def humanoid_extras(extras, words, H, head_r, z_head, x_arm, pal, style,
                    is_machine, head_taken=False):
    """Eyes, ears, beard and anything the prompt asked to stick on."""
    S = []
    body, accent, dark = pal["body"], pal["accent"], pal["dark"]
    face_y = -head_r * 0.85

    if "eyes" in extras or not is_machine:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("eye.%s" % side, "sphere",
                          [head_r * 0.17] * 3,
                          [head_r * 0.36 * sx, face_y, z_head + head_r * 0.12],
                          "#17202a", attach="head", stage="face",
                          label="eye %s" % ("left" if side == "L" else "right")))
    if "ears" in extras:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("ear.%s" % side, "sphere",
                          [head_r * 0.16, head_r * 0.3, head_r * 0.32],
                          [head_r * 0.98 * sx, 0, z_head + head_r * 0.05],
                          pal["skin"], attach="head", stage="face", label="ear"))
    if "beard" in extras:
        S.append(step("beard", "box",
                      [head_r * 0.7, head_r * 0.5, head_r * 0.7],
                      [0, face_y * 0.7, z_head - head_r * 0.75], "#e8e2d0",
                      attach="head", stage="face", label="beard"))
    if "hat" in extras and not head_taken:
        crown = any(w in words for w in ("crown",))
        helmet = any(w in words for w in ("helmet",))
        if crown:
            S.append(step("hat", "cylinder",
                          [head_r * 0.95, head_r * 0.95, head_r * 0.5],
                          [0, 0, z_head + head_r * 1.15], "#d4a017",
                          attach="head", label="crown"))
        elif helmet:
            S.append(step("hat", "sphere",
                          [head_r * 1.12, head_r * 1.12, head_r * 1.1],
                          [0, 0, z_head + head_r * 0.15], pal["light"],
                          attach="head", label="helmet"))
        else:
            S.append(step("hat_brim", "cylinder",
                          [head_r * 1.7, head_r * 1.7, head_r * 0.1],
                          [0, 0, z_head + head_r * 0.85], accent, attach="head",
                          label="hat brim"))
            S.append(step("hat", "cone",
                          [head_r * 1.0, head_r * 1.0, head_r * 1.6],
                          [0, 0, z_head + head_r * 1.7], accent, attach="head",
                          label="hat"))
    if "horns" in extras and not head_taken:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("horn.%s" % side, "cone",
                          [head_r * 0.22, head_r * 0.22, head_r * 0.8],
                          [head_r * 0.6 * sx, 0, z_head + head_r * 1.1],
                          "#e8e2d0", rot=(0, 0.35 * (1 if sx > 0 else -1), 0),
                          attach="head", label="horn"))
    if "antenna" in extras:
        S.append(step("antenna", "cylinder",
                      [head_r * 0.06, head_r * 0.06, head_r * 1.2],
                      [0, 0, z_head + head_r * 1.5], dark, attach="head",
                      label="antenna"))
        S.append(step("antenna_tip", "sphere", [head_r * 0.18] * 3,
                      [0, 0, z_head + head_r * 2.15], "#e74c3c", attach="head",
                      label="antenna tip"))
    if "cape" in extras:
        S.append(step("cape", "sphere",
                      [0.125 * H, 0.030 * H, 0.215 * H],
                      [0, 0.095 * H, 0.615 * H], accent, attach="spine", stage="clothing",
                      label="cape"))
    if "backpack" in extras:
        S.append(step("backpack", "box",
                      [0.085 * H, 0.05 * H, 0.10 * H],
                      [0, 0.14 * H, 0.70 * H], dark, attach="spine", stage="gear",
                      label="backpack"))
    if "wings" in extras:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("wing.%s" % side, "box",
                          [0.15 * H, 0.008 * H, 0.11 * H],
                          [0.30 * H * sx, 0.09 * H, 0.74 * H], pal["light"],
                          rot=(0, 0, 0.25 * (1 if sx > 0 else -1)),
                          attach="spine", stage="detail", label="wing"))
    if "tail" in extras:
        for i in range(4):
            t = i / 3.0
            S.append(step("tail_%02d" % i, "sphere",
                          [0.035 * H * (1 - 0.45 * t)] * 3,
                          [0, 0.11 * H + 0.09 * H * i, 0.55 * H - 0.05 * H * i],
                          body, label="tail"))
    return S


def humanoid_hands(extras, H, pal):
    """What the character is carrying. It goes on last, as it would."""
    S = []
    accent, x_arm = pal["accent"], 0.150 * H
    grip_x = -(x_arm + 0.035 * H)          # just outside the right hand
    grip_y = -0.045 * H                    # and a little in front of it
    if "sword" in extras:
        S.append(step("sword_grip", "cylinder",
                      [0.016 * H, 0.016 * H, 0.055 * H],
                      [grip_x, grip_y, 0.435 * H], "#5a3a22", attach="hand.R", stage="gear",
                      label="sword grip"))
        S.append(step("sword_guard", "box",
                      [0.048 * H, 0.012 * H, 0.010 * H],
                      [grip_x, grip_y, 0.495 * H], accent, attach="hand.R", stage="gear",
                      label="cross guard"))
        S.append(step("sword_blade", "box",
                      [0.016 * H, 0.005 * H, 0.185 * H],
                      [grip_x, grip_y, 0.690 * H], "#c7cdd2", attach="hand.R", stage="gear",
                      label="sword blade"))
        S.append(step("sword_tip", "cone",
                      [0.016 * H, 0.005 * H, 0.030 * H],
                      [grip_x, grip_y, 0.905 * H], "#c7cdd2", attach="hand.R", stage="gear",
                      label="sword tip"))
    if "staff" in extras:
        S.append(step("staff_shaft", "cylinder",
                      [0.013 * H, 0.013 * H, 0.40 * H],
                      [grip_x, grip_y, 0.40 * H], "#7a5230", attach="hand.R", stage="gear",
                      label="staff"))
        S.append(step("staff_gem", "sphere", [0.042 * H] * 3,
                      [grip_x, grip_y, 0.825 * H], "#1abc9c", attach="hand.R", stage="gear",
                      detail={"emissive": 1.6}, label="staff gem"))
    if "shield" in extras:
        S.append(step("shield", "cylinder",
                      [0.15 * H, 0.15 * H, 0.018 * H],
                      [(x_arm + 0.045 * H), -0.055 * H, 0.60 * H], accent,
                      rot=(1.5708, 0, 0), attach="forearm.L", stage="gear",
                      label="shield"))
    return S




# --------------------------------------------------------------------------
# quadruped
# --------------------------------------------------------------------------

def build_quadruped(words, scale, bulk, style, extras):
    """
    A dog is longer than it is tall - breed standards put body length against
    shoulder height at about 10 to 8.5 for a German Shepherd and 10 to 9 for a
    Vizsla - it is deepest at the chest, tucked at the waist and wide again
    over the hindquarters, and a standard's rule of thumb is that the chest
    reaches halfway down the leg. So the body is a run of cross-sections along
    the spine rather than two capsules, and the hind leg is angulated, stifle
    forward and hock back, which is most of what tells a dog from a table.

    Sources: breedingbetterdogs.com and siriusdog.com breed-standard ratios;
    Taiwan Dog standard for muzzle 4.5 to skull 5.5.
    """
    Hs = 0.62 * scale                      # height at the shoulder
    L = 1.17 * Hs                          # chest to rump
    style = style or "round"
    pal = pick_colors(words, "#8c6239", "#4a3524")
    body, accent, dark = pal["body"], pal["accent"], pal["dark"]
    B = bulk

    y_front, y_rear = -0.46 * L, 0.46 * L
    x_leg = 0.092 * L * (0.62 + 0.38 * B)   # under the body, not outboard

    def R(y, z, rx, rz):
        return ring(0, y * L, z * Hs, rx * L * B, rz * Hs * B)

    spine = [
        R(-0.50, 0.760, 0.085, 0.200),     # front of the chest
        R(-0.34, 0.740, 0.135, 0.245),     # chest, the deepest point
        R(-0.12, 0.750, 0.128, 0.225),
        R(+0.10, 0.775, 0.112, 0.190),     # waist, tucked up
        R(+0.32, 0.765, 0.140, 0.215),     # hindquarters
        R(+0.50, 0.745, 0.095, 0.160),     # rump
    ]
    S = []
    S.append(loft("chest", spine[0:4], body,
                  bone("spine", [0, 0, 0.76 * Hs], [0, y_front, 0.77 * Hs],
                       "hips"), "chest"))
    S.append(loft("hips", spine[2:6], body,
                  bone("hips", [0, y_rear, 0.76 * Hs], [0, 0, 0.76 * Hs]),
                  "hindquarters"))

    # ---- neck and head: short and thick, head about a third of the body
    head_l = 0.32 * L
    y_head = y_front - 0.22 * L
    z_head = 0.95 * Hs
    S.append(loft("neck", [
        ring(0, y_front * 0.90, 0.80 * Hs, 0.105 * L * B, 0.115 * L * B),
        ring(0, y_front - 0.10 * L, 0.88 * Hs, 0.092 * L * B, 0.098 * L * B),
        ring(0, y_head + 0.07 * L, z_head - 0.03 * Hs, 0.082 * L * B, 0.086 * L * B),
    ], body, bone("neck", [0, y_front, 0.78 * Hs],
                  [0, y_head + 0.07 * L, z_head], "spine"), "neck"))

    muzzle_l = 0.45 * head_l               # muzzle 4.5 to the skull's 5.5
    S.append(loft("head", [
        ring(0, y_head + 0.10 * L, z_head - 0.01 * Hs, 0.088 * L, 0.090 * L),
        ring(0, y_head + 0.02 * L, z_head + 0.01 * Hs, 0.098 * L, 0.100 * L),
        ring(0, y_head - 0.06 * L, z_head - 0.02 * Hs, 0.078 * L, 0.078 * L),
        ring(0, y_head - 0.06 * L - muzzle_l * 0.40, z_head - 0.055 * Hs,
             0.048 * L, 0.046 * L),
        ring(0, y_head - 0.06 * L - muzzle_l * 0.98, z_head - 0.070 * Hs,
             0.041 * L, 0.039 * L),
    ], body, bone("head", [0, y_head + 0.07 * L, z_head],
                  [0, y_head - 0.16 * L, z_head - 0.05 * Hs], "neck"), "head"))

    nose_y = y_head - 0.06 * L - muzzle_l * 1.05
    S.append(step("nose", "sphere", [0.021 * L, 0.019 * L, 0.019 * L],
                  [0, nose_y, z_head - 0.072 * Hs], "#2b2b2b", attach="head",
                  label="nose"))
    for side, sx in (("L", 1.0), ("R", -1.0)):
        S.append(step("eye.%s" % side, "sphere", [0.017 * L] * 3,
                      [0.058 * L * sx, y_head - 0.040 * L, z_head + 0.015 * Hs],
                      "#17202a", attach="head", label="eye"))
        S.append(loft("ear.%s" % side, [
            ring(0.062 * L * sx, y_head + 0.055 * L, z_head + 0.055 * Hs,
                 0.032 * L, 0.019 * L),
            ring(0.070 * L * sx, y_head + 0.060 * L, z_head + 0.135 * Hs,
                 0.023 * L, 0.014 * L),
            ring(0.076 * L * sx, y_head + 0.062 * L, z_head + 0.195 * Hs,
                 0.006 * L, 0.005 * L),
        ], accent, attach="head", label="ear"))

    # ---- legs
    for tag in ("front", "back"):
        front = tag == "front"
        y_top = (y_front + 0.10 * L) if front else (y_rear - 0.10 * L)
        y_mid = y_top + (0.01 * L if front else -0.075 * L)
        y_low = y_top + (0.00 * L if front else 0.055 * L)
        parent = "spine" if front else "hips"
        z_top = 0.80 * Hs
        z_mid = (0.47 if front else 0.45) * Hs     # elbow / stifle
        z_low = 0.055 * Hs                          # pastern, just off the floor
        for side, sx in (("L", 1.0), ("R", -1.0)):
            b1, b2 = "thigh_%s.%s" % (tag, side), "shin_%s.%s" % (tag, side)
            x = x_leg * sx
            # shoulder blade at the front, haunch at the back: the mass that
            # carries the leg into the body. Without it the leg pops out of
            # the flank as a tube with a crease round it.
            S.append(step("%s_mass.%s" % (tag, side), "sphere",
                          [(0.052 if front else 0.066) * L * B,
                           (0.115 if front else 0.140) * L,
                           (0.165 if front else 0.195) * Hs],
                          [x * 0.72, y_top + (0.01 if front else -0.02) * L,
                           (0.70 if front else 0.68) * Hs], body,
                          attach=b1,
                          label="%s %s" % (tag,
                                           "shoulder" if front else "haunch")))
            # the top ring is deliberately narrower than the ribcage: the
            # shoulder or haunch mass is what shows there, and a wide ring
            # here punches a plate out through the flank
            S.append(loft("%sleg_upper.%s" % (tag, side), [
                ring(x, y_top, z_top + 0.04 * Hs, 0.046 * L * B, 0.054 * L * B),
                ring(x, (y_top + y_mid) / 2, (z_top + z_mid) / 2,
                     0.050 * L * B, 0.057 * L * B),
                ring(x, y_mid, z_mid, 0.036 * L * B, 0.040 * L * B),
            ], body, bone(b1, [x, y_top, z_top], [x, y_mid, z_mid], parent),
                "%s leg upper" % tag))
            S.append(loft("%sleg_lower.%s" % (tag, side), [
                ring(x, y_mid, z_mid + 0.03 * Hs, 0.038 * L * B, 0.044 * L * B),
                ring(x, (y_mid + y_low) / 2, (z_mid + z_low) / 2 + 0.04 * Hs,
                     0.033 * L * B, 0.040 * L * B),   # the calf, carried high
                ring(x, y_low + 0.01 * L, 0.20 * Hs, 0.023 * L, 0.025 * L),
                ring(x, y_low, z_low, 0.021 * L, 0.023 * L),
            ], body, bone(b2, [x, y_mid, z_mid], [x, y_low, z_low], b1),
                "%s leg lower" % tag))
            S.append(loft("paw_%s.%s" % (tag, side), [
                ring(x, y_low + 0.024 * L, 0.052 * Hs, 0.023 * L, 0.040 * Hs),
                ring(x, y_low - 0.022 * L, 0.034 * Hs, 0.030 * L, 0.030 * Hs),
                ring(x, y_low - 0.052 * L, 0.016 * Hs, 0.024 * L, 0.015 * Hs),
            ], dark, bone("paw_%s.%s" % (tag, side), [x, y_low, z_low],
                          [x, y_low - 0.055 * L, 0.02 * Hs], b2),
                "%s paw" % tag))

    # ---- tail, carried back and a little down, tapering to a point
    prev = "hips"
    for i in range(4):
        t = i / 3.0
        h = [0, y_rear + 0.085 * L * i, (0.82 - 0.085 * i) * Hs]
        tl = [0, y_rear + 0.085 * L * (i + 1), (0.82 - 0.085 * (i + 1)) * Hs]
        nm = "tail_%02d" % i
        S.append(limb(nm, h, tl, 0.040 * L * (1 - 0.62 * t),
                      0.040 * L * (1 - 0.62 * (t + 0.33)), body,
                      bone(nm, h, tl, prev), "tail %d" % (i + 1)))
        prev = nm

    if "horns" in extras:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("horn.%s" % side, "cone",
                          [0.018 * L, 0.018 * L, 0.070 * L],
                          [0.048 * L * sx, y_head, z_head + 0.13 * Hs],
                          "#e8e2d0", attach="head", label="horn"))
    if "wings" in extras:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("wing.%s" % side, "box",
                          [0.21 * L, 0.17 * L, 0.01 * L],
                          [0.30 * L * sx, 0, 1.02 * Hs], accent,
                          rot=(0.3 * (1 if sx > 0 else -1), 0, 0),
                          attach="spine", label="wing"))

    return S, {"rig_profile": "quadruped", "height": z_head + 0.20 * Hs,
               "style": style, "organic": True,
               "subject": _subject(words, ARCHETYPES["quadruped"], "dog")}


# --------------------------------------------------------------------------
# bird
# --------------------------------------------------------------------------

def build_bird(words, scale, bulk, style, extras):
    """
    A chicken measures 40-60 cm nose to tail while standing 25-37 cm tall and
    only 11.5-18 cm across: a long narrow thing, not a ball. The body is built
    as a run of sections from breast to tail so it can be full at the breast
    and taper away behind, with the thigh buried in the feathers and only the
    shank showing - which is how a chicken's leg actually reads.

    Source: dimensions.com, Domestic Chicken (Gallus gallus domesticus).
    """
    H = 0.34 * scale                       # standing height
    style = style or "round"
    pal = pick_colors(words, "#ecf0f1", "#e67e22")
    body, accent = pal["body"], pal["accent"]
    B = bulk

    z_body = 0.53 * H
    head_r = 0.105 * H
    y_head = -0.36 * H
    z_head = 0.86 * H

    def R(y, z, rx, rz):
        return ring(0, y * H, z * H, rx * H * B, rz * H * B)

    # breast at the front, tapering back and up into the tail
    S = [loft("body", [
        R(-0.30, 0.500, 0.120, 0.150),     # breast
        R(-0.14, 0.530, 0.170, 0.215),     # the deepest, fullest point
        R(+0.06, 0.540, 0.165, 0.205),
        R(+0.26, 0.565, 0.125, 0.150),
        R(+0.40, 0.600, 0.070, 0.085),     # where the tail leaves
    ], body, bone("hips", [0, 0.16 * H, z_body], [0, -0.14 * H, z_body]),
        "body")]

    S.append(loft("neck", [
        ring(0, -0.26 * H, 0.620 * H, 0.072 * H * B, 0.080 * H * B),
        ring(0, -0.32 * H, 0.740 * H, 0.054 * H * B, 0.058 * H * B),
        ring(0, y_head + 0.02 * H, z_head - head_r * 0.7, 0.050 * H, 0.052 * H),
    ], body, bone("neck", [0, -0.26 * H, 0.62 * H],
                  [0, y_head, z_head - head_r * 0.7], "hips"), "neck"))

    S.append(loft("head", [
        ring(0, y_head + 0.055 * H, z_head - head_r * 0.5, 0.062 * H, 0.066 * H),
        ring(0, y_head + 0.010 * H, z_head + head_r * 0.15, 0.078 * H, 0.084 * H),
        ring(0, y_head - 0.040 * H, z_head - head_r * 0.10, 0.058 * H, 0.060 * H),
    ], body, bone("head", [0, y_head, z_head - head_r * 0.7],
                  [0, y_head - 0.06 * H, z_head + head_r * 0.4], "neck"), "head"))

    S.append(step("comb", "box",
                  [head_r * 0.10, head_r * 0.60, head_r * 0.45],
                  [0, y_head + 0.012 * H, z_head + head_r * 0.95], "#c0392b",
                  attach="head", label="comb"))
    S.append(step("beak", "cone", [head_r * 0.30, head_r * 0.30, head_r * 0.58],
                  [0, y_head - 0.075 * H, z_head - head_r * 0.15], accent,
                  rot=(1.5708, 0, 0), attach="head", label="beak"))
    S.append(step("wattle", "sphere",
                  [head_r * 0.15, head_r * 0.18, head_r * 0.30],
                  [0, y_head - 0.045 * H, z_head - head_r * 0.95], "#c0392b",
                  attach="head", label="wattle"))

    for side, sx in (("L", 1.0), ("R", -1.0)):
        S.append(step("eye.%s" % side, "sphere", [head_r * 0.15] * 3,
                      [head_r * 0.52 * sx, y_head - 0.030 * H,
                       z_head + head_r * 0.10], "#17202a", attach="head",
                      label="eye"))
        # the wing lies along the flank as a lens, not a plate on a curve
        S.append(loft("wing.%s" % side, [
            ring(0.150 * H * B * sx, -0.130 * H, 0.575 * H, 0.030 * H, 0.055 * H),
            ring(0.168 * H * B * sx, -0.020 * H, 0.560 * H, 0.038 * H, 0.080 * H),
            ring(0.150 * H * B * sx, +0.130 * H, 0.556 * H, 0.026 * H, 0.055 * H),
            ring(0.120 * H * B * sx, +0.230 * H, 0.562 * H, 0.012 * H, 0.026 * H),
        ], pal["light"], bone("wing.%s" % side,
                              [0.14 * H * sx, -0.05 * H, 0.58 * H],
                              [0.34 * H * sx, 0.02 * H, 0.55 * H], "hips"),
            "wing"))
        # only the shank shows; the thigh is inside the feathers
        S.append(loft("leg.%s" % side, [
            ring(0.075 * H * sx, -0.030 * H, 0.420 * H, 0.030 * H, 0.034 * H),
            ring(0.078 * H * sx, -0.040 * H, 0.300 * H, 0.019 * H, 0.020 * H),
            ring(0.080 * H * sx, -0.045 * H, 0.055 * H, 0.016 * H, 0.017 * H),
        ], accent, bone("leg.%s" % side,
                        [0.075 * H * sx, -0.03 * H, 0.42 * H],
                        [0.080 * H * sx, -0.045 * H, 0.05 * H], "hips"), "leg"))
        S.append(loft("foot.%s" % side, [
            ring(0.080 * H * sx, +0.010 * H, 0.028 * H, 0.020 * H, 0.020 * H),
            ring(0.080 * H * sx, -0.045 * H, 0.016 * H, 0.030 * H, 0.013 * H),
            ring(0.080 * H * sx, -0.100 * H, 0.010 * H, 0.022 * H, 0.008 * H),
        ], accent, attach="leg.%s" % side, label="foot"))

    # tail feathers, swept up and back - a third of the whole length
    S.append(loft("tail", [
        ring(0, 0.360 * H, 0.605 * H, 0.060 * H, 0.055 * H),
        ring(0, 0.480 * H, 0.710 * H, 0.072 * H, 0.038 * H),
        ring(0, 0.560 * H, 0.810 * H, 0.050 * H, 0.020 * H),
    ], body, bone("tail", [0, 0.34 * H, 0.60 * H], [0, 0.56 * H, 0.81 * H],
                  "hips"), "tail feathers"))

    return S, {"rig_profile": "bird", "height": z_head + head_r * 1.6,
               "style": style, "organic": True,
               "subject": _subject(words, ARCHETYPES["bird"], "chicken")}


# --------------------------------------------------------------------------
# props - objects rather than creatures
# --------------------------------------------------------------------------

def build_prop(prop, words, scale, bulk, style, extras):
    fn = PROPS.get(prop) or PROPS["crate"]
    defaults = PROP_COLORS.get(prop, ("#8c8f94", "#5a5d61"))
    pal = pick_colors(words, defaults[0], defaults[1])
    steps = fn(scale, pal, words, style or "round", bulk)
    top = 0.0
    for st in steps:
        top = max(top, st["loc"][2] + st["size"][2])
    # everything that is not a creature gets one root bone plus whatever
    # chain its own builder asked for, so it can still be moved and spun
    if not any(st["bone"] for st in steps):
        steps[0] = dict(steps[0], bone=bone("root", [0, 0, 0], [0, 0, top * 0.5]))
    return steps, {"rig_profile": "prop", "height": top,
                   "style": style or "round",
                   "organic": prop in ORGANIC_PROPS,
                   "subject": prop or "object"}


PROP_COLORS = {
    "tree": ("#3f7d3f", "#6b4b2a"), "bush": ("#3f7d3f", "#2f5d2f"),
    "mushroom": ("#c0392b", "#ecf0f1"), "rock": ("#8b8f94", "#6b7075"),
    "crystal": ("#5ec8d8", "#2b7f8c"), "chair": ("#8b5a2b", "#6b4423"),
    "table": ("#8b5a2b", "#6b4423"), "barrel": ("#8b5a2b", "#5a5d61"),
    "crate": ("#b08968", "#6b4423"), "chest": ("#8b5a2b", "#d4a017"),
    "sword": ("#c7cdd2", "#5a3a22"), "axe": ("#c7cdd2", "#7a5230"),
    "hammer": ("#8b8f94", "#7a5230"), "staff": ("#7a5230", "#1abc9c"),
    "shield": ("#a8332f", "#d4a017"), "house": ("#d8c3a5", "#a0392f"),
    "tower": ("#9aa0a6", "#7f2b2b"), "rocket": ("#ecf0f1", "#c0392b"),
    "car": ("#2e6fdb", "#1d1f21"), "lamp": ("#3b3f45", "#f5d76e"),
    "torch": ("#7a5230", "#e67e22"), "potion": ("#7ed321", "#6b4423"),
    "key": ("#d4a017", "#b8860b"), "coin": ("#d4a017", "#b8860b"),
    "book": ("#7f2b2b", "#e8e2d0"), "barrier": ("#8b5a2b", "#6b4423"),
    "ball": ("#ecf0f1", "#1d1f21"), "cone": ("#e67e22", "#ecf0f1"),
    "signpost": ("#8b5a2b", "#e8e2d0"), "flag": ("#c0392b", "#8b5a2b"),
    "well": ("#8b8f94", "#6b4423"), "cactus": ("#3f7d3f", "#2f5d2f"),
    "snowman": ("#ecf0f1", "#e67e22"), "campfire": ("#7a5230", "#e67e22"),
}


def _p_tree(s, pal, words, style, bulk):
    h = 3.0 * s
    trunk_r = 0.045 * h * bulk
    palm = "palm" in words
    pine = "pine" in words
    S = [limb("trunk", [0, 0, 0], [0, 0, h * 0.55], trunk_r, trunk_r * 0.72,
              pal["accent"], bone("trunk", [0, 0, 0], [0, 0, h * 0.55]), "trunk")]
    if pine:
        for i in range(3):
            t = i / 2.0
            S.append(step("canopy_%02d" % i, "cone",
                          [h * (0.30 - 0.08 * t), h * (0.30 - 0.08 * t), h * 0.26],
                          [0, 0, h * (0.52 + 0.20 * i)], pal["body"],
                          bone=bone("canopy_%02d" % i, [0, 0, h * (0.52 + 0.20 * i)],
                                    [0, 0, h * (0.70 + 0.20 * i)],
                                    "trunk" if i == 0 else "canopy_%02d" % (i - 1)),
                          label="branches %d" % (i + 1)))
    elif palm:
        for i in range(6):
            a = i * 1.047
            S.append(step("frond_%02d" % i, "box",
                          [h * 0.06, h * 0.30, h * 0.02],
                          [0.28 * h * _cos(a), 0.28 * h * _sin(a), h * 0.58],
                          pal["body"], rot=(0.35, 0, a + 1.5708), label="frond"))
    else:
        for i, (dx, dy, dz, r) in enumerate([(0, 0, 0.74, 0.30),
                                             (0.16, 0.06, 0.62, 0.20),
                                             (-0.14, -0.08, 0.66, 0.18)]):
            S.append(step("canopy_%02d" % i, "sphere",
                          [h * r, h * r * 0.9, h * r * 0.85],
                          [dx * h, dy * h, dz * h], pal["body"],
                          bone=bone("canopy_%02d" % i, [0, 0, h * 0.55],
                                    [dx * h, dy * h, dz * h], "trunk")
                          if i == 0 else None,
                          label="leaves %d" % (i + 1)))
    return S


def _p_bush(s, pal, words, style, bulk):
    h = 0.7 * s
    return [step("bush_%02d" % i, "sphere",
                 [h * r, h * r * 0.9, h * r * 0.8],
                 [dx * h, dy * h, h * z], pal["body"] if i % 2 == 0 else pal["accent"],
                 label="clump %d" % (i + 1))
            for i, (dx, dy, z, r) in enumerate(
                [(0, 0, 0.42, 0.5), (0.34, 0.1, 0.32, 0.36), (-0.3, -0.14, 0.34, 0.4)])]


def _p_mushroom(s, pal, words, style, bulk):
    h = 0.5 * s
    S = [limb("stalk", [0, 0, 0], [0, 0, h * 0.62], h * 0.14 * bulk, h * 0.12,
              pal["accent"], bone("stalk", [0, 0, 0], [0, 0, h * 0.62]), "stalk"),
         step("cap", "sphere", [h * 0.46, h * 0.46, h * 0.34],
              [0, 0, h * 0.66], pal["body"],
              bone=bone("cap", [0, 0, h * 0.62], [0, 0, h * 1.0], "stalk"),
              label="cap")]
    for i, (dx, dy) in enumerate([(0.16, 0.06), (-0.14, 0.12), (0.02, -0.18)]):
        S.append(step("spot_%02d" % i, "sphere", [h * 0.09, h * 0.09, h * 0.05],
                      [dx * h, dy * h, h * 0.86], "#ecf0f1", label="spot"))
    return S


def _p_rock(s, pal, words, style, bulk):
    h = 0.6 * s
    return [step("rock_%02d" % i, "box" if style == "blocky" else "sphere",
                 [h * r, h * r * 0.85, h * r * 0.7],
                 [dx * h, dy * h, h * z], pal["body"] if i == 0 else pal["accent"],
                 rot=(0.1 * i, 0.2 * i, 0.4 * i), label="rock %d" % (i + 1))
            for i, (dx, dy, z, r) in enumerate(
                [(0, 0, 0.3, 0.55), (0.45, 0.15, 0.16, 0.28), (-0.4, 0.2, 0.13, 0.22)])]


def _p_crystal(s, pal, words, style, bulk):
    h = 0.9 * s
    S = []
    for i, (dx, dy, sc, tilt) in enumerate([(0, 0, 1.0, 0.0), (0.22, 0.08, 0.55, 0.28),
                                            (-0.18, 0.14, 0.42, -0.32)]):
        S.append(step("shard_%02d" % i, "cone",
                      [h * 0.16 * sc, h * 0.16 * sc, h * 0.55 * sc],
                      [dx * h, dy * h, h * 0.57 * sc], pal["body"],
                      rot=(tilt, 0, i * 0.7),
                      bone=bone("shard", [0, 0, 0], [0, 0, h * 0.6]) if i == 0 else None,
                      detail={"segments": 6}, label="shard %d" % (i + 1)))
    return S


def _p_chair(s, pal, words, style, bulk):
    h = 0.9 * s
    w, d, seat = 0.42 * s, 0.42 * s, 0.45 * s
    S = [step("seat", "box", [w / 2, d / 2, 0.03 * s], [0, 0, seat], pal["body"],
              label="seat")]
    for i, (sx, sy) in enumerate([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        S.append(step("leg_%02d" % i, "box",
                      [0.025 * s, 0.025 * s, seat / 2],
                      [sx * (w / 2 - 0.03 * s), sy * (d / 2 - 0.03 * s), seat / 2],
                      pal["accent"], label="leg %d" % (i + 1)))
    S.append(step("back", "box", [w / 2, 0.025 * s, (h - seat) / 2],
                  [0, d / 2 - 0.03 * s, seat + (h - seat) / 2], pal["body"],
                  label="backrest"))
    return S


def _p_table(s, pal, words, style, bulk):
    h = 0.75 * s
    w, d = 0.7 * s, 0.5 * s
    S = [step("top", "box", [w, d, 0.03 * s], [0, 0, h], pal["body"], label="table top")]
    for i, (sx, sy) in enumerate([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        S.append(step("leg_%02d" % i, "box", [0.035 * s, 0.035 * s, h / 2],
                      [sx * (w - 0.06 * s), sy * (d - 0.06 * s), h / 2],
                      pal["accent"], label="leg %d" % (i + 1)))
    return S


def _p_barrel(s, pal, words, style, bulk):
    h = 0.9 * s
    r = 0.30 * s * bulk
    S = [step("body", "cylinder", [r, r, h / 2], [0, 0, h / 2], pal["body"],
              label="barrel body")]
    for i, z in enumerate((0.22, 0.5, 0.78)):
        S.append(step("band_%02d" % i, "cylinder",
                      [r * 1.06, r * 1.06, 0.022 * s], [0, 0, h * z],
                      pal["accent"], label="iron band %d" % (i + 1)))
    return S


def _p_crate(s, pal, words, style, bulk):
    a = 0.5 * s
    S = [step("box", "box", [a, a, a], [0, 0, a], pal["body"], label="crate")]
    for i, (ax, ay, az, sx, sy, sz) in enumerate([
            (0, 0, 1, a * 1.02, a * 1.02, 0.03 * s),
            (0, 0, 0.02, a * 1.02, a * 1.02, 0.03 * s)]):
        S.append(step("rail_%02d" % i, "box", [sx, sy, sz],
                      [ax, ay, a * 2 * az], pal["accent"], label="plank %d" % (i + 1)))
    return S


def _p_chest(s, pal, words, style, bulk):
    w, d, h = 0.42 * s, 0.28 * s, 0.26 * s
    return [
        step("base", "box", [w, d, h], [0, 0, h], pal["body"], label="chest base"),
        step("lid", "cylinder", [d, d, w], [0, 0, h * 2], pal["body"],
             rot=(0, 1.5708, 0), detail={"half": True}, label="lid"),
        step("lock", "box", [0.05 * s, 0.02 * s, 0.05 * s],
             [0, -d - 0.01 * s, h * 1.6], pal["accent"], label="lock"),
        step("band", "box", [w * 1.02, 0.03 * s, h * 1.02], [0, 0, h],
             pal["accent"], label="iron band"),
    ]


def _p_sword(s, pal, words, style, bulk):
    L = 1.1 * s
    return [
        step("blade", "box", [0.035 * L, 0.012 * L, 0.34 * L],
             [0, 0, 0.62 * L], pal["body"],
             bone=bone("root", [0, 0, 0], [0, 0, L * 0.5]), label="blade"),
        step("tip", "cone", [0.035 * L, 0.012 * L, 0.08 * L],
             [0, 0, 1.03 * L], pal["body"], label="tip"),
        step("guard", "box", [0.13 * L, 0.025 * L, 0.02 * L],
             [0, 0, 0.27 * L], pal["accent"], label="cross guard"),
        step("grip", "cylinder", [0.022 * L, 0.022 * L, 0.11 * L],
             [0, 0, 0.15 * L], "#5a3a22", label="grip"),
        step("pommel", "sphere", [0.038 * L] * 3, [0, 0, 0.03 * L],
             pal["accent"], label="pommel"),
    ]


def _p_axe(s, pal, words, style, bulk):
    L = 0.8 * s
    return [
        step("handle", "cylinder", [0.022 * L, 0.022 * L, L / 2], [0, 0, L / 2],
             pal["accent"], bone=bone("root", [0, 0, 0], [0, 0, L]), label="handle"),
        step("head", "box", [0.03 * L, 0.10 * L, 0.10 * L],
             [0, 0.06 * L, L * 0.88], pal["body"], label="axe head"),
        step("blade", "cone", [0.03 * L, 0.16 * L, 0.11 * L],
             [0, 0.16 * L, L * 0.88], pal["body"], rot=(-1.5708, 0, 0),
             label="blade"),
    ]


def _p_hammer(s, pal, words, style, bulk):
    L = 0.8 * s
    return [
        step("handle", "cylinder", [0.024 * L, 0.024 * L, L / 2], [0, 0, L / 2],
             pal["accent"], bone=bone("root", [0, 0, 0], [0, 0, L]), label="handle"),
        step("head", "box", [0.16 * L, 0.09 * L, 0.09 * L], [0, 0, L * 0.92],
             pal["body"], label="hammer head"),
    ]


def _p_staff(s, pal, words, style, bulk):
    L = 1.6 * s
    return [
        step("shaft", "cylinder", [0.018 * L, 0.018 * L, L / 2], [0, 0, L / 2],
             pal["body"], bone=bone("root", [0, 0, 0], [0, 0, L]), label="shaft"),
        step("claw", "torus", [0.07 * L, 0.018 * L, 0.07 * L], [0, 0, L * 0.97],
             pal["body"], rot=(1.5708, 0, 0), label="claw"),
        step("gem", "sphere", [0.05 * L] * 3, [0, 0, L * 0.97], pal["accent"],
             label="gem"),
    ]


def _p_shield(s, pal, words, style, bulk):
    r = 0.36 * s
    return [
        step("face", "cylinder", [r, r, 0.025 * s], [0, 0, r], pal["body"],
             rot=(1.5708, 0, 0), bone=bone("root", [0, 0, 0], [0, 0, r * 2]),
             label="shield face"),
        step("rim", "torus", [r, 0.028 * s, r], [0, 0, r], pal["accent"],
             rot=(1.5708, 0, 0), label="rim"),
        step("boss", "sphere", [0.08 * s, 0.05 * s, 0.08 * s],
             [0, -0.04 * s, r], pal["accent"], label="boss"),
    ]


def _p_house(s, pal, words, style, bulk):
    w, d, h = 1.6 * s, 1.3 * s, 1.2 * s
    return [
        step("walls", "box", [w, d, h / 2], [0, 0, h / 2], pal["body"], label="walls"),
        step("roof", "cone", [w * 1.25, d * 1.25, h * 0.55], [0, 0, h * 1.05],
             pal["accent"], detail={"segments": 4}, rot=(0, 0, 0.7854), label="roof"),
        step("door", "box", [0.22 * s, 0.03 * s, 0.34 * s],
             [0, -d - 0.01 * s, 0.34 * s], "#6b4423", label="door"),
        step("window_L", "box", [0.16 * s, 0.03 * s, 0.16 * s],
             [-w * 0.5, -d - 0.01 * s, h * 0.62], "#9fd3e8", label="window"),
        step("window_R", "box", [0.16 * s, 0.03 * s, 0.16 * s],
             [w * 0.5, -d - 0.01 * s, h * 0.62], "#9fd3e8", label="window"),
        step("chimney", "box", [0.12 * s, 0.12 * s, 0.30 * s],
             [w * 0.45, d * 0.3, h * 1.15], "#8b5a2b", label="chimney"),
    ]


def _p_tower(s, pal, words, style, bulk):
    r, h = 0.6 * s, 3.2 * s
    S = [step("shaft", "cylinder", [r, r, h / 2], [0, 0, h / 2], pal["body"],
              bone=bone("root", [0, 0, 0], [0, 0, h]), label="tower shaft"),
         step("crown", "cylinder", [r * 1.18, r * 1.18, 0.08 * s],
              [0, 0, h * 0.97], pal["accent"], label="parapet"),
         step("roof", "cone", [r * 1.1, r * 1.1, 0.8 * s], [0, 0, h + 0.4 * s],
              pal["accent"], label="roof")]
    for i in range(3):
        S.append(step("window_%02d" % i, "box",
                      [0.07 * s, 0.03 * s, 0.14 * s],
                      [0, -r - 0.01 * s, h * (0.35 + 0.22 * i)], "#2b2b2b",
                      label="window %d" % (i + 1)))
    return S


def _p_rocket(s, pal, words, style, bulk):
    h = 2.4 * s
    r = 0.26 * s * bulk
    S = [step("body", "cylinder", [r, r, h * 0.36], [0, 0, h * 0.42], pal["body"],
              bone=bone("root", [0, 0, 0], [0, 0, h]), label="fuselage"),
         step("nose", "cone", [r, r, h * 0.26], [0, 0, h * 0.91], pal["accent"],
              label="nose cone"),
         step("window", "sphere", [r * 0.32, r * 0.32, r * 0.32],
              [0, -r * 0.95, h * 0.58], "#9fd3e8", label="porthole"),
         step("engine", "cone", [r * 0.9, r * 0.9, h * 0.1], [0, 0, h * 0.10],
              "#4a4d52", label="engine bell")]
    for i in range(3):
        a = i * 2.0944
        S.append(step("fin_%02d" % i, "box", [r * 0.09, r * 1.1, h * 0.14],
                      [_cos(a) * r * 1.0, _sin(a) * r * 1.0, h * 0.14],
                      pal["accent"], rot=(0, 0, a + 1.5708), label="fin %d" % (i + 1)))
    return S


def _p_car(s, pal, words, style, bulk):
    L, W = 2.0 * s, 0.85 * s
    S = [step("chassis", "box", [W, L, 0.22 * s], [0, 0, 0.42 * s], pal["body"],
              bone=bone("root", [0, 0, 0], [0, -L, 0]), label="chassis"),
         step("cabin", "box", [W * 0.85, L * 0.45, 0.22 * s],
              [0, L * 0.08, 0.78 * s], pal["body"], label="cabin"),
         step("windscreen", "box", [W * 0.8, 0.02 * s, 0.17 * s],
              [0, L * 0.45 - 0.08 * s, 0.78 * s], "#9fd3e8", label="windscreen")]
    for i, (sx, sy) in enumerate([(1, 1), (1, -1), (-1, 1), (-1, -1)]):
        S.append(step("wheel_%02d" % i, "cylinder",
                      [0.24 * s, 0.24 * s, 0.09 * s],
                      [sx * W, sy * L * 0.6, 0.24 * s], pal["accent"],
                      rot=(0, 1.5708, 0), label="wheel %d" % (i + 1)))
    return S


def _p_lamp(s, pal, words, style, bulk):
    h = 2.6 * s
    return [
        step("base", "cylinder", [0.14 * s, 0.14 * s, 0.05 * s], [0, 0, 0.05 * s],
             pal["body"], label="base"),
        limb("post", [0, 0, 0.05 * s], [0, 0, h * 0.88], 0.045 * s, 0.035 * s,
             pal["body"], bone("root", [0, 0, 0], [0, 0, h]), "post"),
        step("housing", "cone", [0.22 * s, 0.22 * s, 0.16 * s], [0, 0, h * 0.94],
             pal["body"], rot=(3.1416, 0, 0), label="housing"),
        step("bulb", "sphere", [0.13 * s, 0.13 * s, 0.10 * s], [0, 0, h * 0.86],
             pal["accent"], detail={"emissive": 2.5}, label="bulb"),
    ]


def _p_torch(s, pal, words, style, bulk):
    h = 0.8 * s
    return [
        limb("handle", [0, 0, 0], [0, 0, h * 0.72], 0.035 * s, 0.03 * s,
             pal["body"], bone("root", [0, 0, 0], [0, 0, h]), "handle"),
        step("wrap", "cylinder", [0.055 * s, 0.055 * s, 0.07 * s], [0, 0, h * 0.74],
             "#4a3524", label="cloth wrap"),
        step("flame", "cone", [0.09 * s, 0.09 * s, 0.17 * s], [0, 0, h * 0.95],
             pal["accent"], detail={"emissive": 4.0}, label="flame"),
    ]


def _p_potion(s, pal, words, style, bulk):
    h = 0.32 * s
    return [
        step("bulb", "sphere", [h * 0.45, h * 0.45, h * 0.42], [0, 0, h * 0.42],
             pal["body"], detail={"glass": True},
             bone=bone("root", [0, 0, 0], [0, 0, h]), label="bulb"),
        step("neck", "cylinder", [h * 0.14, h * 0.14, h * 0.18], [0, 0, h * 0.92],
             pal["body"], detail={"glass": True}, label="neck"),
        step("cork", "cylinder", [h * 0.15, h * 0.15, h * 0.09], [0, 0, h * 1.16],
             pal["accent"], label="cork"),
    ]


def _p_key(s, pal, words, style, bulk):
    L = 0.3 * s
    S = [step("bow", "torus", [L * 0.22, L * 0.06, L * 0.22], [0, 0, L * 0.22],
              pal["body"], rot=(1.5708, 0, 0),
              bone=bone("root", [0, 0, 0], [0, 0, L]), label="bow"),
         step("shaft", "cylinder", [L * 0.05, L * 0.05, L * 0.34],
              [0, 0, L * 0.72], pal["body"], label="shaft")]
    for i, z in enumerate((0.92, 1.02)):
        S.append(step("tooth_%02d" % i, "box", [L * 0.11, L * 0.04, L * 0.04],
                      [L * 0.11, 0, L * z], pal["body"], label="tooth %d" % (i + 1)))
    return S


def _p_coin(s, pal, words, style, bulk):
    r = 0.18 * s
    return [
        step("coin", "cylinder", [r, r, 0.022 * s], [0, 0, r], pal["body"],
             rot=(1.5708, 0, 0), bone=bone("root", [0, 0, 0], [0, 0, r * 2]),
             label="coin"),
        step("rim", "torus", [r, 0.02 * s, r], [0, 0, r], pal["accent"],
             rot=(1.5708, 0, 0), label="rim"),
    ]


def _p_book(s, pal, words, style, bulk):
    w, d, h = 0.22 * s, 0.30 * s, 0.05 * s
    return [
        step("cover", "box", [w, d, h], [0, 0, h], pal["body"], label="cover"),
        step("pages", "box", [w * 0.94, d * 0.94, h * 0.8], [0, 0.01 * s, h],
             pal["accent"], label="pages"),
        step("spine", "box", [0.02 * s, d, h * 1.06], [-w, 0, h], pal["body"],
             bone=bone("root", [0, 0, 0], [0, 0, h * 2]), label="spine"),
    ]


def _p_barrier(s, pal, words, style, bulk):
    w, h = 1.4 * s, 0.9 * s
    S = []
    for i in range(4):
        S.append(step("post_%02d" % i, "box", [0.05 * s, 0.05 * s, h / 2],
                      [(-w + i * (2 * w / 3)), 0, h / 2], pal["accent"],
                      label="post %d" % (i + 1)))
    for i, z in enumerate((0.35, 0.75)):
        S.append(step("rail_%02d" % i, "box", [w, 0.03 * s, 0.05 * s],
                      [0, 0, h * z], pal["body"], label="rail %d" % (i + 1)))
    return S


def _p_ball(s, pal, words, style, bulk):
    r = 0.22 * s
    return [step("ball", "sphere", [r, r, r], [0, 0, r], pal["body"],
                 bone=bone("root", [0, 0, 0], [0, 0, r * 2]), label="ball")]


def _p_cone(s, pal, words, style, bulk):
    h = 0.7 * s
    return [
        step("base", "box", [0.22 * s, 0.22 * s, 0.025 * s], [0, 0, 0.025 * s],
             pal["body"], label="base"),
        step("cone", "cone", [0.16 * s, 0.16 * s, h / 2], [0, 0, h / 2 + 0.03 * s],
             pal["body"], bone=bone("root", [0, 0, 0], [0, 0, h]), label="cone"),
        step("stripe", "cylinder", [0.11 * s, 0.11 * s, 0.05 * s], [0, 0, h * 0.55],
             pal["accent"], label="reflective stripe"),
    ]


def _p_signpost(s, pal, words, style, bulk):
    h = 1.8 * s
    return [
        limb("post", [0, 0, 0], [0, 0, h], 0.045 * s, 0.04 * s, pal["body"],
             bone("root", [0, 0, 0], [0, 0, h]), "post"),
        step("board", "box", [0.34 * s, 0.03 * s, 0.18 * s], [0.1 * s, 0, h * 0.86],
             pal["accent"], label="sign board"),
    ]


def _p_flag(s, pal, words, style, bulk):
    h = 2.2 * s
    S = [limb("pole", [0, 0, 0], [0, 0, h], 0.035 * s, 0.028 * s, pal["accent"],
              bone("pole", [0, 0, 0], [0, 0, h]), "pole")]
    prev = "pole"
    for i in range(3):
        x0 = 0.03 * s + i * 0.24 * s
        x1 = x0 + 0.24 * s
        nm = "cloth_%02d" % i
        S.append(step(nm, "box", [0.12 * s, 0.01 * s, 0.16 * s],
                      [(x0 + x1) / 2, 0, h * 0.86], pal["body"],
                      bone=bone(nm, [x0, 0, h * 0.86], [x1, 0, h * 0.86], prev),
                      label="cloth %d" % (i + 1)))
        prev = nm
    return S


def _p_well(s, pal, words, style, bulk):
    r, h = 0.55 * s, 0.6 * s
    S = [step("wall", "cylinder", [r, r, h / 2], [0, 0, h / 2], pal["body"],
              bone=bone("root", [0, 0, 0], [0, 0, h * 2]), label="stone wall"),
         step("water", "cylinder", [r * 0.85, r * 0.85, 0.01 * s], [0, 0, h * 0.8],
              "#2e6fdb", label="water")]
    for sx in (1, -1):
        S.append(step("upright_%d" % (sx > 0), "box",
                      [0.04 * s, 0.04 * s, 0.5 * s],
                      [sx * r * 0.85, 0, h + 0.5 * s], pal["accent"], label="upright"))
    S.append(step("roof", "cone", [r * 1.3, r * 1.3, 0.35 * s], [0, 0, h + 1.15 * s],
                  pal["accent"], detail={"segments": 4}, rot=(0, 0, 0.7854),
                  label="roof"))
    return S


def _p_cactus(s, pal, words, style, bulk):
    h = 1.5 * s
    S = [limb("trunk", [0, 0, 0], [0, 0, h], 0.16 * s * bulk, 0.14 * s,
              pal["body"], bone("trunk", [0, 0, 0], [0, 0, h]), "trunk")]
    for i, (sx, z) in enumerate([(1, 0.52), (-1, 0.66)]):
        S.append(limb("arm_%02d" % i, [sx * 0.14 * s, 0, h * z],
                      [sx * 0.38 * s, 0, h * (z + 0.22)], 0.08 * s, 0.07 * s,
                      pal["body"], bone("arm_%02d" % i, [sx * 0.14 * s, 0, h * z],
                                        [sx * 0.38 * s, 0, h * (z + 0.22)], "trunk"),
                      "arm %d" % (i + 1)))
    return S


def _p_snowman(s, pal, words, style, bulk):
    h = 1.4 * s
    r1, r2, r3 = 0.30 * h, 0.22 * h, 0.16 * h
    S = [step("base", "sphere", [r1] * 3, [0, 0, r1], "#ecf0f1",
              bone=bone("hips", [0, 0, 0], [0, 0, r1 * 2]), label="bottom ball"),
         step("body", "sphere", [r2] * 3, [0, 0, r1 * 2 + r2 * 0.75], "#ecf0f1",
              bone=bone("spine", [0, 0, r1 * 2], [0, 0, r1 * 2 + r2 * 1.5], "hips"),
              label="middle ball"),
         step("head", "sphere", [r3] * 3,
              [0, 0, r1 * 2 + r2 * 1.5 + r3 * 0.8], "#ecf0f1",
              bone=bone("head", [0, 0, r1 * 2 + r2 * 1.5],
                        [0, 0, r1 * 2 + r2 * 1.5 + r3 * 2], "spine"), label="head")]
    zh = r1 * 2 + r2 * 1.5 + r3 * 0.8
    S.append(step("carrot", "cone", [r3 * 0.2, r3 * 0.2, r3 * 0.55],
                  [0, -r3 * 1.1, zh], pal["accent"], rot=(1.5708, 0, 0),
                  attach="head", label="carrot nose"))
    for sx in (1, -1):
        S.append(step("eye_%d" % (sx > 0), "sphere", [r3 * 0.13] * 3,
                      [sx * r3 * 0.38, -r3 * 0.82, zh + r3 * 0.3], "#17202a",
                      label="eye"))
        S.append(limb("arm_%d" % (sx > 0), [sx * r2 * 0.8, 0, r1 * 2 + r2 * 0.8],
                      [sx * (r2 + 0.3 * h), 0, r1 * 2 + r2 * 1.5],
                      0.02 * h, 0.014 * h, "#6b4423",
                      bone("arm.%s" % ("L" if sx > 0 else "R"),
                           [sx * r2 * 0.8, 0, r1 * 2 + r2 * 0.8],
                           [sx * (r2 + 0.3 * h), 0, r1 * 2 + r2 * 1.5], "spine"),
                      "stick arm"))
    return S


def _p_campfire(s, pal, words, style, bulk):
    r = 0.45 * s
    S = []
    for i in range(8):
        a = i * 0.7854
        S.append(step("stone_%02d" % i, "sphere",
                      [r * 0.20, r * 0.20, r * 0.15],
                      [_cos(a) * r, _sin(a) * r, r * 0.11], "#8b8f94",
                      label="stone %d" % (i + 1)))
    # four logs leaning into each other, wigwam fashion
    for i in range(4):
        a = i * 1.5708 + 0.4
        S.append(limb("log_%02d" % i,
                      [_cos(a) * r * 0.62, _sin(a) * r * 0.62, 0.02 * s],
                      [_cos(a) * r * 0.10, _sin(a) * r * 0.10, r * 0.86],
                      0.042 * s, 0.032 * s, pal["body"], None, "log %d" % (i + 1)))
    S.append(step("flame", "cone", [r * 0.30, r * 0.30, r * 0.44],
                  [0, 0, r * 0.62], pal["accent"], detail={"emissive": 1.8},
                  bone=bone("root", [0, 0, 0], [0, 0, r * 1.4]), label="flame"))
    S.append(step("flame_core", "cone", [r * 0.16, r * 0.16, r * 0.26],
                  [0, 0, r * 0.44], "#f5d76e", detail={"emissive": 2.6},
                  label="flame core"))
    return S


def _cos(a):
    import math
    return math.cos(a)


def _sin(a):
    import math
    return math.sin(a)


PROPS = {
    "tree": _p_tree, "bush": _p_bush, "mushroom": _p_mushroom, "rock": _p_rock,
    "crystal": _p_crystal, "chair": _p_chair, "table": _p_table,
    "barrel": _p_barrel, "crate": _p_crate, "chest": _p_chest, "sword": _p_sword,
    "axe": _p_axe, "hammer": _p_hammer, "staff": _p_staff, "shield": _p_shield,
    "house": _p_house, "tower": _p_tower, "rocket": _p_rocket, "car": _p_car,
    "lamp": _p_lamp, "torch": _p_torch, "potion": _p_potion, "key": _p_key,
    "coin": _p_coin, "book": _p_book, "barrier": _p_barrier, "ball": _p_ball,
    "cone": _p_cone, "signpost": _p_signpost, "flag": _p_flag, "well": _p_well,
    "cactus": _p_cactus, "snowman": _p_snowman, "campfire": _p_campfire,
}


# ==========================================================================
# outfits: a character is assembled, not carved
#
# A knight is not a blue person. It is a body, and then a breastplate, and
# then a pauldron on each shoulder, and then gauntlets, a belt, tassets,
# greaves, boots and a helmet - each one its own piece, fitted over the body
# underneath and tied to the bone it should move with.
#
# Every module below is a function of the body it is going onto, so the same
# helmet fits a tall thin figure and a short fat one. Modules are always left
# crisp by the sculpt pass: a plate that has been remeshed into the chest is
# no longer a plate.
# ==========================================================================

# the body's landmarks, as fractions of total height (see build_humanoid)
Z_ANKLE, Z_KNEE, Z_HIP = 0.045, 0.260, 0.500
Z_WAIST, Z_CHEST, Z_SHOULDER = 0.625, 0.762, 0.820
Z_CHIN, Z_TOP = 0.873, 0.998
X_HIP = 0.055

# where the arm is, at a given height
_ARM = [(0.810, 0.100, 0.033), (0.625, 0.132, 0.025),
        (0.500, 0.150, 0.018), (0.406, 0.156, 0.013)]


def arm_at(z):
    """(x offset, radius) of the arm at height z, both as fractions of H."""
    if z >= _ARM[0][0]:
        return _ARM[0][1], _ARM[0][2]
    for (z0, x0, r0), (z1, x1, r1) in zip(_ARM, _ARM[1:]):
        if z1 <= z <= z0:
            t = (z0 - z) / (z0 - z1)
            return x0 + (x1 - x0) * t, r0 + (r1 - r0) * t
    return _ARM[-1][1], _ARM[-1][2]


def leg_at(z):
    """(x offset, radius) of the leg at height z."""
    if z >= Z_HIP:
        return 0.052, 0.060
    if z >= Z_KNEE:
        t = (Z_HIP - z) / (Z_HIP - Z_KNEE)
        return 0.052 + 0.003 * t, 0.060 - 0.022 * t
    t = max(0.0, min(1.0, (Z_KNEE - z) / (Z_KNEE - Z_ANKLE)))
    return 0.055 + 0.003 * t, 0.038 - 0.017 * t


class Fit(object):
    """What a module needs to know about the body it is dressing."""

    def __init__(self, H, B, pal, skin, style, head_scale):
        self.H, self.B, self.pal, self.skin = H, B, pal, skin
        self.style, self.head_scale = style, head_scale
        self.main = pal["body"]
        self.trim = pal["accent"]
        self.dark = pal["dark"]
        self.light = pal["light"]
        self.leather = "#5a3a22"
        self.cloth = pal["light"]

    def r(self, x, y, z, rx, ry=None):
        return ring(x * self.H, y * self.H, z * self.H, rx * self.H,
                    (ry if ry is not None else rx) * self.H)

    def torso_rx(self, z):
        """Half-width of the torso at a height, so a garment can clear it."""
        table = [(Z_HIP, 0.077), (0.565, 0.088), (Z_WAIST, 0.071),
                 (0.695, 0.085), (Z_CHEST, 0.096), (Z_SHOULDER, 0.098)]
        if z <= table[0][0]:
            return table[0][1] * self.B
        for (z0, w0), (z1, w1) in zip(table, table[1:]):
            if z0 <= z <= z1:
                t = (z - z0) / (z1 - z0)
                return (w0 + (w1 - w0) * t) * self.B
        return table[-1][1] * self.B

    def head(self, t, grow=0.0):
        """A ring around the head, t running 0 at the chin to 1 at the crown."""
        s = self.head_scale
        z = Z_CHIN + (Z_TOP - Z_CHIN) * s * t
        profile = [(0.00, 0.028, 0.033), (0.17, 0.042, 0.050),
                   (0.36, 0.048, 0.056), (0.58, 0.049, 0.058),
                   (0.81, 0.042, 0.048), (1.00, 0.020, 0.024)]
        rx = ry = 0.0
        for (t0, x0, y0), (t1, x1, y1) in zip(profile, profile[1:]):
            if t0 <= t <= t1:
                k = (t - t0) / (t1 - t0)
                rx, ry = x0 + (x1 - x0) * k, y0 + (y1 - y0) * k
                break
        else:
            rx, ry = profile[-1][1], profile[-1][2]
        return z, (rx * s + grow), (ry * s + grow)


# --------------------------------------------------------------------------
# the modules. Each returns a list of parts and is named for what it is.
# --------------------------------------------------------------------------

def _o_helmet(f, horned=False):
    S = []
    rings = []
    for t, grow in ((0.05, 0.016), (0.22, 0.019), (0.45, 0.019), (0.70, 0.017),
                    (0.92, 0.012), (1.03, 0.004)):
        z, rx, ry = f.head(t, grow)
        rings.append(f.r(0, -0.003, z, rx, ry))
    S.append(loft("helmet", rings, f.main, attach="head", stage="armour",
                  hard=True, label="helmet"))
    z, rx, ry = f.head(0.40, 0.016)
    S.append(step("visor", "box", [rx * f.H * 0.92, 0.010 * f.H, 0.013 * f.H],
                  [0, -(ry + 0.004) * f.H, z * f.H], f.dark, attach="head",
                  stage="armour", hard=True, label="visor slit"))
    z, rx, ry = f.head(0.30, 0.014)
    S.append(step("nose_guard", "box",
                  [0.008 * f.H, 0.012 * f.H, 0.030 * f.H],
                  [0, -(ry + 0.002) * f.H, z * f.H], f.trim, attach="head",
                  stage="armour", hard=True, label="nose guard"))
    if horned:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            z, rx, ry = f.head(0.72, 0.012)
            S.append(step("horn.%s" % side, "cone",
                          [0.014 * f.H, 0.014 * f.H, 0.055 * f.H],
                          [rx * f.H * 0.95 * sx, -0.004 * f.H,
                           (z + 0.030) * f.H], "#e8e2d0",
                          rot=(0, 0.5 * sx, 0), attach="head", stage="armour",
                          hard=True, label="helmet horn"))
    return S


def _o_plume(f):
    """A crest running front to back along the helmet, not a mast."""
    z, rx, ry = f.head(0.92, 0.012)
    return [loft("plume", [
        f.r(0, -(ry * 0.80), z - 0.004, 0.006, 0.010),
        f.r(0, 0.000, z + 0.022, 0.007, 0.022),
        f.r(0, (ry * 0.85), z + 0.004, 0.006, 0.012),
    ], f.trim, attach="head", stage="armour", hard=True, label="crest")]


def _o_dome_helmet(f):
    z, rx, ry = f.head(0.50, 0.026)
    return [step("dome", "sphere", [rx * f.H, ry * f.H, ry * f.H],
                 [0, -0.004 * f.H, z * f.H], "#9fd3e8",
                 detail={"glass": True}, attach="head", stage="gear",
                 hard=True, label="helmet dome"),
            step("collar_ring", "torus",
                 [rx * f.H * 1.02, 0.010 * f.H, rx * f.H],
                 [0, -0.004 * f.H, (Z_CHIN - 0.004) * f.H], f.light,
                 attach="head", stage="gear", hard=True, label="neck ring")]


def _o_crown(f):
    S = []
    z, rx, ry = f.head(0.84, 0.010)
    S.append(loft("crown", [f.r(0, 0, z, rx, ry),
                            f.r(0, 0, z + 0.030, rx * 1.04, ry * 1.04)],
                  "#d4a017", attach="head", stage="clothing", hard=True,
                  label="crown"))
    for i in range(6):
        a = i * 1.047
        S.append(step("crown_point_%02d" % i, "cone",
                      [0.009 * f.H, 0.009 * f.H, 0.022 * f.H],
                      [_cos(a) * rx * f.H, _sin(a) * ry * f.H,
                       (z + 0.050) * f.H], "#d4a017", attach="head",
                      stage="clothing", hard=True, label="crown point"))
    return S


def _o_pointed_hat(f, brim=True, colour=None):
    colour = colour or f.trim
    S = []
    z, rx, ry = f.head(0.86, 0.008)
    if brim:
        S.append(step("hat_brim", "cylinder",
                      [rx * f.H * 1.9, ry * f.H * 1.8, 0.006 * f.H],
                      [0, -0.004 * f.H, z * f.H], colour, attach="head",
                      stage="clothing", hard=True, label="hat brim"))
    S.append(loft("hat", [f.r(0, -0.004, z, rx * 1.05, ry * 1.05),
                          f.r(0, -0.004, z + 0.055, rx * 0.70, ry * 0.70),
                          f.r(0, -0.002, z + 0.110, rx * 0.34, ry * 0.34),
                          f.r(0, 0.002, z + 0.155, rx * 0.06, ry * 0.06)],
                  colour, attach="head", stage="clothing", hard=True,
                  label="hat"))
    return S


def _o_round_hat(f, colour=None, tall=0.035):
    colour = colour or f.leather
    z, rx, ry = f.head(0.84, 0.008)
    return [step("hat_brim", "cylinder",
                 [rx * f.H * 1.95, ry * f.H * 1.75, 0.005 * f.H],
                 [0, -0.004 * f.H, z * f.H], colour, attach="head",
                 stage="clothing", hard=True, label="hat brim"),
            loft("hat", [f.r(0, -0.004, z - 0.006, rx * 1.10, ry * 1.10),
                         f.r(0, -0.004, z + tall * 0.55, rx * 1.06, ry * 1.06),
                         f.r(0, -0.004, z + tall, rx * 0.98, ry * 0.98),
                         f.r(0, -0.004, z + tall + 0.010, rx * 0.74, ry * 0.74)],
                 colour, attach="head", stage="clothing", hard=True,
                 label="hat")]


def _o_chef_hat(f):
    z, rx, ry = f.head(0.86, 0.010)
    return [loft("hat", [f.r(0, -0.004, z, rx * 1.05, ry * 1.05),
                         f.r(0, -0.004, z + 0.022, rx * 1.05, ry * 1.05),
                         f.r(0, -0.004, z + 0.040, rx * 1.35, ry * 1.35),
                         f.r(0, -0.004, z + 0.090, rx * 1.30, ry * 1.30),
                         f.r(0, -0.004, z + 0.105, rx * 0.90, ry * 0.90)],
                 "#f4f6f7", attach="head", stage="clothing", hard=True,
                 label="chef's hat")]


def _o_hood(f):
    """
    Pushed back off the face, so there is still someone inside it. The rings
    are offset behind the head and the front of the opening is cut away by
    keeping the lowest ring small and well back.
    """
    rings = []
    for t, grow, back in ((0.02, 0.008, 0.030), (0.28, 0.021, 0.012),
                          (0.58, 0.022, 0.006), (0.86, 0.019, 0.006),
                          (1.02, 0.008, 0.010)):
        z, rx, ry = f.head(t, grow)
        rings.append(f.r(0, back, z, rx, ry))
    S = [loft("hood", rings, f.main, attach="head", stage="clothing",
              hard=True, label="hood")]
    z, rx, ry = f.head(0.10, 0.022)
    S.append(loft("hood_shoulders", [
        f.r(0, 0.004, Z_SHOULDER + 0.010, f.torso_rx(Z_SHOULDER) + 0.022, 0.072),
        f.r(0, 0.006, 0.856, 0.066, 0.058),
        f.r(0, 0.010, z, rx * 0.92, ry * 0.92),
    ], f.main, attach="spine", stage="clothing", hard=True, label="cowl"))
    return S


def _o_mask(f):
    z, rx, ry = f.head(0.22, 0.012)
    return [loft("mask", [f.r(0, -0.002, Z_CHIN - 0.004, rx * 0.95, ry * 0.95),
                          f.r(0, -0.002, z + 0.020, rx, ry),
                          f.r(0, -0.002, z + 0.046, rx * 1.02, ry * 1.02)],
                 f.dark, attach="head", stage="clothing", hard=True,
                 label="face mask")]


def _o_eyepatch(f):
    z, rx, ry = f.head(0.52, 0.012)
    return [step("eyepatch", "box",
                 [0.020 * f.H, 0.006 * f.H, 0.018 * f.H],
                 [0.020 * f.H, -(ry + 0.001) * f.H, z * f.H], "#1d1f21",
                 attach="head", stage="clothing", hard=True, label="eyepatch"),
            step("eyepatch_strap", "torus",
                 [rx * f.H * 1.02, 0.004 * f.H, rx * f.H],
                 [0, -0.004 * f.H, z * f.H], "#1d1f21", rot=(0.2, 0, 0),
                 attach="head", stage="clothing", hard=True, label="strap")]


def _o_breastplate(f, colour=None, stage="armour"):
    colour = colour or f.main
    g = 0.010                                  # how far it stands off the body
    return [loft("breastplate", [
        f.r(0, 0.000, Z_WAIST + 0.010, f.torso_rx(Z_WAIST) + g * 0.8, 0.056),
        f.r(0, 0.002, 0.695, f.torso_rx(0.695) + g, 0.070),
        f.r(0, 0.006, Z_CHEST, f.torso_rx(Z_CHEST) + g, 0.076),
        f.r(0, 0.004, Z_SHOULDER, f.torso_rx(Z_SHOULDER) + g * 0.7, 0.068),
        f.r(0, 0.002, 0.848, 0.062, 0.053),
    ], colour, attach="spine", stage=stage, hard=True, label="breastplate")]


def _o_tunic(f, colour=None, hem=Z_HIP - 0.030, stage="clothing"):
    colour = colour or f.main
    g = 0.008
    S = [loft("tunic", [
        f.r(0, 0.000, hem, f.torso_rx(max(hem, Z_HIP)) + g * 1.6, 0.066),
        f.r(0, 0.000, Z_WAIST, f.torso_rx(Z_WAIST) + g, 0.058),
        f.r(0, 0.002, 0.700, f.torso_rx(0.700) + g, 0.069),
        f.r(0, 0.006, Z_CHEST, f.torso_rx(Z_CHEST) + g, 0.074),
        f.r(0, 0.004, Z_SHOULDER + 0.008, f.torso_rx(Z_SHOULDER) + g * 0.6, 0.066),
        f.r(0, 0.002, 0.850, 0.060, 0.051),
    ], colour, attach="spine", stage=stage, hard=True, label="tunic")]
    g2 = 0.009
    for side, sx in (("L", 1.0), ("R", -1.0)):
        x0, r0 = arm_at(Z_SHOULDER - 0.010)
        x1, r1 = arm_at(0.690)
        S.append(loft("sleeve.%s" % side, [
            f.r(x0 * sx, 0.002, Z_SHOULDER - 0.006, r0 + g2 * 1.4),
            f.r(((x0 + x1) / 2) * sx, 0.001, 0.740, (r0 + r1) / 2 + g2),
            f.r(x1 * sx, 0.000, 0.690, r1 + g2 * 0.8),
        ], colour, attach="upperarm.%s" % side, stage=stage, hard=True,
            label="short sleeve"))
    return S


def _o_coat(f, colour=None):
    colour = colour or f.main
    g = 0.012
    S = _o_tunic(f, colour, hem=Z_KNEE + 0.040, stage="clothing")
    S[0] = dict(S[0], part="coat", label="coat")
    for side, sx in (("L", 1.0), ("R", -1.0)):
        x0, r0 = arm_at(Z_SHOULDER - 0.010)
        x1, r1 = arm_at(0.560)
        S.append(loft("sleeve.%s" % side, [
            f.r(x0 * sx, 0.002, Z_SHOULDER - 0.010, r0 + g),
            f.r(((x0 + x1) / 2) * sx, 0.001, 0.690, (r0 + r1) / 2 + g),
            f.r(x1 * sx, 0.000, 0.560, r1 + g * 0.8),
        ], colour, attach="upperarm.%s" % side, stage="clothing", hard=True,
            label="sleeve"))
    return S


def _o_robe(f, colour=None):
    colour = colour or f.main
    g = 0.012
    S = [loft("robe", [
        f.r(0, 0.000, Z_ANKLE + 0.015, 0.150, 0.120),
        f.r(0, 0.000, Z_KNEE, 0.126, 0.104),
        f.r(0, 0.000, Z_HIP, f.torso_rx(Z_HIP) + 0.030, 0.082),
        f.r(0, 0.000, Z_WAIST, f.torso_rx(Z_WAIST) + g, 0.060),
        f.r(0, 0.004, Z_CHEST, f.torso_rx(Z_CHEST) + g, 0.076),
        f.r(0, 0.004, Z_SHOULDER + 0.008, f.torso_rx(Z_SHOULDER) + g * 0.6, 0.066),
        f.r(0, 0.002, 0.850, 0.060, 0.051),
    ], colour, attach="hips", stage="clothing", hard=True, label="robe")]
    for side, sx in (("L", 1.0), ("R", -1.0)):
        x0, r0 = arm_at(Z_SHOULDER - 0.010)
        x1, r1 = arm_at(0.520)
        S.append(loft("sleeve.%s" % side, [
            f.r(x0 * sx, 0.002, Z_SHOULDER - 0.010, r0 + g),
            f.r(((x0 + x1) / 2) * sx, 0.001, 0.670, (r0 + r1) / 2 + g * 1.6),
            f.r(x1 * sx, 0.000, 0.520, r1 + g * 2.4),
        ], colour, attach="upperarm.%s" % side, stage="clothing", hard=True,
            label="wide sleeve"))
    return S


def _o_apron(f):
    return [loft("apron", [
        f.r(0, -0.052, Z_KNEE + 0.060, 0.070, 0.006),
        f.r(0, -0.060, Z_HIP + 0.010, 0.078, 0.006),
        f.r(0, -0.066, Z_WAIST, 0.062, 0.006),
        f.r(0, -0.072, Z_CHEST - 0.010, 0.050, 0.006),
    ], "#f4f6f7", attach="hips", stage="clothing", hard=True, label="apron")]


def _o_fur_mantle(f):
    return [loft("mantle", [
        f.r(0, 0.004, 0.690, f.torso_rx(0.690) + 0.030, 0.090),
        f.r(0, 0.006, Z_CHEST, f.torso_rx(Z_CHEST) + 0.034, 0.096),
        f.r(0, 0.004, Z_SHOULDER + 0.014, f.torso_rx(Z_SHOULDER) + 0.030, 0.084),
        f.r(0, 0.002, 0.856, 0.070, 0.058),
    ], "#8b7355", attach="spine", stage="clothing", hard=True,
        label="fur mantle")]


def _o_loincloth(f):
    return [loft("loincloth", [
        f.r(0, 0.000, Z_HIP - 0.075, 0.086, 0.062),
        f.r(0, 0.000, Z_HIP + 0.010, 0.094, 0.068),
        f.r(0, 0.000, Z_WAIST - 0.020, 0.080, 0.058),
    ], f.leather, attach="hips", stage="clothing", hard=True,
        label="loincloth")]


def _o_pauldrons(f, colour=None):
    colour = colour or f.main
    S = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        S.append(loft("pauldron.%s" % side, [
            f.r(0.086 * sx, 0.002, 0.846, 0.030, 0.034),
            f.r(0.104 * sx, 0.002, 0.820, 0.052, 0.055),
            f.r(0.112 * sx, 0.002, 0.780, 0.050, 0.052),
            f.r(0.116 * sx, 0.002, 0.752, 0.040, 0.042),
        ], colour, attach="shoulder.%s" % side, stage="armour", hard=True,
            label="pauldron"))
    return S


def _o_gauntlets(f, colour=None, label="gauntlet"):
    colour = colour or f.light
    S = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        rings = []
        for z in (0.600, 0.560, 0.520, 0.480, 0.450):
            x, r = arm_at(z)
            rings.append(f.r(x * sx, 0.000, z, r + 0.009))
        S.append(loft("gauntlet.%s" % side, rings, colour,
                      attach="forearm.%s" % side, stage="armour", hard=True,
                      label=label))
    return S


def _o_greaves(f, colour=None):
    colour = colour or f.main
    S = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        rings = []
        for z in (0.250, 0.205, 0.140, 0.075):
            x, r = leg_at(z)
            rings.append(f.r(x * sx, 0.002, z, r + 0.009))
        S.append(loft("greave.%s" % side, rings, colour,
                      attach="shin.%s" % side, stage="armour", hard=True,
                      label="greave"))
    return S


def _o_boots(f, colour=None, top=0.150):
    colour = colour or f.leather
    S = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        rings = []
        for z in (top, top * 0.62, 0.060):
            x, r = leg_at(z)
            rings.append(f.r(x * sx, 0.000, z, r + 0.011))
        S.append(loft("boot_shaft.%s" % side, rings, colour,
                      attach="shin.%s" % side, stage="clothing", hard=True,
                      label="boot"))
        S.append(loft("boot.%s" % side, [
            ring(0.058 * f.H * sx, +0.034 * f.H, 0.034 * f.H,
                 0.026 * f.H, 0.030 * f.H),
            ring(0.058 * f.H * sx, -0.005 * f.H, 0.028 * f.H,
                 0.031 * f.H, 0.028 * f.H),
            ring(0.066 * f.H * sx, -0.050 * f.H, 0.022 * f.H,
                 0.033 * f.H, 0.023 * f.H),
            ring(0.076 * f.H * sx, -0.086 * f.H, 0.014 * f.H,
                 0.027 * f.H, 0.015 * f.H),
        ], colour, attach="foot.%s" % side, stage="clothing", hard=True,
            label="boot"))
    return S


def _o_belt(f, colour=None):
    colour = colour or f.leather
    w = f.torso_rx(Z_WAIST) + 0.012
    return [loft("belt", [f.r(0, -0.004, Z_WAIST - 0.022, w, 0.056),
                          f.r(0, -0.004, Z_WAIST + 0.008, w, 0.058)],
                 colour, attach="hips", stage="clothing", hard=True,
                 label="belt"),
            step("buckle", "box",
                 [0.020 * f.H, 0.008 * f.H, 0.020 * f.H],
                 [0, -0.062 * f.H, (Z_WAIST - 0.007) * f.H], "#d4a017",
                 attach="hips", stage="clothing", hard=True, label="buckle")]


def _o_tassets(f, colour=None):
    colour = colour or f.main
    return [loft("tassets", [
        f.r(0, -0.002, Z_WAIST - 0.020, f.torso_rx(Z_WAIST) + 0.014, 0.058),
        f.r(0, -0.002, Z_HIP + 0.020, 0.098, 0.074),
        f.r(0, -0.002, Z_HIP - 0.060, 0.108, 0.080),
    ], colour, attach="hips", stage="armour", hard=True, label="tassets")]


def _o_trousers(f, colour=None, hem=0.080):
    colour = colour or f.dark
    S = []
    for side, sx in (("L", 1.0), ("R", -1.0)):
        rings = []
        for z in (Z_HIP + 0.010, 0.400, Z_KNEE, 0.170, hem):
            x, r = leg_at(z)
            rings.append(f.r(x * sx, 0.000, z, r + 0.010))
        S.append(loft("trouser.%s" % side, rings, colour,
                      attach="thigh.%s" % side, stage="clothing", hard=True,
                      label="trouser leg"))
    return S


def _o_shorts(f, colour=None):
    return _o_trousers(f, colour, hem=0.330)


MODULES = {
    "helmet": _o_helmet,
    "horned_helmet": lambda f: _o_helmet(f, horned=True),
    "plume": _o_plume,
    "dome_helmet": _o_dome_helmet,
    "crown": _o_crown,
    "wizard_hat": lambda f: _o_pointed_hat(f),
    "witch_hat": lambda f: _o_pointed_hat(f, colour="#2c2440"),
    "straw_hat": lambda f: _o_round_hat(f, "#d8b25a"),
    "tricorn": lambda f: _o_round_hat(f, "#2b2b35", tall=0.026),
    "chef_hat": _o_chef_hat,
    "hood": _o_hood,
    "mask": _o_mask,
    "eyepatch": _o_eyepatch,
    "breastplate": _o_breastplate,
    "tunic": _o_tunic,
    "coat": _o_coat,
    "robe": _o_robe,
    "apron": _o_apron,
    "mantle": _o_fur_mantle,
    "loincloth": _o_loincloth,
    "pauldrons": _o_pauldrons,
    "gauntlets": _o_gauntlets,
    "wraps": lambda f: _o_gauntlets(f, f.dark, "wrist wrap"),
    "greaves": _o_greaves,
    "boots": _o_boots,
    "short_boots": lambda f: _o_boots(f, top=0.105),
    "belt": _o_belt,
    "tassets": _o_tassets,
    "trousers": _o_trousers,
    "shorts": _o_shorts,
}

HEAD_MODULES = {"helmet", "horned_helmet", "dome_helmet", "crown", "wizard_hat",
                "witch_hat", "straw_hat", "tricorn", "chef_hat", "hood"}
TORSO_MODULES = {"breastplate", "tunic", "coat", "robe", "mantle"}
LEG_MODULES = {"trousers", "shorts", "robe", "greaves"}

# What each kind of character is assembled from, in the order it goes on.
# A plain person still gets dressed; only the things that would not wear
# clothes are given an empty kit.
KITS = {
    "knight": ["breastplate", "pauldrons", "gauntlets", "belt", "tassets",
               "greaves", "boots", "helmet", "plume"],
    "paladin": ["breastplate", "pauldrons", "gauntlets", "belt", "tassets",
                "greaves", "boots", "helmet"],
    "guard": ["breastplate", "belt", "boots", "helmet"],
    "soldier": ["tunic", "belt", "boots", "helmet"],
    "warrior": ["loincloth", "belt", "pauldrons", "short_boots"],
    "viking": ["mantle", "belt", "boots", "horned_helmet"],
    "king": ["robe", "belt", "crown"],
    "queen": ["robe", "crown"],
    "wizard": ["robe", "belt", "wizard_hat"],
    "mage": ["robe", "belt", "wizard_hat"],
    "witch": ["robe", "belt", "witch_hat"],
    "ninja": ["tunic", "belt", "wraps", "short_boots", "hood", "mask"],
    "pirate": ["coat", "belt", "boots", "tricorn", "eyepatch"],
    "astronaut": ["tunic", "belt", "gauntlets", "boots", "dome_helmet"],
    "farmer": ["tunic", "trousers", "short_boots", "straw_hat"],
    "chef": ["tunic", "apron", "chef_hat"],
    "doctor": ["tunic", "coat"],
    "zombie": ["tunic"],
    "orc": ["loincloth", "belt", "pauldrons"],
    "goblin": ["tunic", "belt", "hood"],
    "elf": ["tunic", "belt", "short_boots"],
    "dwarf": ["tunic", "belt", "boots", "helmet"],
    "robot": ["breastplate", "pauldrons"],
    "android": ["breastplate", "pauldrons"],
    "mech": ["breastplate", "pauldrons", "greaves"],
    "hero": ["breastplate", "belt", "boots"],
    "villain": ["coat", "belt", "boots"],
    "footballer": ["tunic", "shorts", "short_boots"],
    "player": ["tunic", "shorts", "short_boots"],
    "referee": ["tunic", "shorts", "short_boots"],
    "mascot": ["tunic", "shorts"],
    # these wear nothing, on purpose
    "skeleton": [], "golem": [], "alien": [], "doll": [], "puppet": [],
    "avatar": ["tunic", "trousers", "short_boots"],
}

# When the prompt names no colour, the kit brings its own: a knight in steel
# rather than a knight in whatever the default happened to be.
KIT_COLOURS = {
    "knight": ("#8f98a3", "#d4a017"), "paladin": ("#c9ced6", "#d4a017"),
    "guard": ("#7f8c9b", "#a01f2e"), "soldier": ("#5b6b4a", "#3a4433"),
    "warrior": ("#8b5a2b", "#c0392b"), "viking": ("#7a6a52", "#8f98a3"),
    "king": ("#8e2b3a", "#d4a017"), "queen": ("#7d3c98", "#d4a017"),
    "wizard": ("#3b3d8f", "#d4a017"), "mage": ("#2e6fdb", "#9fd3e8"),
    "witch": ("#3a2b4f", "#7ed321"), "ninja": ("#23262c", "#a01f2e"),
    "pirate": ("#4a2f23", "#c0392b"), "astronaut": ("#ecf0f1", "#e67e22"),
    "farmer": ("#6b7a2f", "#8b5a2b"), "chef": ("#f4f6f7", "#c0392b"),
    "doctor": ("#f4f6f7", "#2e6fdb"), "zombie": ("#5f6b4a", "#3a4433"),
    "orc": ("#5d7a3f", "#4a3524"), "goblin": ("#6b7a2f", "#4a3524"),
    "elf": ("#2f6b4f", "#d4a017"), "dwarf": ("#7a4b2a", "#8f98a3"),
    "hero": ("#2e6fdb", "#d4a017"), "villain": ("#2b2b35", "#7d3c98"),
    "footballer": ("#c0392b", "#ecf0f1"), "referee": ("#1d1f21", "#f1c40f"),
}


DEFAULT_KIT = ["tunic", "trousers", "short_boots"]


def kit_for(words):
    """The list of pieces this character is assembled from."""
    for w in words:
        if w in KITS:
            return list(KITS[w]), w
    return list(DEFAULT_KIT), None


def dress(fit, kit):
    """Run each module in turn. One piece, then the next, in the order given."""
    out = []
    for name in kit:
        module = MODULES.get(name)
        if module:
            out += module(fit)
    return out
