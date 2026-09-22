"""
Reference pictures — look at the real thing before trusting your own eye.

boneka has fetched reference photographs from Wikimedia Commons since it was
built, to check a model against the animal it is meant to be. Animating needs
the same thing and more of it: a walk cycle is not a pose, it is a sequence,
and the question is never "what does a walking person look like" but "where is
the far leg on frame six".

So this does two searches rather than one.

    photos    ordinary photographs of the subject, as boneka has always done
    motion    frame-by-frame motion studies

The motion studies are the interesting half. Eadweard Muybridge photographed
humans and animals in motion in the 1880s — walking, running, jumping,
climbing, boxing, dancing, and horses, dogs, cats, elephants and buffalo in
stride — shot frame by frame at a time when nobody knew what a galloping horse
actually did with its legs. The plates are long out of copyright and Wikimedia
Commons holds them, including a great many already assembled into animated
GIFs. They are still the reference animators are taught from, and a GIF is a
frame sequence already: it can be stepped alongside a timeline and played back
as a flipbook without anything having to be guessed.

Nothing here needs a key or an account. Everything is cached on disk, because
Commons rate-limits politely and then abruptly — this was written after
walking into a 429.
"""

import io
import json
import os
import re
import time
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, "Documents", "bengkel", ".refs")
CACHE_AGE = 60 * 60 * 24 * 7        # a week; these are 140-year-old photographs

COMMONS = "https://commons.wikimedia.org/w/api.php"
IMAGE_HOSTS = ("upload.wikimedia.org", "thumb.wikimedia.org")
AGENT = "bengkel/1.0 (local 3D tool; contact: local user)"

# Commons ranks a chicken egg and a chicken soup as highly as a chicken, so
# the obvious wrong answers are dropped rather than shown as reference.
UNHELPFUL = ("egg", "soup", "meat", "recipe", "cooked", "roast", "dish",
             "logo", "map", "coat of arms", "stamp", "flag of", "diagram",
             "chart", "seal of", "emblem", "sign of", "icon", "nugget",
             "curry", "fried", "postcard", "banknote", "coin")

# Words that mean somebody has already assembled the plate into a sequence.
ANIMATED = ("animated", "animation", "loop", "cycle", "zoopraxi")


def _cache_path(kind, key):
    safe = re.sub(r"[^a-z0-9]+", "-", key.lower()).strip("-")[:70]
    return os.path.join(CACHE, "%s-%s.json" % (kind, safe or "x"))


def _cached(kind, key):
    path = _cache_path(kind, key)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_AGE:
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _keep(kind, key, value):
    os.makedirs(CACHE, exist_ok=True)
    with open(_cache_path(kind, key), "w") as f:
        json.dump(value, f)
    return value


def _ask(term, limit):
    """One search against Commons, returning what it knows about each file."""
    query = urllib.parse.urlencode({
        "action": "query", "generator": "search", "gsrsearch": term,
        "gsrnamespace": "6", "gsrlimit": str(limit),
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": "420", "format": "json",
    })
    request = urllib.request.Request(COMMONS + "?" + query,
                                     headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=15) as response:
        doc = json.loads(response.read().decode())
    pages = ((doc.get("query") or {}).get("pages") or {}).values()
    return sorted(pages, key=lambda p: p.get("index", 99))


def _describe(page):
    title = page.get("title", "")[5:]                  # drop the "File:" prefix
    info = (page.get("imageinfo") or [{}])[0]
    meta = info.get("extmetadata") or {}
    thumb = (info.get("thumburl") or "").split("?")[0]  # drop the tracking tail
    if not thumb:
        return None
    lowered = title.lower()
    return {
        "id": title,
        "title": os.path.splitext(title)[0].replace("_", " "),
        "thumb": thumb,
        "full": info.get("url", ""),
        "page": info.get("descriptionurl", ""),
        "mime": info.get("mime", ""),
        "width": info.get("width", 0),
        "height": info.get("height", 0),
        "bytes": info.get("size", 0),
        "licence": (meta.get("LicenseShortName") or {}).get("value", ""),
        "credit": re.sub(r"<[^>]+>", "",
                         (meta.get("Artist") or {}).get("value", ""))[:70],
        # A GIF is a sequence already — it can be stepped and flipped through
        # without anything being guessed about where one frame ends.
        "sequence": info.get("mime") == "image/gif",
        "muybridge": "muybridge" in lowered or "zoopraxi" in lowered,
    }


