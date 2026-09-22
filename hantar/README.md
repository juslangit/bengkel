# hantar

**Into the game, in the shape that game wants.**

*Hantar* is to deliver. This is the last stage, and the only tool in the
workshop that writes anywhere other than the workshop.

```bash
hantar             # on its own
bengkel            # or the last door in the workshop
```

## The last mile

A model being finished is not the same as a model being *in the game*. What
stands between them is four small things that are each easy to get wrong:

| | |
|---|---|
| **the right place** | every project has its own layout, and none of them is the layout a tool would have chosen |
| **the right name** | one project spells a file `boss-walk.glb` and another `Boss_Walk.glb`, and an engine cares |
| **the right size** | periksa says the origin is at its ear and it is ninety metres tall; something has to actually move it |
| **the right format** | Godot takes `.glb`, Unreal wants `.fbx` and counts in centimetres |

## It follows the project, not its own opinion

hantar does not invent a layout. For each game it finds **where that project
already keeps its models** — ranked by what is really in each folder, with
`assets/` preferred over `docs/` and per-download folders discounted — and
reads **how those files are already spelled**. Type `Walker Walk` and it
becomes `walker_walk.glb` in a project whose folder is full of
`athlete_average.glb`, and `walker-walk.glb` in one full of `boss-walk.glb`.

A tool that imposes its own convention on twelve existing projects is a tool
that makes work rather than saving it.

The engine is read from the file only that engine leaves: `project.godot`,
a `.uproject`, or an `index.html`.

## It says where it will land before it writes

The full path appears under the name box and changes as you type, and it says
so in amber when something of that name is already there. Sending over an
existing file asks first.

A delivery you cannot see in advance is one you find out about by looking in
Finder afterwards.

## What it fixes on the way in

periksa reports; hantar is the thing that actually moves them.

- **Stand it on the floor** — the origin to the ground, centred. That is where
  an engine places, rotates and grounds a model from.
- **Make it N metres tall** — scaled to a real-world height, leaving it alone
  if you say nothing.
- **Unreal counts in centimetres** — a 1.8 m character is 180 units there, so
  the FBX is exported at 100 units to the metre, `-Z` forward and `Y` up. The
  other half of every "why is my model sideways" afternoon.

Each folder gets a growing `WHERE-THESE-CAME-FROM.md` — one line per model,
saying where it came from and what was fixed on the way in. One list you can
glance down beats twelve notes nobody reads.

## What it will not do

**It only writes inside `~/Desktop/project/game/`.** A page asking for any
other path is refused, whatever it says. This is the one tool that can leave a
mess somewhere that matters.

## Tests

```bash
tests/run.sh           everything
tests/run.sh --quick   skip the Blender runs
```

17 checks plus 14 in the browser. Every delivery in them goes into a throwaway
project made for the test and deleted afterwards — nothing in the suite
touches real work. It checks that a project's engine is read correctly, that
the destination folder and spelling are found rather than assumed, that a
delivery outside the game folder is refused, that the file which arrives is
really 1.80 m and really standing on the floor — read back from the delivered
file rather than believed because the tool said so — and that sending over
something already there is a question and not a silent overwrite.
