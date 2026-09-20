"""
Animation: prompts in, keyframes out.

Every pose in here is written the way you would describe it out loud - "swing
the right thigh forward twenty degrees" - as a rotation around a world axis.
Just before the keyframe is set, that world rotation is converted into the
bone's own local space. Doing it in that order means a pose never depends on
which way a bone happens to be rolled, which is the usual reason hand-written
rig animation comes out twisted.

Axis convention, the same as Blender's: X is right, Y is depth, Z is up, and
the model faces -Y. A positive turn about X swings a downward limb backwards,
so forward swings are written as negatives.
"""

import math
import re

try:
    import bpy
    from mathutils import Matrix, Vector
except ImportError:                       # outside Blender: the prompt reading
    bpy = Matrix = Vector = None          # and the pose maths still work

TAU = math.pi * 2
D = math.radians          # degrees to radians, used everywhere below


# --------------------------------------------------------------------------
# what the prompt is asking for
# --------------------------------------------------------------------------

MOVES = {
    "idle": ["idle", "breathe", "breathing", "stand", "standing", "still", "rest"],
    "walk": ["walk", "walking", "stroll", "march", "marching", "step"],
    "run": ["run", "running", "sprint", "sprinting", "jog", "jogging", "dash"],
    "jump": ["jump", "jumping", "leap", "hop", "bounce"],
    "wave": ["wave", "waving", "hello", "hi", "greet", "greeting", "goodbye"],
    "dance": ["dance", "dancing", "groove", "boogie", "party"],
    "attack": ["attack", "swing", "slash", "chop", "strike", "swipe"],
    "punch": ["punch", "punching", "jab", "box", "boxing"],
    "kick": ["kick", "kicking", "boot"],
    "spin": ["spin", "spinning", "turn", "rotate", "rotating", "twirl", "pirouette"],
    "nod": ["nod", "nodding", "yes", "agree"],
    "shake": ["shake", "no", "disagree", "refuse"],
    "crouch": ["crouch", "crouching", "duck", "squat", "kneel"],
    "sit": ["sit", "sitting", "seated"],
    "die": ["die", "death", "fall", "falling", "collapse", "faint", "ko"],
    "cheer": ["cheer", "celebrate", "celebration", "win", "victory", "clap"],
    "fly": ["fly", "flying", "flap", "flapping", "hover", "float", "floating"],
    "sneak": ["sneak", "sneaking", "creep", "tiptoe", "prowl"],
    "bob": ["bob", "bobbing", "pulse", "idle float", "sway"],
}

SPEED_WORDS = {"slow": 0.55, "slowly": 0.55, "sluggish": 0.45, "lazy": 0.6,
               "fast": 1.7, "quick": 1.6, "quickly": 1.6, "rapid": 1.9,
               "furious": 2.1, "frantic": 2.2, "gentle": 0.7, "calm": 0.7,
               "heavy": 0.75, "light": 1.2}

SIZE_WORDS = {"big": 1.45, "huge": 1.7, "wide": 1.4, "exaggerated": 1.8,
              "small": 0.6, "tiny": 0.5, "subtle": 0.5, "slight": 0.55,
              "tired": 0.6, "energetic": 1.5, "excited": 1.55}

# these never loop - they play once and hold
ONE_SHOT = {"jump", "attack", "punch", "kick", "die", "nod", "shake", "wave",
            "cheer", "crouch", "sit"}


def read_prompt(prompt, default="idle"):
    words = re.findall(r"[a-z]+", prompt.lower())
    move = default
    for name, synonyms in MOVES.items():
        if any(w in synonyms for w in words):
            move = name
            break
    speed = 1.0
    amount = 1.0
    for w in words:
        if w in SPEED_WORDS:
            speed = SPEED_WORDS[w]
        if w in SIZE_WORDS:
            amount = SIZE_WORDS[w]
    backwards = "backward" in words or "backwards" in words or "reverse" in words
    return {"move": move, "speed": speed, "amount": amount,
            "loop": move not in ONE_SHOT, "backwards": backwards}


# --------------------------------------------------------------------------
# posing helpers
# --------------------------------------------------------------------------

AXES = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1)}


def _world_to_local(pbone, turns):
    """`turns` is a list of (axis letter, radians) applied in armature space."""
    R = Matrix.Identity(3)
    for axis, angle in turns:
        R = Matrix.Rotation(angle, 3, Vector(AXES[axis])) @ R
    B = pbone.bone.matrix_local.to_3x3()
    return (B.inverted() @ R @ B).to_quaternion()


def _sin(p, offset=0.0):
    return math.sin(TAU * (p + offset))


def _ease(p):
    return 0.5 - 0.5 * math.cos(math.pi * min(max(p, 0.0), 1.0))


