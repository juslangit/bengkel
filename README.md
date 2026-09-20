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

**1 · Make it.** You write *a knight with a sword*. boneka reads the words,
works out what a knight is assembled from, and builds it in Blender one piece
at a time — in the order a modeller would:

```
Body      pelvis · ribcage · neck · head · deltoid · upper arm · forearm ·
          hand · thigh · shin · foot
Face      eye left · eye right
Armour    breastplate · pauldron · pauldron · gauntlet · gauntlet
Clothing  belt · buckle
Armour    tassets · greave · greave
Clothing  boot · boot
Armour    helmet · visor slit · nose guard · crest
Gear      sword grip · cross guard · sword blade · sword tip
```

Each finished piece is sent straight to the browser as it is made, so you watch
the thing being assembled rather than waiting for a file. The panel on the right
meanwhile goes and finds photographs of the real thing, so you can judge the
model against a knight rather than against what a knight is assumed to look like.

The belt goes on before the tassets because that is the order it goes on.

**1½ · It gets sculpted.** Two things stop it looking like stacked boxes.

The parts themselves are **lofted cross-sections**, not primitives: a torso is a
stack of rings that starts wide at the shoulders, narrows at the waist and widens
again at the hips; an arm is a shoulder ring, a bicep swell, an elbow, a forearm
swell and a wrist. A box with the corners filed off is still a box, and that is
all a smoothed primitive can ever be.

Then the soft parts are **fused**: voxel-remeshed into one continuous skin,
relaxed and shaded smooth, so the seam where an arm meets a shoulder stops being
a seam. Anything hard-surfaced — a crate, a sword, a deliberately blocky robot —
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

## What each character is assembled from

A knight is not a blue person. It is a body, and then a breastplate, and then a
pauldron on each shoulder, gauntlets, a belt, tassets, greaves, boots, a helmet
and a crest — **each one its own named piece**, fitted over the body underneath
and tied to the bone it should move with, so the pauldron turns with the
shoulder and the greave swings with the shin.

There are twenty-six modules and a kit for each kind of character:

| | |
|---|---|
| **knight** | breastplate, pauldrons, gauntlets, belt, tassets, greaves, boots, helmet, crest |
| **wizard · mage · witch** | robe, belt, pointed hat |
| **pirate** | coat, belt, boots, tricorn, eyepatch |
| **ninja** | tunic, belt, wrist wraps, boots, hood, face mask |
| **king · queen** | robe, belt, crown |
| **farmer** | tunic, trousers, boots, straw hat |
| **chef** | tunic, apron, chef's hat |
| **viking** | fur mantle, belt, boots, horned helmet |
| **astronaut** | tunic, belt, gauntlets, boots, glass helmet dome |
| **soldier · guard · dwarf · elf · orc · goblin · zombie · pirate · hero · villain · footballer…** | their own |
| **anyone else** | tunic, trousers, boots — a plain person still gets dressed |
| **skeleton · golem · doll · puppet** | nothing, on purpose |

Every module is a function of the body it is going onto, so the same helmet fits
a tall thin figure and a short fat one. Whatever the clothes cover becomes an
under-layer in a darker shade, so a garment reads as a garment on top of a body
rather than as a differently shaped body. And if you name neither a colour nor a palette, the kit
brings its own — a knight comes out in steel, a ninja in black, a king in red
and gold — while *a green knight* is green.

Modules are always left crisp by the sculpt pass. A plate that has been
remeshed into the chest is no longer a plate.

## Colour: one palette for the whole model

Type a palette name and **every colour on the model comes from it** — body,
garment, trim and the shades, not just a main colour with two multiplications
applied to it.

```
a knight with a sword          palette: sweetie-16
a pirate                       palette: endesga-32
a wizard with a staff, pastel
```

