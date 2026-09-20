#!/usr/bin/env python3
"""
boneka's checks.

Runs the real Blender worker the same way the app does and looks at what comes
back, rather than testing the pieces in isolation. Two parts:

  * the parser, which needs no Blender at all
  * the worker, driven end to end - build, rig, animate, export - over a wide
    spread of prompts, because the failures that matter are the ones where one
    particular recipe makes a shape the rigger cannot handle

    python3 tests/check.py          everything
    python3 tests/check.py --quick  parser plus a handful of models
"""

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "blender"))
BLENDER = os.environ.get(
    "BONEKA_BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
MARK = "@@BK@@"

PASS, FAIL = [], []


def check(name, condition, detail=""):
    (PASS if condition else FAIL).append(name)
    if not condition:
        print("  FAIL  %s%s" % (name, ("  - " + detail) if detail else ""))
    return condition


# --------------------------------------------------------------------------
# the parser, on its own
# --------------------------------------------------------------------------

def check_parser():
    import anim
    import recipes
    print("\nthe parser")

    cases = [
        ("a tall blue knight with a sword", "humanoid", ["sword"]),
        ("a chunky red robot with an antenna", "humanoid", ["antenna"]),
        ("a brown dog with a tail", "quadruped", ["tail"]),
        ("a small white chicken", "bird", []),
        ("a pine tree", "prop", []),
        ("a treasure chest", "prop", []),
        ("", "humanoid", []),
    ]
    for prompt, archetype, extras in cases:
        plan = recipes.plan_from_prompt(prompt)
        check("reads %r as a %s" % (prompt or "(nothing)", archetype),
              plan["archetype"] == archetype, plan["archetype"])
        for extra in extras:
            check("  finds the %s" % extra, extra in plan["extras"])

    plan = recipes.plan_from_prompt("a tall knight")
    short = recipes.plan_from_prompt("a short knight")
    check("tall is taller than short", plan["height"] > short["height"],
          "%s vs %s" % (plan["height"], short["height"]))

    plan = recipes.plan_from_prompt("a green wizard")
    check("colour words reach the model",
          any(s["color"] == recipes.COLORS["green"] for s in plan["steps"]))

    # every prop in the library must produce something standing on the ground
    for prop in sorted(recipes.PROPS):
        plan = recipes.plan_from_prompt("a %s" % prop)
        ok = bool(plan["steps"]) and plan["height"] > 0
        low = min(s["loc"][2] - s["size"][2] for s in plan["steps"])
        check("prop %s builds" % prop, ok, "no steps")
        check("prop %s sits on the floor" % prop, low > -0.06,
              "lowest point %.3f" % low)

    # no part may be placed below the floor on a creature either
    for prompt in ("a knight", "a dog", "a chicken"):
        plan = recipes.plan_from_prompt(prompt)
        low = min(s["loc"][2] - abs(s["size"][2]) for s in plan["steps"]
                  if s["shape"] != "limb")
        check("%s stands on the floor" % prompt, low > -0.06, "%.3f" % low)

    # every bone's parent must exist, or the armature cannot be built
    for prompt in ("a knight with a sword", "a dog", "a chicken", "a flag",
                   "a pine tree", "a snowman"):
        plan = recipes.plan_from_prompt(prompt)
        names = {s["bone"]["name"] for s in plan["steps"] if s["bone"]}
        orphans = [s["bone"]["name"] for s in plan["steps"] if s["bone"]
                   and s["bone"]["parent"] and s["bone"]["parent"] not in names]
        check("%s has no orphan bones" % prompt, not orphans, str(orphans))
        attached = {s["attach"] for s in plan["steps"] if s.get("attach")}
        missing = sorted(attached - names)
        check("%s attaches only to real bones" % prompt, not missing, str(missing))

    # the subject is what the reference lookup searches for, so it has to be
    # the thing the prompt is about rather than the last noun in it
    for prompt, subject in [("a tall blue knight with a sword", "knight"),
                            ("a brown dog with a tail", "dog"),
                            ("a small white chicken", "chicken"),
                            ("a pine tree", "tree"),
                            ("a treasure chest", "chest")]:
        plan = recipes.plan_from_prompt(prompt)
        check("%r is about a %s" % (prompt, subject),
              plan["subject"] == subject, plan["subject"])

    # what gets sculpted and what keeps its corners
    for prompt, organic in [("a knight", True), ("a dog", True),
                            ("a chicken", True), ("an oak tree", True),
                            ("a crate", False), ("a table", False),
                            ("a sword", False), ("a blocky green golem", False),
                            ("a voxel knight", False)]:
        plan = recipes.plan_from_prompt(prompt)
        check("%r is %s" % (prompt, "sculpted" if organic else "left crisp"),
              plan["organic"] == organic, str(plan["organic"]))

    plan = recipes.plan_from_prompt("a knight with a sword and a hat")
    soft = {s["part"] for s in plan["steps"] if not s["hard"]}
    check("the body is sculpted", "chest" in soft and "upperarm.L" in soft)
    for accessory in ("sword_blade", "eye.L", "hat"):
        check("the %s keeps its own shape" % accessory, accessory not in soft)

    # proportion, against the references the recipes were written from
    plan = recipes.plan_from_prompt("a knight")
    head = next(s for s in plan["steps"] if s["part"] == "head")
    head_height = head["size"][2] * 2
    ratio = plan["height"] / head_height
    check("the figure is eight heads tall", 7.4 <= ratio <= 8.6,
          "%.2f heads" % ratio)

    dog = recipes.plan_from_prompt("a dog")
    ys = [s["loc"][1] for s in dog["steps"]]
    length = max(ys) - min(ys)
    check("the dog is longer than it is tall", length > dog["height"] * 0.55,
          "%.2f long, %.2f tall" % (length, dog["height"]))

    bird = recipes.plan_from_prompt("a chicken")
    body = next(s for s in bird["steps"] if s["part"] == "body")
    check("the chicken's body is longer than it is wide",
          body["size"][1] > body["size"][0] * 1.4,
          "%.3f deep, %.3f wide" % (body["size"][1], body["size"][0]))

    # a character is assembled from named pieces, not carved as one lump
    unknown = sorted({m for kit in recipes.KITS.values() for m in kit
                      if m not in recipes.MODULES})
    check("every kit names modules that exist", not unknown, str(unknown))

    for prompt, wanted in [
            ("a knight", ["helmet", "breastplate", "pauldron", "greave",
                          "gauntlet", "belt", "tassets", "boot"]),
            ("a wizard", ["robe", "hat", "belt"]),
            ("a pirate", ["coat", "hat", "belt", "boot"]),
            ("a farmer", ["tunic", "trouser", "hat", "boot"]),
            ("a ninja", ["hood", "mask", "tunic", "belt"]),
            ("a king", ["robe", "crown"]),
            ("a chef", ["apron", "hat"]),
            ("a man", ["tunic", "trouser", "boot"]),
    ]:
        parts = " ".join(s["part"] for s in
                         recipes.plan_from_prompt(prompt)["steps"])
        for piece in wanted:
            check("%s wears a %s" % (prompt, piece), piece in parts)

    for prompt in ("a skeleton", "a golem", "a doll"):
        plan = recipes.plan_from_prompt(prompt)
        dressed = [s["part"] for s in plan["steps"]
                   if s["stage"] in ("clothing", "armour")]
        check("%s wears nothing, on purpose" % prompt, not dressed, str(dressed))

    # the pieces go on in the order a modeller would put them on
    plan = recipes.plan_from_prompt("a knight with a sword")
    order = plan["stages"]
    check("the body is built first", order[0] == "body", str(order))
    check("what it carries goes on last", order[-1] == "gear", str(order))
    check("the face comes before the armour",
          order.index("face") < order.index("armour"), str(order))

    # Armour and clothing go through the sculpt pass now - left out of it they
    # stayed as raw intersecting lofts and a sleeve ended in a flat disc in
    # mid-air. What keeps them from melting into the body is that they are a
    # different colour, and the sculpt pass fuses one colour group at a time.
    colour_of = {s["part"]: s["color"] for s in plan["steps"]}
    for piece in ("breastplate", "pauldron.L", "greave.R", "tassets"):
        if piece in colour_of:
            check("the %s cannot fuse into the body" % piece,
                  colour_of[piece] != colour_of["chest"],
                  "%s vs %s" % (colour_of[piece], colour_of["chest"]))

    # the small details are still exempt, because a remesh would swallow them
    soft = {s["part"] for s in plan["steps"] if not s["hard"]}
    for piece in ("visor", "buckle", "eye.L", "sword_blade"):
        if piece in colour_of:
            check("the %s keeps its edges" % piece, piece not in soft)

    # a kit brings its own colours only when the prompt names none
    steel = recipes.plan_from_prompt("a knight")
    green = recipes.plan_from_prompt("a green knight")
    plate = lambda p: next(s["color"] for s in p["steps"]
                           if s["part"] == "breastplate")
    check("an unpainted knight is in steel", plate(steel) == "#8f98a3",
          plate(steel))
    check("a green knight is green", plate(green) == recipes.COLORS["green"],
          plate(green))

    # every piece hangs off a bone that exists, or it would not animate
    for prompt in ("a knight with a sword", "a wizard with a staff", "a pirate",
                   "a ninja", "an astronaut", "a footballer"):
        plan = recipes.plan_from_prompt(prompt)
        names = {s["bone"]["name"] for s in plan["steps"] if s["bone"]}
        loose = sorted({s["attach"] for s in plan["steps"]
                        if s.get("attach") and s["attach"] not in names})
        check("%s: every piece hangs off a real bone" % prompt, not loose,
              str(loose))

    # palettes
    import palette as pal
    check("black is darker than white in Oklab",
          pal.oklab("#000000")[0] < pal.oklab("#ffffff")[0])
    check("junk is dropped from a palette",
          pal.normalise(["#1a1c2c", "zzz", "abc", "ffcd75", None]) ==
          ["#1a1c2c", "#ffcd75"])
    check("a name becomes a slug", pal.slug("Sweetie 16") == "sweetie-16",
          pal.slug("Sweetie 16"))

    sweetie = ["1a1c2c", "5d275d", "b13e53", "ef7d57", "ffcd75", "a7f070",
               "38b764", "257179", "29366f", "3b5dc9", "41a6f6", "73eff7",
               "f4f4f4", "94b0c2", "566c86", "333c57"]
    for name, colors in [(m, pal.MOODS[m]) for m in pal.known_moods()] + \
            [("sweetie-16", sweetie)]:
        plan = recipes.plan_from_prompt("a knight with a sword")
        before = []
        for s in plan["steps"]:
            if s["color"] not in before:
                before.append(s["color"])
        mapping = pal.snap_plan(plan["steps"], colors)

        on_palette = set(pal.normalise(colors))
        used = {s["color"] for s in plan["steps"]}
        check("%s: every colour is on the palette" % name,
              used <= on_palette, str(sorted(used - on_palette)))
        if len(pal.normalise(colors)) >= len(mapping):
            check("%s: colours stay distinct" % name,
                  len(set(mapping.values())) == len(mapping),
                  "%d of %d" % (len(set(mapping.values())), len(mapping)))
        order = sorted(before, key=lambda c: pal.oklab(c)[0])
        kept = all(pal.oklab(mapping[a])[0] <= pal.oklab(mapping[b])[0] + 1e-9
                   for a, b in zip(order, order[1:]))
        check("%s: the shading order survives" % name, kept)

    plain = recipes.plan_from_prompt("a knight with a sword")
    moody = recipes.plan_from_prompt("a knight with a sword, pastel")
    check("a mood named in the prompt is used",
          moody["palette_name"] == "pastel", moody["palette_name"])
    check("and it changes the colours",
          {s["color"] for s in plain["steps"]} !=
          {s["color"] for s in moody["steps"]})
    check("without one, nothing is snapped", plain["palette"] == [])

    explicit = recipes.plan_from_prompt("a knight", palette=sweetie)
    check("a palette passed in is used",
          {s["color"] for s in explicit["steps"]} <= set(pal.normalise(sweetie)))
    tiny = recipes.plan_from_prompt("a knight", palette=["#ff0000"])
    check("a palette of one colour is ignored, not obeyed",
          len({s["color"] for s in tiny["steps"]}) > 1)

    # a palette smaller than the model shares swatches rather than distorting
    three = ["#111111", "#888888", "#eeeeee"]
    plan = recipes.plan_from_prompt("a knight with a sword")
    was = []
    for s in plan["steps"]:
        if s["color"] not in was:
            was.append(s["color"])
    got = pal.snap_plan(plan["steps"], three)
    check("a tiny palette is still obeyed",
          {s["color"] for s in plan["steps"]} <= set(three))
    order = sorted(was, key=lambda c: pal.oklab(c)[0])
    check("and the shading still does not invert",
          all(pal.oklab(got[a])[0] <= pal.oklab(got[b])[0] + 1e-9
              for a, b in zip(order, order[1:])))

    # textures: what each part is made of
    for prompt, part, surface in [
            ("a knight with a sword", "breastplate", "metal"),
            ("a knight with a sword", "helmet", "metal"),
            ("a knight with a sword", "belt", "leather"),
            ("a wizard with a staff", "robe", "fabric"),
            ("a wizard with a staff", "staff_shaft", "wood"),
            ("an oak tree", "trunk", "wood"),
            ("a house", "walls", "concrete"),
            ("a crate", "box", "wood"),
            ("a barrel", "body", "wood"),
            ("a stone rock", "rock_00", "stone"),
    ]:
        plan = recipes.plan_from_prompt(prompt)
        got = next((s["material"] for s in plan["steps"] if s["part"] == part),
                   None)
        check("%s: the %s is %s" % (prompt, part, surface), got == surface,
              str(got))

    # a tree is mostly wood, but its leaves are not planks
    tree = recipes.plan_from_prompt("an oak tree")
    leaves = [s["material"] for s in tree["steps"] if s["part"].startswith("canopy")]
    check("a tree's canopy is not wood", leaves and "wood" not in leaves,
          str(leaves))

    # "a knight with a sword" sets prop to sword; a knight is not made of sword
    knight = recipes.plan_from_prompt("a knight with a sword")
    body = next(s["material"] for s in knight["steps"] if s["part"] == "chest")
    check("a prop in the prompt does not re-surface the body",
          body == "detail", body)

    check("every part has a surface",
          all(s.get("material") for s in knight["steps"]))
    check("the plan lists its surfaces",
          set(knight["surfaces"]) == {s["material"] for s in knight["steps"]})

    # a house is a house, not a box with a lid
    house = recipes.plan_from_prompt("a house")
    parts = {s["part"]: s for s in house["steps"]}
    for needed in ("walls", "roof", "door", "door_frame", "window_L",
                   "window_frame_L", "sill_L", "chimney", "plinth", "step"):
        check("a house has a %s" % needed, needed in parts)

    walls, roof = parts["walls"], parts["roof"]
    wall_top = walls["loc"][2] + walls["size"][2]
    roof_bottom = roof["loc"][2] - roof["size"][2]
    check("the roof starts at the top of the walls, not inside them",
          abs(roof_bottom - wall_top) < 0.25 * house["height"],
          "roof from %.2f, walls to %.2f" % (roof_bottom, wall_top))
    check("the roof overhangs the walls",
          roof["size"][0] > walls["size"][0] and roof["size"][1] > walls["size"][1],
          "roof %.2fx%.2f vs walls %.2fx%.2f" % (
              roof["size"][0], roof["size"][1], walls["size"][0], walls["size"][1]))
    check("the roof is above the walls at its peak",
          roof["loc"][2] + roof["size"][2] > wall_top)
    check("the walls are taller than a metre",
          walls["size"][2] * 2 > 1.0, "%.2f m" % (walls["size"][2] * 2))
    check("the house is taller than it is half-wide",
          house["height"] > walls["size"][0], "%.2f vs %.2f" % (
              house["height"], walls["size"][0]))
    check("the door reaches the ground",
          parts["door"]["loc"][2] - parts["door"]["size"][2] < 0.35)

    # a loft can extrude a polygon, which is what made the gabled roof possible
    gable = recipes.loft("g", [recipes.ring(-1, 0, 0, 2.0, 1.5, recipes.GABLE),
                               recipes.ring(1, 0, 0, 2.0, 1.5, recipes.GABLE)],
                         "#ffffff")
    check("a profiled loft is measured correctly",
          [round(v, 2) for v in gable["size"]] == [1.0, 2.0, 0.75],
          str([round(v, 2) for v in gable["size"]]))
    check("and it is built the right way up",
          round(gable["loc"][2], 2) == 0.75, str(round(gable["loc"][2], 2)))

    # animation prompts
    for prompt, move, faster in [("walk", "walk", False), ("walk slowly", "walk", False),
                                 ("run fast", "run", True), ("big jump", "jump", False),
                                 ("wave hello", "wave", False), ("", "idle", False)]:
        got = anim.read_prompt(prompt)
        check("reads %r as %s" % (prompt or "(nothing)", move), got["move"] == move,
              got["move"])
        if faster:
            check("  and faster", got["speed"] > 1.0)
    check("slowly is slower", anim.read_prompt("walk slowly")["speed"] < 1.0)
    check("one-shot moves do not loop", not anim.read_prompt("jump")["loop"])
    check("cycles do loop", anim.read_prompt("walk")["loop"])

    # every move must exist for every rig, or a button would do nothing
    for profile, table in anim.PROFILES.items():
        missing = sorted(set(anim.MOVES) - set(table))
        check("%s knows every move" % profile, not missing, str(missing))


# --------------------------------------------------------------------------
# the worker, for real
# --------------------------------------------------------------------------

class Worker:
    def __init__(self, session):
        self.proc = subprocess.Popen(
            [BLENDER, "--background", "--factory-startup", "--python",
             os.path.join(ROOT, "blender", "worker.py"), "--", session],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.session = session
        self.await_event("ready", 120)

    def send(self, **msg):
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def await_event(self, wanted, timeout=120):
        """Collect events until `wanted` arrives, or an error, or time runs out."""
        deadline = time.time() + timeout
        seen = []
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                break
            if not line.startswith(MARK):
                continue
            event = json.loads(line[len(MARK):].strip())
            seen.append(event)
            if event["event"] == "error":
                return {"event": "error", "message": event.get("message", ""),
                        "seen": seen}
            if event["event"] == wanted:
                event["seen"] = seen
                return event
        return {"event": "timeout", "seen": seen}

    def run(self, wanted, timeout=120, **msg):
        self.send(**msg)
        return self.await_event(wanted, timeout)

    def stop(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def check_worker(quick):
    import recipes
    print("\nthe worker (real Blender)")
    session = os.path.join(ROOT, "sessions", "checks")
    os.makedirs(session, exist_ok=True)
    w = Worker(session)

    models = [
        ("a tall blue knight with a sword and a cape", "humanoid", 14),
        ("a chunky red robot with an antenna", "humanoid", 14),
        ("a brown dog with a tail", "quadruped", 14),
        ("a small white chicken", "bird", 4),
        ("a pine tree", "prop", 1),
        ("a treasure chest", "prop", 1),
    ]
    if not quick:
        models += [
            ("a wizard with a staff and a hat", "humanoid", 14),
            ("a fat grey wolf", "quadruped", 14),
            ("a blocky green golem", "humanoid", 14),
            ("a snowman", "prop", 3),
            ("a red flag", "prop", 2),
            ("a rocket", "prop", 1),
        ]

    for prompt, archetype, min_bones in models:
        built = w.run("built", 180, cmd="build", prompt=prompt)
        if not check("build: %s" % prompt, built["event"] == "built",
                     built.get("message", built["event"])):
            continue
        check("  it has parts", built["parts"] > 0)
        check("  it has triangles", built["triangles"] > 0)
        check("  it has a real size", 0.02 < built["height"] < 60,
              str(built["height"]))
        expect_sculpt = recipes.plan_from_prompt(prompt)["organic"]
        check("  sculpted" if expect_sculpt else "  left crisp",
              built.get("sculpted") is expect_sculpt,
              str(built.get("sculpted")))
        if expect_sculpt:
            stages = [e for e in built["seen"] if e["event"] == "sculpting"]
            check("  the sculpt pass reported itself",
                  any(s.get("stage") == "done" for s in stages))
            check("  and did not explode the triangle count",
                  built["triangles"] < 200000, str(built["triangles"]))
        steps = [e for e in built["seen"] if e["event"] == "step"]
        check("  one snapshot per part", len(steps) == built["parts"],
              "%d snapshots, %d parts" % (len(steps), built["parts"]))
        check("  every snapshot exists",
              all(os.path.getsize(os.path.join(session, s["file"])) > 0
                  for s in steps))

        rigged = w.run("rigged", 180, cmd="rig")
        if not check("  rig: %s" % prompt, rigged["event"] == "rigged",
                     rigged.get("message", rigged["event"])):
            continue
        check("  enough bones (%d+)" % min_bones, rigged["count"] >= min_bones,
              str(rigged["count"]))
        check("  rigged exactly, from the recipe", rigged.get("exact") is True)
        check("  no duplicate bone names",
              len(set(rigged["bones"])) == len(rigged["bones"]))

        moves = ["walk", "idle", "spin"] if quick else \
            ["idle", "walk", "run", "jump", "wave", "dance", "attack", "spin",
             "die", "sit"]
        for move in moves:
            got = w.run("animated", 180, cmd="animate", prompt=move)
            ok = check("  animate %s" % move, got["event"] == "animated",
                       got.get("message", got["event"]))
            if ok:
                check("    has frames", got["frames"] > 1, str(got["frames"]))
                check("    file written",
                      os.path.getsize(os.path.join(session, got["file"])) > 0)

        for fmt in ("glb", "fbx"):
            got = w.run("exported", 180, cmd="export", format=fmt)
            check("  export .%s" % fmt, got["event"] == "exported",
                  got.get("message", got["event"]))

    # a model that arrives as one lump, with no recipe to read
    lump = os.path.join(session, "export_tall_blue_knight_sword_cape.glb")
    if not os.path.exists(lump):
        candidates = [f for f in os.listdir(session) if f.startswith("export_")
                      and f.endswith(".glb")]
        lump = os.path.join(session, candidates[0]) if candidates else None
    if lump:
        got = w.run("built", 180, cmd="import", path=lump)
        if check("imports a finished model", got["event"] == "built",
                 got.get("message", got["event"])):
            rigged = w.run("rigged", 240, cmd="rig", profile="humanoid")
            if check("  fits a skeleton to it", rigged["event"] == "rigged",
                     rigged.get("message", rigged["event"])):
                check("  fitted, not exact", rigged.get("exact") is False)
                check("  and it has bones", rigged["count"] >= 14,
                      str(rigged["count"]))
                got = w.run("animated", 180, cmd="animate", prompt="walk")
                check("  and it walks", got["event"] == "animated",
                      got.get("message", got["event"]))

    # a sculpted model must still rig exactly - the weights are transferred
    # across the remesh, and if that ever silently fails this is what catches it
    built = w.run("built", 180, cmd="build", prompt="a tall blue knight with a sword")
    if check("sculpted knight builds", built["event"] == "built",
             built.get("message", built["event"])):
        rigged = w.run("rigged", 180, cmd="rig")
        if check("  it still rigs", rigged["event"] == "rigged",
                 rigged.get("message", rigged["event"])):
            check("  exactly, from the recipe", rigged.get("exact") is True)
            check("  with every bone the recipe asked for",
                  rigged["count"] == len(recipes.plan_from_prompt(
                      "a tall blue knight with a sword")["steps"] and
                      [s for s in recipes.plan_from_prompt(
                          "a tall blue knight with a sword")["steps"]
                       if s.get("bone")]),
                  str(rigged["count"]))
            got = w.run("animated", 180, cmd="animate", prompt="walk")
            check("  and walks", got["event"] == "animated",
                  got.get("message", got["event"]))

    # things that should fail politely rather than crash
    w.run("built", 180, cmd="build", prompt="a knight")
    got = w.run("animated", 30, cmd="animate", prompt="walk")
    check("animating before rigging says so, and does not crash",
          got["event"] == "error" and "Auto-Rig" in got.get("message", ""),
          got.get("message", got["event"]))
    got = w.run("pong", 30, cmd="ping")
    check("still alive after that", got["event"] == "pong")

    w.stop()


def main():
    quick = "--quick" in sys.argv
    started = time.time()
    check_parser()
    if "--parser-only" not in sys.argv:
        check_worker(quick)
    print("\n%d passed, %d failed, %.0fs" %
          (len(PASS), len(FAIL), time.time() - started))
    if FAIL:
        print("failed:")
        for name in FAIL:
            print("  -", name)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