# --------------------------------------------------------------------------
# the humanoid moves - each returns {bone: [(axis, radians), ...]}
#                      plus "_root" for a whole-body offset
# --------------------------------------------------------------------------

def _h_idle(p, a):
    s = _sin(p)
    return {
        "spine": [("X", D(1.6 * a) * s)],
        "head": [("X", D(1.2 * a) * _sin(p, 0.15)), ("Z", D(2.0 * a) * _sin(p, 0.3))],
        "upperarm.L": [("Y", D(4 * a) * s)], "upperarm.R": [("Y", D(-4 * a) * s)],
        "_root": {"loc": (0, 0, 0.006 * a * s)},
    }


def _h_walk(p, a, stride=26.0, lift=1.0, lean=0.0, bounce=0.02):
    s, c = _sin(p), _sin(p, 0.25)
    knee_L = max(0.0, -_sin(p, 0.10)) * D(52 * a) * lift
    knee_R = max(0.0, -_sin(p + 0.5, 0.10)) * D(52 * a) * lift
    return {
        "hips": [("Z", D(4 * a) * c)],
        "spine": [("X", D(lean)), ("Z", D(-5 * a) * c)],
        "head": [("Z", D(3 * a) * c)],
        "thigh.L": [("X", D(-stride * a) * s)],
        "thigh.R": [("X", D(stride * a) * s)],
        "shin.L": [("X", knee_L)], "shin.R": [("X", knee_R)],
        "foot.L": [("X", D(14 * a) * _sin(p, 0.3))],
        "foot.R": [("X", D(-14 * a) * _sin(p, 0.3))],
        "upperarm.L": [("X", D(stride * 0.8 * a) * s), ("Y", D(6))],
        "upperarm.R": [("X", D(-stride * 0.8 * a) * s), ("Y", D(-6))],
        "forearm.L": [("X", D(-18 * a) * max(0.0, s))],
        "forearm.R": [("X", D(-18 * a) * max(0.0, -s))],
        "_root": {"loc": (0, 0, bounce * a * abs(_sin(p * 2)))},
    }


def _h_run(p, a):
    pose = _h_walk(p, a, stride=44.0, lift=1.5, lean=14.0, bounce=0.05)
    pose["forearm.L"] = [("X", D(-75 * a))]
    pose["forearm.R"] = [("X", D(-75 * a))]
    return pose


def _h_sneak(p, a):
    pose = _h_walk(p, a * 0.6, stride=18.0, lift=1.2, lean=22.0, bounce=0.005)
    pose["thigh.L"] += [("X", D(24))]
    pose["thigh.R"] += [("X", D(24))]
    pose["shin.L"] += [("X", D(34))]
    pose["shin.R"] += [("X", D(34))]
    pose["_root"] = {"loc": (0, 0, -0.10 * a)}
    return pose


def _h_jump(p, a):
    # crouch, drive, tuck in the air, absorb the landing
    crouch = _ease(min(p / 0.22, 1.0)) * (1 - _ease(max(0.0, (p - 0.22) / 0.14)))
    air = _ease(max(0.0, (p - 0.30) / 0.22)) * (1 - _ease(max(0.0, (p - 0.66) / 0.20)))
    land = _ease(max(0.0, (p - 0.80) / 0.20))
    dip = (crouch + land) * a
    return {
        "hips": [("X", D(14 * dip))],
        "spine": [("X", D(16 * dip - 8 * air))],
        "thigh.L": [("X", D(48 * dip + 55 * air))],
        "thigh.R": [("X", D(48 * dip + 55 * air))],
        "shin.L": [("X", D(-62 * dip - 70 * air))],
        "shin.R": [("X", D(-62 * dip - 70 * air))],
        "foot.L": [("X", D(20 * dip - 25 * air))],
        "foot.R": [("X", D(20 * dip - 25 * air))],
        "upperarm.L": [("X", D(30 * dip - 150 * air)), ("Y", D(10))],
        "upperarm.R": [("X", D(30 * dip - 150 * air)), ("Y", D(-10))],
        "_root": {"loc": (0, 0, -0.16 * dip + 0.75 * a * air)},
    }


def _h_wave(p, a):
    raise_amt = _ease(min(p / 0.2, 1.0)) * (1 - _ease(max(0.0, (p - 0.78) / 0.22)))
    flap = _sin(p * 4) * raise_amt
    return {
        "spine": [("Z", D(-4 * raise_amt))],
        "head": [("Z", D(-6 * raise_amt))],
        "upperarm.R": [("Y", D(-140 * raise_amt * a)), ("X", D(-12 * raise_amt))],
        "forearm.R": [("Y", D(-25 * raise_amt)), ("X", D(-18 * raise_amt))],
        "hand.R": [("X", D(30 * flap * a))],
        "upperarm.L": [("Y", D(6))],
    }