Ten moods are built in and need no network at all — *pastel, muted, earthy,
neon, monochrome, sunset, forest, ice, rust, candy* — and you can name **any
palette on [Lospec](https://lospec.com/palette-list)**, which is thousands of
hand-made ones. A palette is kept on disk after the first fetch, so one you have
used before still works with the network unplugged. Blender is handed the
colours, never the name, so the build itself never touches the network.

### Getting the snapping right

Matching is done in **Oklab**, not RGB. Nearest-in-RGB is the obvious way and
it is wrong: it will swap a mid green for a dark blue because the numbers are
close, while your eye sees nothing in common.

Two things then have to be true at once, and they pull against each other:

- **distinct** — no two of the model's colours may land on the same swatch, or
  the model goes flat
- **in order** — a colour that started darker than another must end darker than
  it, or the shading inverts and the form reads inside out

Both hold if the model's colours are sorted by lightness, the palette is sorted
by lightness, and each colour takes a strictly later swatch than the one before.
That leaves a choice of which swatches to skip, and the choice is made to keep
the colours as close to the originals as possible — a shortest path over a grid,
solved exactly rather than guessed at.

Two greedier versions came first and both failed. Nearest-swatch-then-fix kept
undoing its own de-duplication; a one-pass greedy walk let an early dark colour
take a light swatch and then ran out of palette. A palette smaller than the
model shares swatches rather than distorting, and still never inverts.

## Surfaces: textures from Texturelabs

Nothing is perfectly flat any more. Every part is given a surface based on what
it is — metal on armour, wood on a staff or a crate, fabric on a robe, stone on
a rock, concrete on a wall — and anything unclassified gets a faint grunge, so
no surface is a plain slab of colour.

The textures come from **[Texturelabs](https://texturelabs.org/)**, free and
with no account. They are photographs for graphic design, not PBR material
sets — there are no normal or roughness maps — so they are used as a **multiply
over the colour a part already has**. The palette still decides the colour; the
texture decides the surface is not flat. That keeps the two systems from
fighting each other.

Each source photograph is turned into a grey detail map once — desaturated,
auto-contrasted, then squeezed into a narrow range around white, per surface,
because skin and cloth want a whisper where rusted metal and bare soil can take
a shove. The server fetches and prepares; Blender is handed file paths and
never touches the network.

A model has no UVs to begin with — the lofts are built with bmesh and the voxel
remesh throws away whatever a mesh had — so every part is smart-projected and
scaled to bounds, fitting the texture once across each part. These are not
tiling materials, so repeating them would show the seam every time.

The ones used are **hand-picked**. The site holds design overlays and
decorative tilework beside the real surfaces: one "brick" turned out to be
Moroccan zellij, one "fabric" a photograph of a t-shirt on a white background.
They were looked at before being chosen.

### What you may do with a textured export

Texturelabs is free for commercial use and asks for no credit, but the terms
are specific about 3D:

> *Texturelabs resources cannot ... be distributed or sold as part of a 3D
> model in a way that allows a third party to use, download, extract or access
> the Texturelabs asset.*

Using one **inside a finished game is explicitly allowed**. Handing someone the
`.glb` is not. So every textured export writes a `…_TEXTURES.txt` beside it
naming what is inside and repeating the restriction — the obligation travels
with the file instead of relying on anyone remembering. **Never commit these
files, or the `textures/` folder, to a repository.**

There is a `texturelabs` command on the PATH for the same library outside
boneka: `texturelabs categories`, `texturelabs search wood`,
`texturelabs pick metal -n 3`. It writes a `SOURCES.md` beside whatever it
downloads, with the same licence line.

## Where the shapes come from

Nothing in here was eyeballed. The recipes are written to measured proportions
and the source is named in the code beside the numbers:

| Subject | What it is built to |
|---|---|
| People | the **eight-head canon** for the vertical landmarks — head 1/8 of the height, crotch at 4 heads, chin at 7, shoulders a third of a head below it, arms 3 heads long, elbow at the navel, wrist at the crotch. Widths come from **anthropometry** instead, because the drawing canon measures the fleshed silhouette and this has to build the flesh: biacromial breadth is about 0.234 H and shoulder-to-hip about 1.4, so the skeletal shoulder ring is narrower than the finished figure and the deltoids make up the difference |
| Four-legged animals | breed-standard **length against shoulder height**, about 10 to 8.5; the chest reaching halfway down the leg; muzzle 4.5 to the skull's 5.5; and the hind leg angulated, stifle forward and hock back |
| Birds | a chicken measured at **40–60 cm long, 25–37 cm tall, 11.5–18 cm across** — a long narrow thing, not a ball, with the thigh buried in the feathers and only the shank showing |

The checks enforce them: one of them fails if the figure stops being eight heads
tall, another if the dog stops being longer than it is tall.

## Lofts, in detail

`loft()` describes a part by its **cross-sections** rather than by a primitive:
a list of rings, each with its own centre, half-width and half-depth. Each ring
is laid perpendicular to the path through its neighbours, so a curved stack of
rings makes a curved form rather than a sheared one.

That is what lets a torso taper and a limb carry a muscle. It is also why the
figure stands in a slight A-pose: the gap between arm and waist is most of what
makes a standing figure read as a person rather than a slab, and it only exists
if the arm is held off the body.

Two masses have to **overlap** for the remesh to blend them — meeting at a plane
leaves a crease, which is what the ridge at a dog's waist and the seam at a
figure's navel were. And a limb's topmost ring has to be *narrower* than the
body it enters, or it punches a plate out through the flank; the blending mass
that sits there is a deltoid on a person and a shoulder blade or haunch on a dog.

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

The grid is sized **per colour group**, not once for the whole model. One tiny
part — the tip of an ear — used to drag the global voxel size down until the
body was remeshed at a millimetre, which both exploded the triangle count and
left every intersection as a visible crease, because a grid that fine simply
reproduces the parts it was given.

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
                  fetches reference photographs from Wikimedia Commons,
                  palettes from Lospec and textures from Texturelabs, and
                  prepares and caches all three
blender/
  recipes.py      words  ->  a build plan: the body, then the kit it wears
                  (no Blender needed, so the whole thing is testable)
  palette.py      a plan + a palette  ->  the plan, recoloured
  build.py        a build plan  ->  geometry, including lofts
  sculpt.py       loose parts   ->  one continuous form
  rig.py          geometry      ->  a skeleton and weights
  anim.py         a move        ->  keyframes; and .fbx retargeting
  worker.py       one long-running Blender, JSON in, JSON out
web/              the page, and three.js kept locally
animations/       .fbx clips you drop in
palettes/         palettes fetched from Lospec, kept for offline use
textures/         textures fetched from Texturelabs - never committed
sessions/         everything Blender writes, one folder per run
tests/check.py    779 checks, parser and real Blender
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
python3 tests/check.py            # 779 checks, about 30 seconds
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
