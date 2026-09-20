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


def step(part, shape, size, loc, color, rot=(0, 0, 0), bone=None, label=None,
         detail=None, attach=None):
    """
    One part of the model.

    `bone` makes a new bone and is what makes the auto-rig button exact.
    `attach` names a bone made by some other part, for things that ride along
    rather than bend - an eye, a hat, a sword in a hand.
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
        "label": label or part.replace("_", " ").replace(".", " "),
        "detail": detail or {},
    }


def bone(name, head, tail, parent=None):
    return {"name": name, "head": [round(v, 4) for v in head],
            "tail": [round(v, 4) for v in tail], "parent": parent}


# --------------------------------------------------------------------------
# the main entry point
# --------------------------------------------------------------------------

def plan_from_prompt(prompt):
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

    return {
        "prompt": prompt,
        "archetype": archetype,
        "prop": prop,
        "name": _title(words, archetype),
        "style": style or meta.get("style", "round"),
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

def limb(part, head, tail, r0, r1, color, bone_def=None, label=None):
    """
    A part that runs between two points. The mesh builder works out the
    direction itself, so nothing here has to do trigonometry.
    """
    mid = [(head[i] + tail[i]) / 2.0 for i in range(3)]
    return step(part, "limb", [r0, r1, 0], mid, color, bone=bone_def,
                label=label, detail={"head": list(head), "tail": list(tail),
                                     "r0": r0, "r1": r1})


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
    H = 1.8 * scale
    style = style or ("blocky" if any(w in words for w in
                      ("robot", "android", "mech", "golem")) else "round")
    chibi = any(w in words for w in ("chibi", "cute", "toy", "baby", "doll"))
    head_scale = 1.75 if chibi else 1.0

    pal = pick_colors(words, "#4a7ab8", "#d4a017", default_skin="#d9a07a")
    body, accent, skin = pal["body"], pal["accent"], pal["skin"]
    is_machine = any(w in words for w in ("robot", "android", "mech", "golem",
                                          "skeleton"))
    if is_machine:
        skin = pal["light"]

    # joints, as a fraction of total height
    z_ankle, z_knee, z_hip = 0.045 * H, 0.28 * H, 0.53 * H
    z_waist, z_shoulder, z_neck = 0.60 * H, 0.81 * H, 0.86 * H
    x_hip, x_arm, x_shoulder = 0.075 * H, 0.13 * H, 0.04 * H
    r_arm, r_leg = 0.035 * H * bulk, 0.048 * H * bulk
    head_r = 0.075 * H * head_scale
    z_head = z_neck + head_r * 0.92

    torso = "box" if style == "blocky" else "capsule"
    solid = "box" if style == "blocky" else "sphere"

    S = []
    # 1. hips ------------------------------------------------------------
    S.append(step("hips", torso,
                  [0.10 * H * bulk, 0.066 * H * bulk, 0.058 * H],
                  [0, 0, (z_hip + z_waist) / 2],
                  body, bone=bone("hips", [0, 0, z_hip], [0, 0, z_waist]),
                  label="hips"))
    # 2. chest -----------------------------------------------------------
    S.append(step("chest", torso,
                  [0.12 * H * bulk, 0.076 * H * bulk, 0.105 * H],
                  [0, 0, (z_waist + z_shoulder) / 2],
                  body, bone=bone("spine", [0, 0, z_waist], [0, 0, z_shoulder],
                                  "hips"),
                  label="chest"))
    # 3. neck ------------------------------------------------------------
    S.append(limb("neck", [0, 0, z_shoulder], [0, 0, z_neck],
                  0.038 * H, 0.036 * H, skin,
                  bone("neck", [0, 0, z_shoulder], [0, 0, z_neck], "spine"),
                  "neck"))
    # 4. head ------------------------------------------------------------
    S.append(step("head", solid,
                  [head_r * 1.0, head_r * 0.95, head_r * 1.1],
                  [0, 0, z_head], skin,
                  bone=bone("head", [0, 0, z_neck], [0, 0, z_neck + head_r * 2],
                            "neck"),
                  label="head"))
    # 5-7. arms ----------------------------------------------------------
    S += mirrored("shoulder", [x_shoulder, 0, z_shoulder - 0.01 * H],
                  [x_arm, 0, z_shoulder - 0.02 * H],
                  r_arm * 1.25, r_arm * 1.1, body, "spine", "shoulder")
    S += mirrored("upperarm", [x_arm, 0, z_shoulder - 0.02 * H],
                  [x_arm, 0, 0.62 * H], r_arm, r_arm * 0.88, body,
                  "shoulder.X", "upper arm")
    S += mirrored("forearm", [x_arm, 0, 0.62 * H], [x_arm, 0, 0.47 * H],
                  r_arm * 0.88, r_arm * 0.72, skin, "upperarm.X", "forearm")
    S += mirrored("hand", [x_arm, 0, 0.47 * H], [x_arm, 0, 0.40 * H],
                  r_arm * 0.95, r_arm * 0.6, skin, "forearm.X", "hand")
    # 8-10. legs ---------------------------------------------------------
    S += mirrored("thigh", [x_hip, 0, z_hip], [x_hip, 0, z_knee],
                  r_leg, r_leg * 0.82, pal["dark"] if is_machine else body,
                  "hips", "thigh")
    S += mirrored("shin", [x_hip, 0, z_knee], [x_hip, 0, z_ankle],
                  r_leg * 0.82, r_leg * 0.6, pal["dark"] if is_machine else body,
                  "thigh.X", "shin")
    for side, sx in (("L", 1.0), ("R", -1.0)):
        S.append(step("foot.%s" % side, "box",
                      [r_leg * 0.95, 0.065 * H, 0.022 * H],
                      [x_hip * sx, -0.035 * H, 0.022 * H], pal["dark"],
                      bone=bone("foot.%s" % side, [x_hip * sx, 0, z_ankle],
                                [x_hip * sx, -0.09 * H, 0.02 * H],
                                "shin.%s" % side),
                      label="foot %s" % ("left" if side == "L" else "right")))

    S += humanoid_extras(extras, words, H, head_r, z_head, x_arm, pal, style,
                         is_machine)

    return S, {"rig_profile": "humanoid", "height": H, "style": style}


def humanoid_extras(extras, words, H, head_r, z_head, x_arm, pal, style,
                    is_machine):
    S = []
    body, accent, dark = pal["body"], pal["accent"], pal["dark"]
    face_y = -head_r * 0.85

    if "eyes" in extras or not is_machine:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("eye.%s" % side, "sphere",
                          [head_r * 0.17] * 3,
                          [head_r * 0.36 * sx, face_y, z_head + head_r * 0.12],
                          "#17202a", attach="head",
                          label="eye %s" % ("left" if side == "L" else "right")))
    if "ears" in extras:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("ear.%s" % side, "sphere",
                          [head_r * 0.16, head_r * 0.3, head_r * 0.32],
                          [head_r * 0.98 * sx, 0, z_head + head_r * 0.05],
                          pal["skin"], attach="head", label="ear"))
    if "beard" in extras:
        S.append(step("beard", "box",
                      [head_r * 0.7, head_r * 0.5, head_r * 0.7],
                      [0, face_y * 0.7, z_head - head_r * 0.75], "#e8e2d0",
                      attach="head", label="beard"))
    if "hat" in extras:
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
    if "horns" in extras:
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
        S.append(step("cape", "box",
                      [0.12 * H, 0.01 * H, 0.21 * H],
                      [0, 0.105 * H, 0.60 * H], accent, attach="spine",
                      label="cape"))
    if "backpack" in extras:
        S.append(step("backpack", "box",
                      [0.085 * H, 0.05 * H, 0.10 * H],
                      [0, 0.14 * H, 0.70 * H], dark, attach="spine",
                      label="backpack"))
    if "wings" in extras:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("wing.%s" % side, "box",
                          [0.15 * H, 0.008 * H, 0.11 * H],
                          [0.30 * H * sx, 0.09 * H, 0.74 * H], pal["light"],
                          rot=(0, 0, 0.25 * (1 if sx > 0 else -1)),
                          attach="spine", label="wing"))
    if "tail" in extras:
        for i in range(4):
            t = i / 3.0
            S.append(step("tail_%02d" % i, "sphere",
                          [0.035 * H * (1 - 0.45 * t)] * 3,
                          [0, 0.11 * H + 0.09 * H * i, 0.55 * H - 0.05 * H * i],
                          body, label="tail"))
    grip_x = -(x_arm + 0.035 * H)          # just outside the right hand
    grip_y = -0.045 * H                    # and a little in front of it
    if "sword" in extras:
        S.append(step("sword_grip", "cylinder",
                      [0.016 * H, 0.016 * H, 0.055 * H],
                      [grip_x, grip_y, 0.435 * H], "#5a3a22", attach="hand.R",
                      label="sword grip"))
        S.append(step("sword_guard", "box",
                      [0.048 * H, 0.012 * H, 0.010 * H],
                      [grip_x, grip_y, 0.495 * H], accent, attach="hand.R",
                      label="cross guard"))
        S.append(step("sword_blade", "box",
                      [0.016 * H, 0.005 * H, 0.185 * H],
                      [grip_x, grip_y, 0.690 * H], "#c7cdd2", attach="hand.R",
                      label="sword blade"))
        S.append(step("sword_tip", "cone",
                      [0.016 * H, 0.005 * H, 0.030 * H],
                      [grip_x, grip_y, 0.905 * H], "#c7cdd2", attach="hand.R",
                      label="sword tip"))
    if "staff" in extras:
        S.append(step("staff_shaft", "cylinder",
                      [0.013 * H, 0.013 * H, 0.40 * H],
                      [grip_x, grip_y, 0.40 * H], "#7a5230", attach="hand.R",
                      label="staff"))
        S.append(step("staff_gem", "sphere", [0.042 * H] * 3,
                      [grip_x, grip_y, 0.825 * H], "#1abc9c", attach="hand.R",
                      detail={"emissive": 1.6}, label="staff gem"))
    if "shield" in extras:
        S.append(step("shield", "cylinder",
                      [0.15 * H, 0.15 * H, 0.018 * H],
                      [(x_arm + 0.045 * H), -0.055 * H, 0.60 * H], accent,
                      rot=(1.5708, 0, 0), attach="forearm.L", label="shield"))
    return S


# --------------------------------------------------------------------------
# quadruped
# --------------------------------------------------------------------------

def build_quadruped(words, scale, bulk, style, extras):
    Hs = 0.70 * scale                      # height at the shoulder
    L = 1.20 * Hs                          # nose to tail, roughly
    style = style or "round"
    pal = pick_colors(words, "#8c6239", "#4a3524")
    body, accent, dark = pal["body"], pal["accent"], pal["dark"]

    z_back = 0.86 * Hs
    z_knee, z_ankle = 0.40 * Hs, 0.09 * Hs
    y_front, y_rear = -0.30 * L, 0.32 * L
    x_leg = 0.17 * L
    r_leg = 0.055 * L * bulk
    head_r = 0.21 * L

    torso = "box" if style == "blocky" else "capsule"
    solid = "box" if style == "blocky" else "sphere"

    S = []
    S.append(step("hips", torso,
                  [0.15 * L * bulk, 0.17 * L, 0.15 * L * bulk],
                  [0, y_rear * 0.75, z_back], body,
                  bone=bone("hips", [0, y_rear, z_back], [0, 0, z_back]),
                  label="hindquarters"))
    S.append(step("chest", torso,
                  [0.165 * L * bulk, 0.20 * L, 0.165 * L * bulk],
                  [0, y_front * 0.75, z_back], body,
                  bone=bone("spine", [0, 0, z_back], [0, y_front, z_back + 0.02 * L],
                            "hips"),
                  label="chest"))
    S.append(limb("neck", [0, y_front, z_back + 0.02 * L],
                  [0, y_front - 0.22 * L, z_back + 0.22 * L],
                  0.085 * L * bulk, 0.07 * L, body,
                  bone("neck", [0, y_front, z_back + 0.02 * L],
                       [0, y_front - 0.22 * L, z_back + 0.22 * L], "spine"),
                  "neck"))
    z_head = z_back + 0.26 * L
    y_head = y_front - 0.30 * L
    S.append(step("head", solid, [head_r * 0.9, head_r * 1.15, head_r * 0.9],
                  [0, y_head, z_head], body,
                  bone=bone("head", [0, y_front - 0.22 * L, z_back + 0.22 * L],
                            [0, y_head - 0.12 * L, z_head], "neck"),
                  label="head"))
    S.append(step("muzzle", "box",
                  [head_r * 0.40, head_r * 0.52, head_r * 0.34],
                  [0, y_head - head_r * 1.08, z_head - head_r * 0.30], pal["light"],
                  attach="head", label="muzzle"))
    S.append(step("nose", "sphere", [head_r * 0.15] * 3,
                  [0, y_head - head_r * 1.55, z_head - head_r * 0.22], "#2b2b2b",
                  attach="head", label="nose"))
    for side, sx in (("L", 1.0), ("R", -1.0)):
        S.append(step("eye.%s" % side, "sphere", [head_r * 0.14] * 3,
                      [head_r * 0.45 * sx, y_head - head_r * 0.78,
                       z_head + head_r * 0.22], "#17202a", attach="head",
                      label="eye"))
        S.append(step("ear.%s" % side, "cone",
                      [head_r * 0.32, head_r * 0.22, head_r * 0.7],
                      [head_r * 0.55 * sx, y_head + head_r * 0.2,
                       z_head + head_r * 1.0], accent, attach="head", label="ear"))

    for tag, y, parent in (("front", y_front, "spine"), ("back", y_rear, "hips")):
        for side, sx in (("L", 1.0), ("R", -1.0)):
            nm = "%sleg_%s.%s" % ("fore" if tag == "front" else "hind", "upper", side)
            top = [x_leg * sx, y, z_back - 0.06 * L]
            mid = [x_leg * sx, y, z_knee]
            low = [x_leg * sx, y, z_ankle]
            b1 = "thigh_%s.%s" % (tag, side)
            b2 = "shin_%s.%s" % (tag, side)
            S.append(limb(nm, top, mid, r_leg, r_leg * 0.78, body,
                          bone(b1, top, mid, parent), "%s leg upper" % tag))
            S.append(limb(nm.replace("upper", "lower"), mid, low,
                          r_leg * 0.78, r_leg * 0.6, body,
                          bone(b2, mid, low, b1), "%s leg lower" % tag))
            S.append(step("paw_%s.%s" % (tag, side), "box",
                          [r_leg * 0.85, 0.05 * L, 0.022 * L],
                          [x_leg * sx, y - 0.015 * L, 0.025 * L], dark,
                          bone=bone("paw_%s.%s" % (tag, side), low,
                                    [x_leg * sx, y - 0.07 * L, 0.02 * L], b2),
                          label="%s paw" % tag))

    prev = "hips"
    for i in range(4):
        t = i / 3.0
        h = [0, y_rear + 0.14 * L * i, z_back + 0.04 * L - 0.02 * L * i]
        tl = [0, y_rear + 0.14 * L * (i + 1), z_back + 0.04 * L - 0.02 * L * (i + 1)]
        nm = "tail_%02d" % i
        S.append(limb(nm, h, tl, 0.045 * L * (1 - 0.5 * t),
                      0.045 * L * (1 - 0.5 * (t + 0.33)), body,
                      bone(nm, h, tl, prev), "tail %d" % (i + 1)))
        prev = nm

    if "horns" in extras:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("horn.%s" % side, "cone",
                          [head_r * 0.2, head_r * 0.2, head_r * 0.8],
                          [head_r * 0.5 * sx, y_head, z_head + head_r * 1.3],
                          "#e8e2d0", label="horn"))
    if "wings" in extras:
        for side, sx in (("L", 1.0), ("R", -1.0)):
            S.append(step("wing.%s" % side, "box",
                          [0.21 * L, 0.17 * L, 0.01 * L],
                          [0.36 * L * sx, 0, z_back + 0.16 * L], accent,
                          rot=(0.3 * (1 if sx > 0 else -1), 0, 0), label="wing"))

    return S, {"rig_profile": "quadruped", "height": z_head + head_r,
               "style": style}


# --------------------------------------------------------------------------
# bird
# --------------------------------------------------------------------------

def build_bird(words, scale, bulk, style, extras):
    H = 0.45 * scale
    style = style or "round"
    pal = pick_colors(words, "#ecf0f1", "#e67e22")
    body, accent = pal["body"], pal["accent"]
    solid = "box" if style == "blocky" else "sphere"

    z_body = 0.55 * H
    r_body = 0.26 * H * bulk
    z_head = z_body + r_body * 1.35
    head_r = 0.16 * H

    S = [
        step("body", solid, [r_body, r_body * 1.15, r_body * 1.1],
             [0, 0, z_body], body,
             bone=bone("hips", [0, 0.1 * H, z_body], [0, -0.1 * H, z_body]),
             label="body"),
        limb("neck", [0, -0.05 * H, z_body + r_body * 0.6],
             [0, -0.06 * H, z_head - head_r * 0.6], 0.07 * H, 0.06 * H, body,
             bone("neck", [0, -0.05 * H, z_body + r_body * 0.6],
                  [0, -0.06 * H, z_head - head_r * 0.6], "hips"), "neck"),
        step("head", solid, [head_r] * 3, [0, -0.06 * H, z_head], body,
             bone=bone("head", [0, -0.06 * H, z_head - head_r * 0.6],
                       [0, -0.06 * H, z_head + head_r], "neck"), label="head"),
        step("beak", "cone", [head_r * 0.45, head_r * 0.45, head_r * 0.9],
             [0, -0.06 * H - head_r * 1.2, z_head - head_r * 0.1], accent,
             rot=(1.5708, 0, 0), attach="head", label="beak"),
    ]
    for side, sx in (("L", 1.0), ("R", -1.0)):
        S.append(step("eye.%s" % side, "sphere", [head_r * 0.16] * 3,
                      [head_r * 0.5 * sx, -0.06 * H - head_r * 0.62,
                       z_head + head_r * 0.2], "#17202a", attach="head",
                      label="eye"))
        S.append(step("wing.%s" % side, "box",
                      [0.020 * H, 0.16 * H, 0.085 * H],
                      [(r_body * 0.74) * sx, 0.02 * H, z_body + 0.01 * H], pal["light"],
                      bone=bone("wing.%s" % side,
                                [r_body * 0.8 * sx, 0, z_body + 0.08 * H],
                                [(r_body + 0.30 * H) * sx, 0, z_body + 0.02 * H],
                                "hips"),
                      label="wing"))
        S.append(limb("leg.%s" % side, [0.09 * H * sx, 0.02 * H, z_body - r_body * 0.7],
                      [0.09 * H * sx, 0.02 * H, 0.05 * H], 0.025 * H, 0.02 * H,
                      accent, bone("leg.%s" % side,
                                   [0.09 * H * sx, 0.02 * H, z_body - r_body * 0.7],
                                   [0.09 * H * sx, 0.02 * H, 0.05 * H], "hips"),
                      "leg"))
        S.append(step("foot.%s" % side, "box",
                      [0.025 * H, 0.055 * H, 0.013 * H],
                      [0.09 * H * sx, -0.02 * H, 0.015 * H], accent, label="foot"))
    S.append(step("tail", "box", [0.08 * H, 0.11 * H, 0.015 * H],
                  [0, 0.28 * H, z_body + 0.02 * H], pal["light"],
                  bone=bone("tail", [0, r_body * 0.8, z_body],
                            [0, 0.40 * H, z_body + 0.04 * H], "hips"),
                  label="tail"))
    return S, {"rig_profile": "bird", "height": z_head + head_r, "style": style}


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
    return steps, {"rig_profile": "prop", "height": top, "style": style or "round"}


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
    for i in range(6):
        a = i * 1.047
        S.append(step("stone_%02d" % i, "sphere",
                      [r * 0.18, r * 0.18, r * 0.13],
                      [_cos(a) * r, _sin(a) * r, r * 0.1], "#8b8f94",
                      label="stone %d" % (i + 1)))
    for i in range(4):
        a = i * 1.5708 + 0.4
        S.append(limb("log_%02d" % i, [_cos(a) * r * 0.6, _sin(a) * r * 0.6, 0.02 * s],
                      [-_cos(a) * r * 0.2, -_sin(a) * r * 0.2, r * 0.5],
                      0.04 * s, 0.035 * s, pal["body"], None, "log %d" % (i + 1)))
    S.append(step("flame", "cone", [r * 0.42, r * 0.42, r * 0.7],
                  [0, 0, r * 0.85], pal["accent"], detail={"emissive": 4.0},
                  bone=bone("root", [0, 0, 0], [0, 0, r * 2]), label="flame"))
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