def _h_cheer(p, a):
    up = _ease(min(p / 0.25, 1.0))
    pump = abs(_sin(p * 3)) * up
    return {
        "spine": [("X", D(-8 * up))],
        "head": [("X", D(-14 * up))],
        "upperarm.L": [("Y", D(158 * up * a)), ("X", D(-20 * pump))],
        "upperarm.R": [("Y", D(-158 * up * a)), ("X", D(-20 * pump))],
        "forearm.L": [("X", D(-30 * pump))], "forearm.R": [("X", D(-30 * pump))],
        "_root": {"loc": (0, 0, 0.09 * a * pump)},
    }


def _h_dance(p, a):
    s, c = _sin(p), _sin(p, 0.25)
    return {
        "hips": [("Z", D(16 * a) * s), ("Y", D(9 * a) * c)],
        "spine": [("Z", D(-12 * a) * s), ("X", D(5 * a) * c)],
        "head": [("Z", D(10 * a) * s), ("X", D(7 * a) * _sin(p * 2))],
        "upperarm.L": [("Y", D(85 + 45 * a * s)), ("X", D(-20 * a) * c)],
        "upperarm.R": [("Y", D(-85 - 45 * a * c)), ("X", D(-20 * a) * s)],
        "forearm.L": [("X", D(-55 - 25 * a * s))],
        "forearm.R": [("X", D(-55 - 25 * a * c))],
        "thigh.L": [("X", D(-10 * a) * c)], "thigh.R": [("X", D(10 * a) * c)],
        "_root": {"loc": (0, 0, 0.05 * a * abs(_sin(p * 2))),
                  "rot": [("Z", D(7 * a) * s)]},
    }


def _h_attack(p, a):
    wind = _ease(min(p / 0.32, 1.0)) * (1 - _ease(max(0.0, (p - 0.32) / 0.14)))
    hit = _ease(max(0.0, (p - 0.36) / 0.18)) * (1 - _ease(max(0.0, (p - 0.70) / 0.30)))
    return {
        "hips": [("Z", D(18 * wind - 22 * hit))],
        "spine": [("Z", D(26 * wind - 34 * hit)), ("X", D(-6 * wind + 12 * hit))],
        "head": [("Z", D(-8 * wind + 10 * hit))],
        "upperarm.R": [("Y", D(-120 * wind - 20 * hit)), ("X", D(40 * wind - 70 * hit))],
        "forearm.R": [("X", D(-70 * wind + 10 * hit))],
        "upperarm.L": [("Y", D(18)), ("X", D(-20 * hit))],
        "thigh.L": [("X", D(-16 * hit))], "thigh.R": [("X", D(14 * hit))],
        "_root": {"rot": [("Z", D(-10 * a * hit))]},
    }


def _h_punch(p, a):
    left = p < 0.5
    q = (p / 0.5) if left else ((p - 0.5) / 0.5)
    out = _ease(min(q / 0.35, 1.0)) * (1 - _ease(max(0.0, (q - 0.45) / 0.45)))
    near, far = ("L", "R") if left else ("R", "L")
    sign = 1 if near == "L" else -1
    return {
        "spine": [("Z", D(-16 * sign * out * a))],
        "hips": [("Z", D(-9 * sign * out))],
        "upperarm." + near: [("X", D(-88 * out * a)), ("Y", D(14 * sign))],
        "forearm." + near: [("X", D(-8 * out))],
        "upperarm." + far: [("X", D(-25)), ("Y", D(20 * sign * -1))],
        "forearm." + far: [("X", D(-95))],
        "head": [("Z", D(-5 * sign * out))],
    }


def _h_kick(p, a):
    out = _ease(min(p / 0.34, 1.0)) * (1 - _ease(max(0.0, (p - 0.46) / 0.44)))
    return {
        "hips": [("X", D(16 * out))],
        "spine": [("X", D(22 * out * a))],
        "thigh.R": [("X", D(-95 * out * a))],
        "shin.R": [("X", D(-30 * out + 45 * (1 - out) * out * 4))],
        "thigh.L": [("X", D(12 * out))],
        "upperarm.L": [("X", D(-50 * out)), ("Y", D(20))],
        "upperarm.R": [("X", D(45 * out)), ("Y", D(-20))],
        "_root": {"loc": (0, 0, -0.03 * out)},
    }


def _h_nod(p, a):
    return {"head": [("X", D(19 * a) * _sin(p * 2))],
            "neck": [("X", D(7 * a) * _sin(p * 2))]}


def _h_shake(p, a):
    return {"head": [("Z", D(26 * a) * _sin(p * 2))],
            "neck": [("Z", D(8 * a) * _sin(p * 2))]}


