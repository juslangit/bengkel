"""
Palettes.

A model built from one hand-made palette hangs together in a way that a body
colour plus two multiplications never does. This module does two things: it
holds a handful of moods that need no network at all, and it snaps every colour
in a finished plan onto whatever palette it is given.

Matching is done in **Oklab**, not in RGB. Nearest-in-RGB is the obvious way and
it is wrong: it will happily swap a mid green for a dark blue because the
numbers are close, while your eye sees nothing in common. Oklab is laid out so
that equal distances look like equal differences, which is the whole point of a
palette.

Two rules on top of nearest-colour, both there because the naive version looked
bad:

  * **Keep things distinct.** If the body and the trim both land on the same
    palette entry the model goes flat, so the second one is pushed to its next
    nearest.
  * **Keep the lightness order.** A shade that was darker than its base has to
    stay darker than its base, or the shading inverts and the form reads
    inside out.

No Blender here, so it can be read and tested with ordinary Python.
"""

import re

# --------------------------------------------------------------------------
# moods that are always available, network or no network
# --------------------------------------------------------------------------

MOODS = {
    "pastel": ["fdf3f7", "f7c6d0", "f6dfb4", "d9edc2", "b8e2e8", "c9c7e8",
               "e5bfd7", "9a93b8", "6f6a8d", "3d3a52"],
    "muted": ["e8e2d6", "c9bfae", "a89c88", "8a7f6d", "6b6255", "8b7a6b",
              "6d7a6a", "4e5a52", "3a3f3c", "23262a"],
    "earthy": ["f0e2c8", "d9bd8d", "bf9761", "9c6f3f", "7a5230", "5a3a22",
               "6b7a2f", "4a5a28", "33402a", "1f2419"],
    "neon": ["0b0b14", "1b1035", "3a0ca3", "7209b7", "f72585", "ff477e",
             "ff8fab", "06d6a0", "1de4bd", "faff81"],
    "monochrome": ["ffffff", "d9dde1", "b4bac1", "8e959e", "6b727b", "4d545c",
                   "353b42", "23272c", "141619", "060708"],
    "sunset": ["2b1b3d", "5c2a55", "97386b", "d4506b", "f2795f", "fca566",
               "fdd08a", "ffeec2", "8fb4c9", "3f6480"],
    "forest": ["e7f0d4", "b9d18a", "82ab55", "55803a", "3a5c2c", "26401f",
               "6b4f2a", "4a3520", "2d2317", "13180f"],
    "ice": ["ffffff", "e4f4fb", "bfe4f5", "8fcbe8", "5aa8d1", "3a7fae",
            "2b5c85", "1e3f5e", "14283c", "0a1420"],
    "rust": ["f2e3c6", "d9a86c", "bf7340", "8c4a26", "5e2f1a", "3a1f13",
             "7a7f75", "545a52", "34382f", "1a1c17"],
    "candy": ["fff5fb", "ffd1e8", "ff9ecd", "ff6fae", "e04f8f", "a8377a",
              "6f2660", "8fe3e8", "58c4cc", "2c6f79"],
}

_SLUG = re.compile(r"[^a-z0-9]+")


def known_moods():
    return sorted(MOODS)


def mood_in(words):
    """A built-in mood named anywhere in the prompt."""
    for w in words:
        if w in MOODS:
            return w
    return None


def normalise(colors):
    """Accept '#ab12cd' or 'ab12cd', drop anything that is not a colour."""
    out = []
    for c in colors or []:
        c = str(c).strip().lstrip("#").lower()
        if re.fullmatch(r"[0-9a-f]{6}", c):
            out.append("#" + c)
    return out


def slug(name):
    return _SLUG.sub("-", (name or "").strip().lower()).strip("-")


# --------------------------------------------------------------------------
# colour maths
# --------------------------------------------------------------------------

