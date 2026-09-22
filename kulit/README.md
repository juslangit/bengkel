# kulit

**Give a model its colour and its surface, one part at a time.**

*Kulit* is skin. This is the Dress stage: jaring hands over a clean grey mesh
with no colour at all, and pasar hands over a download whose materials are
twelve slots of somebody else's idea. Here a model gets a surface it chose.

```bash
kulit              # on its own
bengkel            # or the fourth door in the workshop
```

## One row per part

Open a model and every mesh in it gets a row: its name, how many triangles it
is, a colour and a material. Click a part **on the model** and its row is
selected — which is the way round you reach for when the parts are called
`Mesh_0` and `Mesh_1`.

Nine materials: metal, wood, fabric, leather, stone, concrete, brick, soil,
and plain. Each row also has a tiling slider — how many times the surface
repeats across that part.

A material with no photograph behind it is **greyed out rather than offered**,
because choosing it would silently give you flat colour and nothing would say
so.

## Colour now, surface when you press the button

The colour appears on the model the instant you click a swatch. Choosing a
colour by imagining it is not choosing.

The material does not. Deriving a normal map and a roughness map from a
photograph is image work that belongs elsewhere, and faking a plausible
preview would be worse than being plain about the split — so it is: **colour
now, surface when you press Dress it.**

Colours come from the palettes boneka already has, so the two tools agree
about colour rather than each having their own idea of it.

## What a material is made of

Nothing here derives maps. boneka's `tools/pbr.py` already turns one
Texturelabs photograph into three, and its numbers were arrived at by looking
at real surfaces, so kulit runs that rather than growing a second version:

| | |
|---|---|
| **detail** | the greyscale, squeezed towards white, multiplied over the colour |
| **normal** | the slope of that greyscale, so the light catches the relief |
| **rough** | dark and rough go together, so roughness is largely the inverse of brightness |

It runs in **system Python, before Blender starts**, because it is written in
Pillow and numpy and Blender ships its own Python without either. Blender is
handed three finished file paths.

In the material, one image and one constant colour go into a Multiply, into
Base Color. That exact shape is what Blender's glTF exporter reads as
`baseColorFactor × baseColorTexture` — anything more elaborate silently does
not survive the export, and the model comes back grey.

## The licence, which matters here more than anywhere

Texturelabs is free to use commercially and asks for no credit, but is
specific about 3D:

> *Texturelabs resources cannot ... be distributed or sold as part of a 3D
> model in a way that allows a third party to use, download, extract or access
> the Texturelabs asset.*

**Using this model inside a finished game is explicitly allowed. Handing
someone the `.glb` is not.**

So every dressed export writes a `WHAT-IS-IN-IT.md` beside itself with the
full wording, and the page says it on the result panel. The obligation travels
with the file rather than relying on anyone remembering it. **Never commit a
dressed model to a public repository.**

## Where things land

```
~/Documents/bengkel/kulit/out/<name>/
    <name>.glb            the dressed model, textures inside it
    <name>.blend          the same thing to carry on by hand
    WHAT-IS-IN-IT.md      what is in it and what may be done with it
```

From here it goes on to **gerak** with one press.

## Tests

```bash
tests/run.sh           everything
tests/run.sh --quick   skip the Blender run
```

14 checks plus 14 in the browser. The ones that matter read the exported
`.glb` itself rather than trusting the exit code: that the `baseColorFactor`
is not plain white (which is what a colour lost on export looks like), that
the detail map and the normal map are really embedded, that a part nobody
named is refused rather than quietly painted, and that the licence restriction
is on disk beside the result.