def _h_crouch(p, a):
    k = _ease(min(p / 0.45, 1.0))
    return {
        "hips": [("X", D(22 * k * a))],
        "spine": [("X", D(18 * k * a))],
        "head": [("X", D(-16 * k))],
        "thigh.L": [("X", D(76 * k * a))], "thigh.R": [("X", D(76 * k * a))],
        "shin.L": [("X", D(-88 * k * a))], "shin.R": [("X", D(-88 * k * a))],
        "foot.L": [("X", D(24 * k))], "foot.R": [("X", D(24 * k))],
        "upperarm.L": [("X", D(-28 * k)), ("Y", D(12))],
        "upperarm.R": [("X", D(-28 * k)), ("Y", D(-12))],
        "_root": {"loc": (0, 0, -0.30 * k * a)},
    }


def _h_sit(p, a):
    k = _ease(min(p / 0.5, 1.0))
    return {
        "hips": [("X", D(-6 * k))],
        "thigh.L": [("X", D(88 * k))], "thigh.R": [("X", D(88 * k))],
        "shin.L": [("X", D(-88 * k))], "shin.R": [("X", D(-88 * k))],
        "upperarm.L": [("X", D(-16 * k)), ("Y", D(10))],
        "upperarm.R": [("X", D(-16 * k)), ("Y", D(-10))],
        "_root": {"loc": (0, 0, -0.44 * k)},
    }


def _h_die(p, a):
    k = _ease(min(p / 0.75, 1.0))
    stagger = _sin(p * 3) * (1 - k) * 0.4
    return {
        "hips": [("X", D(-8 * k))],
        "spine": [("X", D(-30 * k + 12 * stagger)), ("Z", D(18 * k))],
        "head": [("X", D(34 * k)), ("Z", D(-14 * k))],
        "upperarm.L": [("Y", D(40 * k)), ("X", D(20 * k))],
        "upperarm.R": [("Y", D(-30 * k)), ("X", D(25 * k))],
        "thigh.L": [("X", D(28 * k))], "thigh.R": [("X", D(12 * k))],
        "shin.L": [("X", D(-40 * k))],
        "_root": {"loc": (0, 0.12 * k, -0.72 * k),
                  "rot": [("X", D(-82 * k))]},
    }


def _h_fly(p, a):
    flap = _sin(p)
    return {
        "spine": [("X", D(-46))],
        "head": [("X", D(38))],
        "upperarm.L": [("Y", D(88 + 34 * a * flap)), ("X", D(-12))],
        "upperarm.R": [("Y", D(-88 - 34 * a * flap)), ("X", D(-12))],
        "thigh.L": [("X", D(34))], "thigh.R": [("X", D(34))],
        "shin.L": [("X", D(-26))], "shin.R": [("X", D(-26))],
        "_root": {"loc": (0, 0, 0.30 + 0.07 * a * flap)},
    }


def _h_spin(p, a):
    return {"_root": {"rot": [("Z", TAU * p)],
                      "loc": (0, 0, 0.02 * abs(_sin(p * 2)))},
            "upperarm.L": [("Y", D(62 * a))], "upperarm.R": [("Y", D(-62 * a))]}


HUMANOID = {
    "idle": _h_idle, "walk": _h_walk, "run": _h_run, "sneak": _h_sneak,
    "jump": _h_jump, "wave": _h_wave, "cheer": _h_cheer, "dance": _h_dance,
    "attack": _h_attack, "punch": _h_punch, "kick": _h_kick, "nod": _h_nod,
    "shake": _h_shake, "crouch": _h_crouch, "sit": _h_sit, "die": _h_die,
    "fly": _h_fly, "spin": _h_spin, "bob": _h_idle,
}


# --------------------------------------------------------------------------
# quadruped
# --------------------------------------------------------------------------

def _q_tail(p, a, amp=16.0, speed=1.0):
    return {"tail_%02d" % i: [("Z", D(amp * a / (i + 1)) * _sin(p * speed, -0.12 * i))]
            for i in range(4)}


def _q_idle(p, a):
    out = {"spine": [("X", D(1.2 * a) * _sin(p))],
           "neck": [("X", D(2.0 * a) * _sin(p, 0.2))],
           "head": [("Z", D(3.0 * a) * _sin(p, 0.35))]}
    out.update(_q_tail(p, a, 10.0))
    return out