def motion(term, limit=12):
    """Frame-by-frame motion studies of a movement.

    Muybridge first, because those are what an animator is actually after, and
    the sequences before the single plates — a walk cycle you can step through
    beats a photograph of somebody mid-stride.
    """
    held = _cached("motion", term)
    if held is not None:
        return held

    seen, out = set(), []
    for phrase in ("Muybridge %s animated" % term,
                   "Muybridge %s" % term,
                   "%s animation sequence" % term):
        try:
            pages = _ask(phrase, limit * 2)
        except Exception:
            continue
        for page in pages:
            item = _describe(page)
            if not item or item["id"] in seen:
                continue
            lowered = item["title"].lower()
            if any(word in lowered for word in UNHELPFUL):
                continue
            seen.add(item["id"])
            item["kind"] = "motion"
            out.append(item)
        if len(out) >= limit * 2:
            break

    # Sequences first, then Muybridge plates, then the rest. Sorting rather
    # than filtering: a still plate is real reference when no GIF exists, and
    # for some movements none does.
    out.sort(key=lambda i: (not i["sequence"],
                            not i["muybridge"],
                            not any(w in i["title"].lower() for w in ANIMATED)))
    return _keep("motion", term, out[:limit])


def photos(term, limit=12):
    """Ordinary photographs of the subject, the way boneka has always done it."""
    held = _cached("photo", term)
    if held is not None:
        return held

    try:
        pages = _ask("%s filetype:bitmap" % term, limit * 4)
    except Exception:
        return []

    out = []
    for page in pages:
        item = _describe(page)
        if not item:
            continue
        if any(word in item["title"].lower() for word in UNHELPFUL):
            continue
        item["kind"] = "photo"
        out.append(item)
        if len(out) >= limit:
            break
    return _keep("photo", term, out)


def look(term, kind="all", limit=12):
    """Both searches, or one of them."""
    term = (term or "").strip()
    if not term:
        return []
    if kind == "motion":
        return motion(term, limit)
    if kind == "photo":
        return photos(term, limit)
    # Motion first: this is a reference panel for animating, and a walk cycle
    # is more use than a photograph of a pavement.
    return motion(term, limit) + photos(term, limit)


# --------------------------------------------------------------------------
# getting the picture itself
# --------------------------------------------------------------------------

def fetch(url, timeout=30):
    """Fetched by the server, never by the page.

    The browser then makes no third-party request, so the origin rule stays
    true for everything on screen and Commons never learns what he is
    animating.
    """
    host = urllib.parse.urlparse(url).netloc
    if host not in IMAGE_HOSTS:
        raise ValueError("that is not a Wikimedia image")
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(), response.headers.get("Content-Type", "image/jpeg")


def keep_local(url, folder, name=None):
    """Save a picture beside the work, so a pinned reference survives Commons.

    A reference that lives at a URL is a reference that is gone when the link
    rots or the laptop is on a train. Pinning one writes it down.
    """
    body, ctype = fetch(url)
    os.makedirs(folder, exist_ok=True)
    ending = {"image/gif": ".gif", "image/png": ".png",
              "image/jpeg": ".jpg", "image/webp": ".webp"}.get(ctype.split(";")[0], ".jpg")
    stem = name or os.path.splitext(os.path.basename(urllib.parse.urlparse(url).path))[0]
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem)[:60].strip("-") or "reference"
    path = os.path.join(folder, stem + ending)
    with open(path, "wb") as f:
        f.write(body)
    return path


def split_frames(path, out_folder, limit=64):
    """Pull an animated GIF apart into its frames.

    Returns the frames in order, or an empty list for anything that is not a
    sequence. This is what lets a reference be stepped alongside the timeline
    and played as a flipbook: frame six of the reference beside frame six of
    his own animation.

    Pillow is imported here rather than at the top so that everything else in
    this file still works on a machine without it.
    """
    try:
        from PIL import Image, ImageSequence
    except ImportError:
        return []

    try:
        image = Image.open(path)
    except Exception:
        return []
    if getattr(image, "n_frames", 1) <= 1:
        return []

    os.makedirs(out_folder, exist_ok=True)
    stem = os.path.splitext(os.path.basename(path))[0]
    out = []
    for index, frame in enumerate(ImageSequence.Iterator(image)):
        if index >= limit:
            break
        # Converted through RGB because a GIF's palette can carry a
        # transparency index that comes out black otherwise.
        target = os.path.join(out_folder, "%s-%03d.png" % (stem, index))
        frame.convert("RGB").save(target, "PNG", optimize=True)
        out.append(target)
    return out
