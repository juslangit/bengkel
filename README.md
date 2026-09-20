# boneka

**Type what you want, watch Blender build it, press one button for bones, then
tell it how to move.**

boneka ("puppet" in Malay) is a local app. You open it in a browser, but nothing
leaves the machine and nothing costs money: the thinking is a Python program, the
modelling is the Blender already installed, and the picture in the middle of the
screen is the model as it is being made.

```
boneka
```

That is the whole command. It opens at `http://127.0.0.1:8777`.

---

## The four things it does

**1 · Make it.** You write *a tall blue knight with a sword and a cape*. boneka
reads the words, plans about twenty-five parts, and builds them in Blender one at
a time. Each finished part is sent straight to the browser, so the model appears
hips first, then chest, then head, then an arm — you watch it happen rather than
waiting for a file.

**2 · Give it bones.** One button. Because boneka built the mesh itself, it
already knows that *this* is the left forearm and that the elbow is exactly
here — so the skeleton is placed from the recipe, not guessed from a cloud of
triangles. Every part is weighted to its own bone and then the weights are
softened across the joints so the limbs bend instead of snapping.

**3 · Make it move.** You write *walk slowly* or *big jump* or *fast dance*.
boneka writes the keyframes onto the rig and plays them back in the viewport. It
knows nineteen moves, and each one is written for each kind of body, so *walk* on
a dog is a dog's diagonal gait and not a person's.

**4 · Take it away.** `.glb`, `.fbx` or `.blend`, with the animation baked in.
Godot and Unreal both read the first two.

---

## What it can build

| Kind | What you say | What you get |
|---|---|---|
| People | knight, wizard, robot, ninja, farmer, zombie, orc, astronaut… | a full humanoid, 18 bones |
| Four-legged animals | dog, cat, wolf, horse, dragon, bear… | body, head, four legs, a tail, 18+ bones |
| Birds | chicken, duck, owl, penguin, eagle… | body, wings, legs, tail |
| Objects | 34 of them — tree, chair, sword, house, rocket, car, campfire, snowman… | the object, with a bone so it can still spin and bob |

Words it also understands: **size** (tiny, small, tall, huge, giant), **build**
(thin, slim, chunky, fat, buff), **style** (blocky, voxel, round, cute, chibi),
any **colour** (the first colour paints the body, the second the trim), and
**extras** — with a hat, with horns, with wings, with a tail, with a cape, with a
backpack, with a sword, with a shield, with a staff, with an antenna.

Nothing here is a neural network. It is a library of recipes written in real
proportions, which is why a 1.8 m person really is 1.8 m tall and lands in Godot
at the right scale.

## Moves it knows

idle · walk · run · sneak · jump · wave · cheer · dance · attack · punch · kick ·
nod · shake · crouch · sit · die · fly · spin · bob

Say *slowly*, *fast* or *frantic* to change the speed; *subtle*, *big* or
*exaggerated* to change how far it goes.

## Borrowing real motion capture

Drop a `.fbx` clip into `animations/` and it appears in a menu under the
animation box. Mixamo is the usual source — download as **FBX Binary**, **without
skin**. boneka translates the bone names and reads every turn in the source rig's
own space before writing it into ours, so the two skeletons don't have to agree
on rest pose or bone length. The result is close rather than exact; that is the
nature of retargeting.

## Meshy

If you want a properly textured, organic model rather than a built one, there is
a **Use Meshy** button. It costs real credits, so it always asks first and
**never** runs on its own. What comes back is one lump of triangles with no part
names, so Auto-Rig switches to its other route: a standard skeleton measured
against the mesh's own proportions, with Blender working the weights out by heat
diffusion.

---

## How it is put together

```
boneka            the launcher - starts the server, opens the browser
server.py         keeps Blender alive, serves the page, streams progress
blender/
  recipes.py      words  ->  a build plan        (no Blender needed, so testable)
  build.py        a build plan  ->  geometry
  rig.py          geometry  ->  a skeleton and weights
  anim.py         a move  ->  keyframes; and .fbx retargeting
  worker.py       one long-running Blender, JSON in, JSON out
web/              the page, and three.js kept locally
animations/       .fbx clips you drop in
sessions/         everything Blender writes, one folder per run
tests/check.py    621 checks, parser and real Blender
```

The one design decision everything else follows from: **Blender is started once
and left running.** Commands go in on stdin as JSON, events come back on stdout.
The scene, the rig and the pose are all still there between button presses, which
is why Auto-Rig is instant instead of re-loading a file.

### Sizes, one rule

Every size in a recipe is a **half-extent**: half the width, half the depth, half
the height, or the radius. One rule, applied everywhere, because the first draft
mixed half and full sizes and produced a person with hips 72 cm across.

### Rotations, one rule

Every pose is written as a turn around a **world** axis — "swing the right thigh
forward twenty degrees" — and converted into the bone's own space at the last
moment. That means a pose never depends on how a bone happens to be rolled,
which is the usual reason hand-written rig animation comes out twisted.

## Checks

```
python3 tests/check.py            # 621 checks, about 20 seconds
python3 tests/check.py --quick    # fewer models
python3 tests/check.py --parser-only   # no Blender needed
```

The worker checks drive the real Blender exactly as the app does and look at
what comes back. They have already earned their keep: they caught a crystal and
a rocket that were half underground, and a chicken whose beak pointed backwards.

## Requirements

macOS with Blender (tested on 5.2.1 LTS) and the system Python. Nothing to
install. If Blender lives somewhere unusual, set `BONEKA_BLENDER`. To move the
port, set `BONEKA_PORT` — though if it is busy boneka takes the next one by
itself.

## A note on the lock on the door

A server listening on localhost with no lock is reachable by every page in your
browser, so boneka checks two things on every request: a token made fresh each
run and carried in the address bar, and that the request came from boneka's own
origin. Neither is optional, and neither is there for show.