def _q_walk(p, a, stride=24.0, lift=1.0, bounce=0.012):
    # diagonal pairs, the way a dog actually walks
    pairs = {"front.L": 0.0, "back.R": 0.05, "front.R": 0.5, "back.L": 0.55}
    out = {"spine": [("Z", D(3 * a) * _sin(p, 0.25))],
           "neck": [("X", D(-3 * a) * _sin(p * 2))],
           "head": [("X", D(4 * a) * _sin(p * 2, 0.1))]}
    for leg, phase in pairs.items():
        tag, side = leg.split(".")
        s = _sin(p, phase)
        bend = max(0.0, -_sin(p, phase + 0.12)) * D(38 * a) * lift
        out["thigh_%s.%s" % (tag, side)] = [("X", D(-stride * a) * s)]
        out["shin_%s.%s" % (tag, side)] = [("X", bend)]
        out["paw_%s.%s" % (tag, side)] = [("X", D(12 * a) * _sin(p, phase + 0.3))]
    out.update(_q_tail(p, a, 14.0))
    out["_root"] = {"loc": (0, 0, bounce * a * abs(_sin(p * 2)))}
    return out


def _q_run(p, a):
    out = _q_walk(p, a, stride=42.0, lift=1.6, bounce=0.05)
    # in a gallop the front pair and the back pair move together, not diagonally
    for tag, phase in (("front", 0.0), ("back", 0.42)):
        for side in ("L", "R"):
            s = _sin(p, phase)
            out["thigh_%s.%s" % (tag, side)] = [("X", D(-46 * a) * s)]
            out["shin_%s.%s" % (tag, side)] = [
                ("X", max(0.0, -_sin(p, phase + 0.15)) * D(60 * a))]
    out["spine"] = [("X", D(9 * a) * _sin(p * 2))]
    out["_root"] = {"loc": (0, 0, 0.06 * a * max(0.0, _sin(p * 2)))}
    return out


def _q_jump(p, a):
    k = _ease(min(p / 0.25, 1.0)) * (1 - _ease(max(0.0, (p - 0.55) / 0.45)))
    air = _ease(max(0.0, (p - 0.25) / 0.25)) * (1 - _ease(max(0.0, (p - 0.65) / 0.3)))
    out = {"spine": [("X", D(-14 * air + 10 * k))]}
    for tag in ("front", "back"):
        for side in ("L", "R"):
            out["thigh_%s.%s" % (tag, side)] = [("X", D(40 * k - 46 * air))]
            out["shin_%s.%s" % (tag, side)] = [("X", D(-50 * k + 30 * air))]
    out.update(_q_tail(p, a, 20.0))
    out["_root"] = {"loc": (0, 0, 0.55 * a * air - 0.10 * k)}
    return out


def _q_sit(p, a):
    k = _ease(min(p / 0.5, 1.0))
    out = {"spine": [("X", D(-26 * k))], "neck": [("X", D(18 * k))],
           "hips": [("X", D(-30 * k))]}
    for side in ("L", "R"):
        out["thigh_back.%s" % side] = [("X", D(74 * k))]
        out["shin_back.%s" % side] = [("X", D(-80 * k))]
    out.update(_q_tail(p, a, 12.0))
    out["_root"] = {"loc": (0, 0, -0.22 * k), "rot": [("X", D(-14 * k))]}
    return out


def _q_die(p, a):
    k = _ease(min(p / 0.8, 1.0))
    return {"spine": [("Z", D(20 * k))], "neck": [("X", D(30 * k))],
            "_root": {"loc": (0, 0, -0.30 * k), "rot": [("Y", D(84 * k))]}}


QUADRUPED = {
    "idle": _q_idle, "walk": _q_walk, "run": _q_run, "sneak":
        lambda p, a: _q_walk(p, a * 0.6, stride=16.0, bounce=0.004),
    "jump": _q_jump, "sit": _q_sit, "crouch": _q_sit, "die": _q_die,
    "wave": lambda p, a: dict(_q_tail(p, a, 34.0, 2.0),
                              head=[("Z", D(12 * a) * _sin(p * 2))]),
    "dance": lambda p, a: dict(_q_tail(p, a, 30.0, 2.0),
                               spine=[("Z", D(14 * a) * _sin(p))],
                               head=[("X", D(12 * a) * _sin(p * 2))],
                               _root={"loc": (0, 0, 0.04 * a * abs(_sin(p * 2)))}),
    "nod": lambda p, a: {"head": [("X", D(18 * a) * _sin(p * 2))]},
    "shake": lambda p, a: {"head": [("Z", D(24 * a) * _sin(p * 2))]},
    "spin": lambda p, a: {"_root": {"rot": [("Z", TAU * p)]}},
    "attack": lambda p, a: {"neck": [("X", D(-26 * a) * _ease(min(p / 0.3, 1.0)))],
                            "head": [("X", D(-30 * a) * _ease(min(p / 0.3, 1.0)))]},
    "cheer": lambda p, a: _q_jump(p, a),
    "bob": _q_idle, "fly": _q_jump, "punch": _q_jump, "kick": _q_jump,
}


