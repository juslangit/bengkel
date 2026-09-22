# jaring

**Turn a heavy model into one a game can carry — and keep the detail.**

A *jaring* is a net: an even mesh. That is literally what this does. It rebuilds
a model's surface out of even quads, lays out UVs on the new surface, and bakes
the detail it just removed into a normal map so the light still behaves as
though the detail were there.

```bash
jaring             # on its own
bengkel            # or the third door in the workshop
```

## The one question

Every tool that does this asks **how many faces do you want**, which nobody
knows. jaring asks **how wide should one quad be**, in centimetres, which you
can picture: a 2 cm quad on a person-sized character is about a knuckle.

The face count follows from the model's own surface area:

```
faces = area ÷ (quad size)²
```

so 4 m² of surface at 2 cm quads is 10,000 quads. The page works that out as
you drag and shows it **before** the minute of Blender, not after.

| | | |
|---|---|---|
| **Hero** | 0.8 cm | Close to the camera. Heavy, detailed. |
| **Game** | 2 cm | The usual choice. Light enough to animate. |
| **Background** | 6 cm | Far away, or there are fifty of them. |

The presets are a starting point, not a mode — move the slider and they go dark.

## What one press does

1. **Weld** — merge vertices that sit in the same place. glTF has no shared
   vertices, so a model that has been through a `.glb` arrives as loose
   triangles that merely touch: a sphere exported and re-imported comes back
   with 32,512 non-manifold edges. Without this step no model is ever closed
   and the quad path might as well not exist.
2. **Remesh** — Quadriflow rebuilds the surface in even quads, if the model is
   closed. A real downloaded character usually is not — armour pieces, hair
   cards and eyes are separate open shells — and then jaring remeshes with
   voxels instead and says so.
3. **Unwrap** — UVs on the new surface, with a few pixels between islands so
   the bake cannot bleed from one to its neighbour.
4. **Bake** — the original's detail into a tangent-space normal map. The rays
   travel 2% of the model's own diagonal: far enough to reach the detail, not
   far enough to punch through and hit the far side.
5. **LODs** — the distance versions, each decimated from the one above rather
   than remeshed from the original, so they all share the one baked map.

## Before and after, side by side

The two halves of the viewport share one camera. Turn one and the other turns
with it, so the difference you see is the mesh and never the angle. Both are
drawn by a single renderer: two would each hold their own WebGL context, and a
browser hands out a small number of those before it starts silently taking them
back.

## What comes out

```
~/Documents/bengkel/jaring/out/<name>/
    <name>.glb            the result, with the normal map wired in
    <name>_LOD1.glb       the distance versions, one file each
    <name>_LOD2.glb
    <name>_normal.png     the baked map
    <name>.blend          all of them together, to look at by hand
    WHAT-JARING-DID.md    what it was, what it is, and the settings used
```

One file per LOD, not all of them in one: LODs are alternatives to each other,
and in a single `.glb` they are not alternatives, they are three copies of a
model standing inside one another.

Inside bengkel, the result goes on to **gerak** with one press.

## The two ways Quadriflow lies

Neither raises anything, and both were found by looking at the screen rather
than by a test.

**It cancels rather than raising** when it dislikes a mesh, leaving an
untouched copy that looks like a result — which then gets a flat, useless
normal map baked from it.

**It returns FINISHED and hands back shards** when the mesh is not watertight:
a different shape, at a different size, in a different place. A 1.3 metre
paladin came back 8 metres across, and every other check passed — it was
lighter, it had UVs, it had a baked map, it was on disk.

So jaring measures the result. A remesh of a thing is the same size as the
thing; anything else is thrown away and done again with voxels. The size in
and the size out are reported with every result, and the test suite asserts
they agree.

## When it comes out heavier

It will, if you pick a quad size finer than the model needed — a 12,000
triangle model at 2 cm quads comes back at 12,500. That is not a failure: it
now has even quads, real UVs and a baked map, which the download did not. But
it is not the lighter model you pressed the button for, so jaring says so
plainly rather than reporting "−2% lighter".

## Where the maths came from

All of it is lifted from **Retopo Kit**, the Blender add-on in
`~/Desktop/project/3d/retopology` that solved the same problem with a person
watching. The quad-size formula, the 2%-of-the-diagonal ray distance, the
four-pixel island margin, decimating each LOD from the one above — those are
numbers that were found to work on real sculpts, and they are re-used here
rather than re-derived. What jaring adds is that nobody has to be watching.

## Tests

```bash
tests/run.sh           everything, about two minutes
tests/run.sh --quick   skip the Blender run
```

19 checks plus 15 in the browser. The ones that matter are about the result
rather than the exit code: that a real model comes out **the same size** it
went in, and lighter; that a fallback to voxels is said out loud; that the
normal map holds real detail rather than being a flat sheet; that each LOD has
its own file and is lighter than the one above; and that the number the page
shows before the remesh is the number the remesher uses.

The suite builds its own watertight lump with Blender
(`tests/make-blob.py`), because every model on this machine is a downloaded
game character and not one of them is closed — without it the quad path would
never be exercised at all.
