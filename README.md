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
waiting for a file. Meanwhile the panel on the right goes and finds photographs
of the real thing, so you can judge the model against a knight rather than
against what a knight is assumed to look like.

**1½ · It gets sculpted.** A body made of a box, two cylinders and a sphere reads
as a box, two cylinders and a sphere however carefully they are placed. So once
the parts are down they are fused: voxel-remeshed into one continuous skin,
relaxed, and shaded smooth. The seam where an arm meets a shoulder stops being a
seam. Anything hard-surfaced — a crate, a sword, a deliberately blocky robot —
is left crisp, because a crate with soft corners is a worse crate.

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

## Where the shapes come from

Nothing in here was eyeballed. The recipes are written to measured proportions
and the source is named in the code beside the numbers:

| Subject | What it is built to |
|---|---|
| People | the **eight-head canon** — head 1/8 of the height, crotch at 4 heads, shoulders 2⅓ heads across and a third of a head below the chin, arms 3 heads long, elbow at the navel, wrist at the crotch |
| Four-legged animals | breed-standard **length against shoulder height**, about 10 to 8.5; muzzle 4.5 to the skull's 5.5 |
| Birds | a chicken measured at **40–60 cm long, 25–37 cm tall, 11.5–18 cm across** — a long narrow thing, not a ball |

The checks enforce them: one of them fails if the figure stops being eight heads
tall, another if the dog stops being longer than it is tall.

## The sculpt pass, in detail

Headless Blender cannot drive sculpt-mode brushes — they need a viewport — but it
can drive the thing a sculptor reaches for first, which is the **voxel remesh**.
Three things have to survive it, and each is handled:

- **Colour.** A remesh keeps one material, so parts are grouped by colour and each
  group is remeshed on its own. A blue torso and a skin-coloured forearm stay
  blue and skin-coloured, and the join between them reads as a sleeve.
- **Weights.** A remesh throws vertex groups away, so they are painted on before
  and transferred back from the original geometry afterwards. That is what keeps
  the rig exact rather than guessed.
- **Thin things.** A voxel grid swallows anything thinner than about two voxels.
  Those parts are measured and left alone rather than dissolved.

Two masses have to *overlap* for a remesh to blend them — meeting at a plane
leaves a crease. That is why the pelvis and the ribcage are built taller than
they strictly need to be.

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
server.py         keeps Blender alive, serves the page, streams progress,
                  and fetches reference photographs from Wikimedia Commons
blender/
  recipes.py      words  ->  a build plan        (no Blender needed, so testable)
  build.py        a build plan  ->  geometry
  sculpt.py       loose parts   ->  one continuous form
  rig.py          geometry      ->  a skeleton and weights
  anim.py         a move        ->  keyframes; and .fbx retargeting
  worker.py       one long-running Blender, JSON in, JSON out
web/              the page, and three.js kept locally
animations/       .fbx clips you drop in
sessions/         everything Blender writes, one folder per run
tests/check.py    673 checks, parser and real Blender
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
python3 tests/check.py            # 673 checks, about 30 seconds
python3 tests/check.py --quick    # fewer models
python3 tests/check.py --parser-only   # no Blender needed
```

The worker checks drive the real Blender exactly as the app does and look at
what comes back. They have already earned their keep: they caught a crystal and
a rocket that were half underground, and a chicken whose beak pointed backwards.
They also hold the proportions to their references, so a figure that stops being
eight heads tall fails a check rather than merely looking wrong.

What they cannot catch is ugliness. Render the model and look at it — that is
how the deflated limbs, the crease at the waist and the plank of a cape were
found, none of which any check would have objected to.

## Reference pictures

Type a prompt and boneka looks the subject up on **Wikimedia Commons** — no key,
no account, licence shown on every thumbnail. The server fetches them, not the
page, so the browser never makes a third-party request and the origin rule holds
for everything on screen. Offline, the panel says so and nothing else changes.

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