# --------------------------------------------------------------------------
# bird
# --------------------------------------------------------------------------

def _b_flap(p, a, amp=52.0):
    f = _sin(p)
    return {"wing.L": [("Y", D(-amp * a) * f)], "wing.R": [("Y", D(amp * a) * f)]}


def _b_idle(p, a):
    out = _b_flap(p, a * 0.12, 20.0)
    out.update({"neck": [("X", D(3 * a) * _sin(p, 0.2))],
                "head": [("Z", D(7 * a) * _sin(p, 0.4))],
                "tail": [("X", D(4 * a) * _sin(p))]})
    return out


def _b_fly(p, a):
    out = _b_flap(p, a, 58.0)
    out.update({"neck": [("X", D(10))], "tail": [("X", D(-12))],
                "leg.L": [("X", D(38))], "leg.R": [("X", D(38))],
                "_root": {"loc": (0, 0, 0.22 + 0.06 * a * _sin(p, 0.25))}})
    return out


def _b_walk(p, a):
    return {"leg.L": [("X", D(-26 * a) * _sin(p))],
            "leg.R": [("X", D(26 * a) * _sin(p))],
            "neck": [("X", D(6 * a) * _sin(p * 2))],
            "head": [("X", D(-10 * a) * _sin(p * 2, 0.15))],
            "tail": [("X", D(5 * a) * _sin(p))],
            "_root": {"loc": (0, 0, 0.01 * a * abs(_sin(p * 2)))}}


def _b_hop(p, a):
    air = _ease(max(0.0, (p - 0.2) / 0.3)) * (1 - _ease(max(0.0, (p - 0.6) / 0.4)))
    out = _b_flap(p, a * 0.6, 40.0)
    out.update({"leg.L": [("X", D(42 * air))], "leg.R": [("X", D(42 * air))],
                "_root": {"loc": (0, 0, 0.18 * a * air)}})
    return out


BIRD = {
    "idle": _b_idle, "fly": _b_fly, "walk": _b_walk, "run": _b_walk,
    "jump": _b_hop, "sneak": _b_walk, "bob": _b_idle,
    "wave": lambda p, a: _b_flap(p, a, 60.0),
    "dance": lambda p, a: dict(_b_flap(p, a, 44.0),
                               head=[("Z", D(16 * a) * _sin(p))],
                               tail=[("X", D(12 * a) * _sin(p * 2))],
                               _root={"loc": (0, 0, 0.03 * a * abs(_sin(p * 2)))}),
    "nod": lambda p, a: {"head": [("X", D(22 * a) * _sin(p * 2))]},
    "shake": lambda p, a: {"head": [("Z", D(28 * a) * _sin(p * 2))]},
    "attack": lambda p, a: {"neck": [("X", D(-34 * a) * _ease(min(p / 0.25, 1.0)))],
                            "head": [("X", D(-26 * a) * _ease(min(p / 0.25, 1.0)))]},
    "spin": lambda p, a: {"_root": {"rot": [("Z", TAU * p)]}},
    "die": lambda p, a: {"_root": {"loc": (0, 0, -0.10 * _ease(p)),
                                   "rot": [("Y", D(88 * _ease(p)))]}},
    "sit": lambda p, a: {"_root": {"loc": (0, 0, -0.06 * _ease(p))},
                         "leg.L": [("X", D(50 * _ease(p)))],
                         "leg.R": [("X", D(50 * _ease(p)))]},
    "crouch": lambda p, a: {"_root": {"loc": (0, 0, -0.05 * _ease(p))}},
    "cheer": lambda p, a: _b_flap(p, a, 66.0), "punch": _b_hop, "kick": _b_hop,
}


# --------------------------------------------------------------------------
# props - one root bone, sometimes a chain
# --------------------------------------------------------------------------

def _prop(p, a, move):
    if move == "spin":
        return {"_root": {"rot": [("Z", TAU * p)]}}
    if move in ("jump", "bob", "idle", "fly"):
        h = 0.10 if move in ("jump", "fly") else 0.03
        return {"_root": {"loc": (0, 0, h * a * (0.5 - 0.5 * math.cos(TAU * p))),
                          "rot": [("Z", D(9 * a) * _sin(p, 0.25))]}}
    if move in ("die", "attack"):
        k = _ease(min(p / 0.7, 1.0))
        return {"_root": {"rot": [("Y", D(88 * k))], "loc": (0, 0, -0.04 * k)}}
    if move in ("dance", "wave", "cheer", "shake"):
        return {"_root": {"rot": [("Y", D(20 * a) * _sin(p)),
                                  ("X", D(12 * a) * _sin(p, 0.25))],
                          "loc": (0, 0, 0.03 * a * abs(_sin(p * 2)))}}
    if move in ("nod",):
        return {"_root": {"rot": [("X", D(18 * a) * _sin(p * 2))]}}
    # walk, run, sneak, crouch, sit, punch, kick all become a tip and a rock
    return {"_root": {"rot": [("X", D(11 * a) * _sin(p))],
                      "loc": (0, 0, 0.02 * a * abs(_sin(p * 2)))}}


