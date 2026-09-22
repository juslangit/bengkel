# pasar

**One search box over three libraries. Everything you download lands in the
workshop, with a note saying where it came from.**

A *pasar* is a market — the place you go for raw material before you make
anything. This is the first stop in the pipeline: find a model, an HDRI or a
surface, bring it home, and hand it straight to the next tool.

```bash
pasar              # on its own
bengkel            # or as the first door in the workshop
```

## What it searches

| | | |
|---|---|---|
| **Sketchfab** | 3D models | downloadable ones only — the rest cannot leave the site |
| **Poly Haven** | HDRIs | for lighting a scene; CC0, so anything goes |
| **Texturelabs** | 2,035 surfaces | free to use commercially, **never** redistributable |

All three at once, or one at a time.

## Why it exists

Each of those three already had a command-line tool on this machine —
`sketchfab`, `polyhaven`, `texturelabs`. They worked, but one at a time, in a
terminal, with no pictures. pasar doesn't reimplement any of them: it loads
them as modules and calls their functions, so there is still only one
description of how to talk to Sketchfab. What it adds is a face — all three
searched together, thumbnails, and a download that goes where the workshop can
find it.

## The licence is on the card

Every result shows its licence **before** you download, and anything marked
**NonCommercial** or **NoDerivs** is flagged in amber — those cannot go into
something you sell.

Every download writes a `WHERE-IT-CAME-FROM.md` beside the file, recording the
source, the author, the licence and the page. Six months later that note is the
only way to know what you are allowed to do with the thing, so it is written
every time and never left to memory. Keep it with the asset.

One rule worth repeating, because it is the easiest to break by accident:
**a Texturelabs file must never be shipped inside a model you hand to someone
else.** Bake it into your own maps and ship those.

## Where things land

```
~/Documents/bengkel/pasar/out/<source>/<name>/
```

A `.glb` from here opens in **gerak** with one press — pasar offers the hand-off
when it is running inside bengkel.

## Tests

```bash
tests/run.sh
```

16 checks: the token and origin guards, all three libraries reachable, a
licence on every single result, the NonCommercial rule, and the note beside a
download. The searches need the internet; without it those are skipped rather
than failed.
