"""
Turn one photograph into a material.

Texturelabs gives a colour photograph and nothing else - no normal map, no
roughness map, no height. That is why a boneka surface used to look like a
picture painted on plastic: the *colour* varied but the *light* did not, and
light is most of what tells you a surface is real.

Everything below is derived from the one image:

  detail    the greyscale, squeezed towards white, multiplied over the colour
  normal    the slope of that greyscale, so the light catches the relief
  rough     dark and rough go together on most real surfaces, so roughness is
            largely the inverse of brightness, mapped into a per-surface range

None of it is a real measurement. A height map guessed from a photograph's
brightness is wrong wherever the photograph had a shadow or a highlight in it,
and it will happily read a dark stain as a dent. It is still far better than a
constant, which is what was there before.

Run directly to preview what a surface will look like:
    python3 tools/pbr.py textures/source/Texturelabs_Metal_126S.jpg metal
"""

import os
import sys

import numpy as np
from PIL import Image, ImageOps

# (detail low, detail high, roughness low, roughness high, metallic)
# Detail is how hard the colour is pushed about; roughness is the window the
# surface lives in - polished metal is narrow and low, bare soil is high and
# wide; metallic is flat per surface because these photographs cannot tell us.
SURFACES = {
    "detail":   (0.84, 1.05, 0.55, 0.80, 0.0),
    "fabric":   (0.78, 1.06, 0.70, 0.95, 0.0),
    "leather":  (0.68, 1.06, 0.45, 0.75, 0.0),
    "metal":    (0.62, 1.10, 0.30, 0.72, 0.80),
    "wood":     (0.62, 1.08, 0.40, 0.72, 0.0),
    "stone":    (0.60, 1.10, 0.55, 0.88, 0.0),
    "concrete": (0.68, 1.08, 0.62, 0.92, 0.0),
    "brick":    (0.58, 1.10, 0.60, 0.90, 0.0),
    "soil":     (0.64, 1.08, 0.72, 0.96, 0.0),
}

# How much relief to read into each surface. Fabric is nearly flat; brick and
# soil are not.
RELIEF = {"detail": 0.35, "fabric": 0.55, "leather": 0.60, "metal": 0.45,
          "wood": 0.70, "stone": 1.00, "concrete": 0.65, "brick": 1.20,
          "soil": 1.00}


def _grey(path, size=1024):
    im = Image.open(path).convert("L")
    im.thumbnail((size, size), Image.LANCZOS)
    return ImageOps.autocontrast(im, cutoff=2)


def detail_map(grey, low, high):
    """The multiply map: grey, squeezed into a narrow band below white."""
    a = np.asarray(grey, dtype=np.float32) / 255.0
    a = (low + (high - low) * a) / high
    return Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8))


def normal_map(grey, strength):
    """
    Slope of the greyscale, as a tangent-space normal.

    The gradient is taken with a Sobel pair and the result normalised, which
    is the standard height-to-normal trick. Blurring first matters: JPEG noise
    read as relief looks like the surface is covered in grit.
    """
    from PIL import ImageFilter

    a = np.asarray(grey.filter(ImageFilter.GaussianBlur(1.1)),
                   dtype=np.float32) / 255.0
    dx = np.zeros_like(a)
    dy = np.zeros_like(a)
    dx[:, 1:-1] = (a[:, 2:] - a[:, :-2]) * 0.5
    dy[1:-1, :] = (a[2:, :] - a[:-2, :]) * 0.5

    nx = -dx * strength * 8.0
    ny = -dy * strength * 8.0
    nz = np.ones_like(a)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([(nx / length * 0.5 + 0.5),
                    (ny / length * 0.5 + 0.5),
                    (nz / length * 0.5 + 0.5)], axis=-1)
    return Image.fromarray(np.clip(rgb * 255, 0, 255).astype(np.uint8))


def rough_map(grey, low, high):
    """
    Darker tends to mean rougher: a worn, dirty or pitted patch scatters light
    and a polished one does not. Inverting brightness into a per-surface window
    is crude but it breaks up the flat specular, which is the thing that reads
    as plastic.
    """
    from PIL import ImageFilter

    a = np.asarray(grey.filter(ImageFilter.GaussianBlur(2.0)),
                   dtype=np.float32) / 255.0
    r = high - (high - low) * a
    return Image.fromarray(np.clip(r * 255, 0, 255).astype(np.uint8))


def build(source, surface, out_dir, size=1024):
    """Write the three maps for one photograph. Returns their paths."""
    low, high, r_low, r_high, metallic = SURFACES.get(surface,
                                                      SURFACES["detail"])
    grey = _grey(source, size)
    stem = os.path.splitext(os.path.basename(source))[0]
    os.makedirs(out_dir, exist_ok=True)

    made = {"metallic": metallic}
    for kind, image in (
            ("detail", detail_map(grey, low, high)),
            ("normal", normal_map(grey, RELIEF.get(surface, 0.5))),
            ("rough", rough_map(grey, r_low, r_high))):
        path = os.path.join(out_dir, "%s_%s_%s.png" % (surface, stem, kind))
        image.save(path, "PNG", optimize=True)
        made[kind] = path
    return made


if __name__ == "__main__":
    src = sys.argv[1]
    surface = sys.argv[2] if len(sys.argv) > 2 else "detail"
    out = build(src, surface, "/tmp/pbr-preview")
    for k, v in out.items():
        print("%-9s %s" % (k, v))