PROP = {name: (lambda m: (lambda p, a: _prop(p, a, m)))(name) for name in MOVES}

PROFILES = {"humanoid": HUMANOID, "quadruped": QUADRUPED, "bird": BIRD,
            "prop": PROP, "generic": PROP}

BASE_FRAMES = {
    "idle": 96, "walk": 32, "run": 22, "sneak": 46, "jump": 46, "wave": 64,
    "cheer": 60, "dance": 44, "attack": 40, "punch": 44, "kick": 42, "nod": 44,
    "shake": 44, "crouch": 44, "sit": 54, "die": 74, "fly": 26, "spin": 60,
    "bob": 64,
}


# --------------------------------------------------------------------------
# turning a move into real keyframes
# --------------------------------------------------------------------------

def _root_bone(arm_obj):
    for pb in arm_obj.pose.bones:
        if pb.bone.parent is None:
            return pb
    return None


def bake(arm_obj, profile, move, speed=1.0, amount=1.0, loop=True, fps=30):
    table = PROFILES.get(profile) or PROP
    poser = table.get(move) or PROP.get(move) or PROP["idle"]
    frames = max(8, int(round(BASE_FRAMES.get(move, 40) / max(speed, 0.15))))

    scene = bpy.context.scene
    scene.render.fps = fps
    arm_obj.animation_data_clear()
    arm_obj.animation_data_create()
    action = bpy.data.actions.new("%s_%s" % (profile, move))
    arm_obj.animation_data.action = action

    for pb in arm_obj.pose.bones:
        pb.rotation_mode = "QUATERNION"

    have = {pb.name: pb for pb in arm_obj.pose.bones}
    root = _root_bone(arm_obj)

    # which channels this move touches, so every key is written on every frame
    touched = set()
    samples = []
    total = frames if loop else max(frames - 1, 1)
    for f in range(frames + (1 if loop else 0)):
        p = (f % frames) / float(frames) if loop else f / float(total)
        pose = poser(p, amount) or {}
        samples.append(pose)
        touched.update(k for k in pose if k != "_root")
    touched = [n for n in touched if n in have]

    for f, pose in enumerate(samples):
        frame = f + 1
        root_info = pose.get("_root") or {}
        for name in touched:
            pb = have[name]
            turns = list(pose.get(name) or [])
            if root and pb is root and root_info.get("rot"):
                turns = list(root_info["rot"]) + turns
            pb.rotation_quaternion = _world_to_local(pb, turns)
            pb.keyframe_insert("rotation_quaternion", frame=frame)

        if root:
            if root.name not in touched and root_info.get("rot"):
                root.rotation_quaternion = _world_to_local(root, root_info["rot"])
                root.keyframe_insert("rotation_quaternion", frame=frame)
            offset = Vector(root_info.get("loc") or (0, 0, 0))
            local = root.bone.matrix_local.to_3x3().inverted() @ offset
            root.location = local
            root.keyframe_insert("location", frame=frame)

    scene.frame_start = 1
    scene.frame_end = frames + (1 if loop else 0)
    scene.frame_set(1)
    return {"move": move, "frames": scene.frame_end, "fps": fps, "loop": loop,
            "bones": sorted(touched), "action": action.name}


def clear_pose(arm_obj):
    arm_obj.animation_data_clear()
    for pb in arm_obj.pose.bones:
        pb.rotation_mode = "QUATERNION"
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = 1


# --------------------------------------------------------------------------
# borrowed motion: an .fbx dropped in the animations folder
# --------------------------------------------------------------------------

# Mixamo is the common case, so its names are translated to boneka's
SOURCE_NAMES = {
    "hips": "hips", "spine": "spine", "spine1": "spine", "spine2": "spine",
    "neck": "neck", "head": "head",
    "leftshoulder": "shoulder.L", "leftarm": "upperarm.L",
    "leftforearm": "forearm.L", "lefthand": "hand.L",
    "rightshoulder": "shoulder.R", "rightarm": "upperarm.R",
    "rightforearm": "forearm.R", "righthand": "hand.R",
    "leftupleg": "thigh.L", "leftleg": "shin.L", "leftfoot": "foot.L",
    "rightupleg": "thigh.R", "rightleg": "shin.R", "rightfoot": "foot.R",
    # some rigs use plainer names
    "upperarm_l": "upperarm.L", "lowerarm_l": "forearm.L", "hand_l": "hand.L",
    "upperarm_r": "upperarm.R", "lowerarm_r": "forearm.R", "hand_r": "hand.R",
    "thigh_l": "thigh.L", "calf_l": "shin.L", "foot_l": "foot.L",
    "thigh_r": "thigh.R", "calf_r": "shin.R", "foot_r": "foot.R",
    "pelvis": "hips", "chest": "spine", "neck_01": "neck", "head_01": "head",
}

