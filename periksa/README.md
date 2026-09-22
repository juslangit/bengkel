# periksa

**A last look before a model goes into a game.**

*Periksa* is to inspect. This is the Check stage: the place where the things
that waste an afternoon are caught in a second.

```bash
periksa            # on its own
bengkel            # or the fifth door in the workshop
```

## It reads the file. It does not open it.

A `.glb` carries its own table of contents in a JSON chunk at the front —
every mesh, every material, every image, every animation, and the exact
bounding box of each accessor. That is enough for everything here, so periksa
never starts Blender and never unpacks a byte of geometry. It takes a few
milliseconds, which is what *light* was supposed to mean.

## What it catches

Almost none of it is exotic. Each one is obvious once you know and invisible
until you do:

- **It is ninety metres tall.** Whoever made it worked in centimetres and the
  exporter believed them. The single most common thing wrong with a download.
- **Its origin is somewhere near its left ear.** An engine places, rotates and
  grounds a model about its origin; anywhere else and it hovers, sinks, or
  swings around a point outside itself.
- **It has no UVs.** Every texture will be one smeared pixel, and nothing
  anywhere will say why.
- **It has forty materials.** That is forty draw calls for one prop.
- **It has clips with no name.** An engine calls a clip by name, so unnamed
  ones have to be picked by number — which changes every time it is
  re-exported.
- **It is 60 MB.** Usually the textures, all of which have to fit in video
  memory at once.

## It does not grade

Nothing here is wrong in the abstract. A 400,000 triangle model is right for a
cinematic and hopeless for a crowd, so the first thing you tell periksa is
what the thing is **for**:

| | |
|---|---|
| **Hero character** | the one the camera looks at — about 60,000 triangles |
| **Character** | someone in the world — about 20,000 |
| **Prop** | a crate, a lamp, a sword — about 5,000 |
| **Background** | far away, or fifty of them at once — about 1,500 |

The same model passes as a hero and fails as scenery, and the test suite
asserts exactly that.

Every finding says **what** it found, **why** it matters, and **what to do**.
Things that are already fine are folded away, because they are reassurance
rather than news.

## And it shows you

The model stands on a grid ruled in metres while the findings sit beside it.
Half of what periksa says is about size and where the origin sits, and the
only way to believe those is to see the thing on a floor.

## Tests

```bash
tests/run.sh
```

14 checks plus 17 in the browser, and none of them needs Blender. The suite
**builds broken models on purpose** — a real `.glb` with one thing wrong with
it, made by editing the description at the front — and checks each fault is
caught: a model exported in centimetres, one a thousand times too small, one
with its UVs removed. It also checks periksa measures the paladin to the same
centimetre jaring does, because two tools disagreeing about a model's size is
worse than either of them being silent.

A checker that is confidently wrong is worse than no checker, because it is
believed.