def _to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def oklab(hex_color):
    """sRGB hex to Oklab, where equal distances look like equal differences."""
    h = hex_color.lstrip("#")
    r, g, b = (_to_linear(int(h[i:i + 2], 16) / 255.0) for i in (0, 2, 4))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = (v ** (1.0 / 3.0) if v > 0 else -((-v) ** (1.0 / 3.0))
                  for v in (l, m, s))
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def distance(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def ranked(target, palette_lab):
    """Palette indices, nearest first."""
    lab = oklab(target)
    return sorted(range(len(palette_lab)),
                  key=lambda i: distance(lab, palette_lab[i]))


# --------------------------------------------------------------------------
# snapping a whole plan
# --------------------------------------------------------------------------

def snap_plan(steps, colors):
    """
    Put every colour in a plan onto the palette, keeping the model readable.

    Two things have to be true at once, and they pull against each other:

      * **distinct** - no two of the model's colours may land on the same
        swatch, or the model goes flat
      * **in order** - a colour that started darker than another must end
        darker than it, or the shading inverts and the form reads inside out

    Both hold if the model's colours are sorted by lightness, the palette is
    sorted by lightness, and each colour is given a *strictly later* swatch
    than the one before it. That leaves a choice of which swatches to skip,
    and the choice is made to keep the colours as close to the originals as
    possible - which is a shortest-path over a grid, so it is solved exactly
    rather than guessed at.

    Two greedier versions came first and both failed: nearest-swatch-then-fix
    kept undoing its own de-duplication, and a one-pass greedy walk let an
    early dark colour take a light swatch and then ran out of palette.

    Returns a map of the original colour to its replacement, and edits the
    steps in place.
    """
    colors = normalise(colors)
    if len(colors) < 2:
        return {}

    originals = []
    for st in steps:
        if st["color"] not in originals:
            originals.append(st["color"])
    originals.sort(key=lambda c: oklab(c)[0])       # darkest first

    order = sorted(range(len(colors)), key=lambda i: oklab(colors[i])[0])
    swatches = [colors[i] for i in order]
    chosen = _best_run(originals, swatches)

    mapping = {src: swatches[j] for src, j in zip(originals, chosen)}
    for st in steps:
        st["color"] = mapping.get(st["color"], st["color"])
    return mapping


def _best_run(sources, swatches):
    """
    Pick one swatch per colour, strictly increasing through the palette, with
    the smallest total difference. A shortest path over (colour, swatch),
    filled in one row at a time.
    """
    n, m = len(sources), len(swatches)
    if n > m:                                   # more colours than swatches:
        return _nearest_run(sources, swatches)  # share, and keep the order

    source_lab = [oklab(c) for c in sources]
    swatch_lab = [oklab(c) for c in swatches]
    cost = [[distance(source_lab[i], swatch_lab[j]) for j in range(m)]
            for i in range(n)]

    INF = float("inf")
    best = [[INF] * m for _ in range(n)]
    came = [[-1] * m for _ in range(n)]
    for j in range(m):
        best[0][j] = cost[0][j]
    for i in range(1, n):
        running, argmin = INF, -1
        for j in range(m):
            if j > 0 and best[i - 1][j - 1] < running:
                running, argmin = best[i - 1][j - 1], j - 1
            if argmin >= 0:
                best[i][j] = running + cost[i][j]
                came[i][j] = argmin

    end = min(range(m), key=lambda j: best[n - 1][j])
    run = [end]
    for i in range(n - 1, 0, -1):
        run.append(came[i][run[-1]])
    return list(reversed(run))


def _nearest_run(sources, swatches):
    """Fallback when the palette is smaller than the model: nearest, in order."""
    swatch_lab = [oklab(c) for c in swatches]
    out, floor = [], 0
    for source in sources:
        near = sorted(range(len(swatches)),
                      key=lambda j: distance(oklab(source), swatch_lab[j]))
        pick = next((j for j in near if j >= floor), len(swatches) - 1)
        out.append(pick)
        floor = pick
    return out