# boneka's own bone names, so a clip exported from boneka can be read back in
for _side in ("l", "r"):
    for _part in ("shoulder", "upperarm", "forearm", "hand", "thigh", "shin",
                  "foot"):
        SOURCE_NAMES["%s.%s" % (_part, _side)] = "%s.%s" % (_part, _side.upper())
for _part in ("hips", "spine", "neck", "head"):
    SOURCE_NAMES[_part] = _part


def _normalise(name):
    n = name.lower()
    for prefix in ("mixamorig:", "mixamorig", "armature|", "bip01_", "bip01",
                   "root|"):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return n.strip(" _:.")


def import_clip(path, target_arm, target_profile="humanoid", fps=30):
    """
    Bring the motion out of an .fbx and put it on our own rig.

    Each source bone's turn is read in the source rig's own space and then
    written into our bone's space, so the two rigs do not have to agree on
    rest pose, bone length or roll - only on which bone is which.
    """
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=True,
                             ignore_leaf_bones=True)
    imported = [o for o in bpy.context.scene.objects if o not in before]
    source = next((o for o in imported if o.type == "ARMATURE"), None)
    if source is None:
        for o in imported:
            bpy.data.objects.remove(o, do_unlink=True)
        raise RuntimeError("that file has no skeleton in it")

    action = source.animation_data.action if source.animation_data else None
    if action is None:
        for o in imported:
            bpy.data.objects.remove(o, do_unlink=True)
        raise RuntimeError("that file has a skeleton but no animation on it")

    clip_name = action.name.split("|")[-1].strip() or action.name
    start, end = (int(round(v)) for v in action.frame_range)
    frames = max(1, end - start + 1)

    pairs = []
    for spb in source.pose.bones:
        target_name = SOURCE_NAMES.get(_normalise(spb.name))
        if target_name and target_name in target_arm.pose.bones:
            pairs.append((spb, target_arm.pose.bones[target_name]))
    if not pairs:
        names = ", ".join(sorted({_normalise(b.name) for b in source.pose.bones})[:8])
        for o in imported:
            bpy.data.objects.remove(o, do_unlink=True)
        raise RuntimeError("none of that rig's bones match ours (it has: %s ...)" % names)

    src_height = max(1e-4, source.dimensions.z)
    tgt_height = max(1e-4, sum(b.bone.length for b in target_arm.pose.bones if
                               b.bone.parent is None) or 1.0)

    target_arm.animation_data_clear()
    target_arm.animation_data_create()
    new_action = bpy.data.actions.new("imported_" + clip_name)
    target_arm.animation_data.action = new_action
    for pb in target_arm.pose.bones:
        pb.rotation_mode = "QUATERNION"

    root = _root_bone(target_arm)
    src_root = next((s for s, t in pairs if t is root), None)
    scene = bpy.context.scene
    base_loc = None

    for i in range(frames):
        scene.frame_set(start + i)
        for spb, tpb in pairs:
            rest_s = spb.bone.matrix_local.to_3x3()
            local_s = (spb.bone.matrix_local.inverted() @ spb.matrix).to_3x3()
            world = rest_s @ local_s @ rest_s.inverted()
            rest_t = tpb.bone.matrix_local.to_3x3()
            tpb.rotation_quaternion = (rest_t.inverted() @ world @ rest_t).to_quaternion()
            tpb.keyframe_insert("rotation_quaternion", frame=i + 1)
        if root is not None and src_root is not None:
            world_loc = (src_root.matrix.translation -
                         src_root.bone.matrix_local.translation)
            if base_loc is None:
                base_loc = world_loc.copy()
            delta = (world_loc - base_loc) * (tgt_height / src_height)
            root.location = root.bone.matrix_local.to_3x3().inverted() @ delta
            root.keyframe_insert("location", frame=i + 1)

    for o in imported:
        bpy.data.objects.remove(o, do_unlink=True)

    scene.frame_start = 1
    scene.frame_end = frames
    scene.frame_set(1)
    scene.render.fps = fps
    return {"move": clip_name, "frames": frames, "fps": fps, "loop": True,
            "bones": sorted({t.name for _, t in pairs}), "mapped": len(pairs),
            "action": new_action.name}
