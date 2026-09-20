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
