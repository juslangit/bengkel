#!/usr/bin/env python3
"""
pasar — the market.

The first stage of the pipeline: getting the raw material. One search box over
three libraries that were already reachable from this machine, but only from a
terminal and only one at a time:

    Sketchfab     3D models, free and downloadable
    Poly Haven    HDRIs, for lighting a scene
    Texturelabs   2,035 surfaces, free for commercial use

None of the talking-to-them is written here. Each of those has a command-line
tool on the PATH that already knows how to search it, how to authenticate, and
where a download should land — so pasar loads those tools as modules and calls
their functions. One implementation of "how to talk to Sketchfab" rather than
two that drift apart.

What pasar adds is a face: all three searched at once, thumbnails, and a
download that goes into the workshop and can be handed straight to the next
tool without going through Finder.
"""

import importlib.machinery
import importlib.util
import json
import os
import pathlib
import shutil
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "common"))

from serve import Tool, HOME, SAFE_NAME     # noqa: E402

tool = Tool("pasar", __file__, "@@PASAR-READY@@", title="pasar")


# --------------------------------------------------------------------------
# the three libraries, borrowed rather than reimplemented
# --------------------------------------------------------------------------

def load_cli(name):
    """Load one of the command-line tools as a module.

    They have no .py on the end because they are meant to be typed, so the
    loader is told the path explicitly. If one is missing, pasar carries on
    without that library rather than refusing to start — the other two are
    still useful.
    """
    path = os.path.join(HOME, ".local", "bin", name)
    if not os.path.exists(path):
        tool.log("no %s on the PATH; that library will be unavailable" % name)
        return None
    try:
        loader = importlib.machinery.SourceFileLoader(name, path)
        spec = importlib.util.spec_from_loader(name, loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return module
    except Exception as err:
        tool.log("could not load %s: %s" % (name, err))
        return None


SKETCHFAB = load_cli("sketchfab")
POLYHAVEN = load_cli("polyhaven")
TEXTURELABS = load_cli("texturelabs")


# --------------------------------------------------------------------------
# searching
# --------------------------------------------------------------------------

def search_sketchfab(query, limit):
    """Downloadable models only — the rest cannot leave the website."""
    if not SKETCHFAB:
        return []
    token = SKETCHFAB.load_token()
    found = SKETCHFAB.api("/search", token, type="models", q=query,
                          downloadable="true", count=limit, sort_by="-likeCount")
    out = []
    for item in found.get("results", []):
        images = (item.get("thumbnails") or {}).get("images") or []
        # Smallest picture that is still worth looking at: the list shows
        # dozens at once and a 2048px thumbnail each would be absurd.
        images = sorted(images, key=lambda i: i.get("width") or 0)
        thumb = next((i["url"] for i in images if (i.get("width") or 0) >= 400),
                     images[-1]["url"] if images else "")
        licence = (item.get("license") or {}).get("label") or "unknown"
        out.append({
            "source": "sketchfab",
            "id": item["uid"],
            "kind": "model",
            "title": item.get("name") or "untitled",
            "by": (item.get("user") or {}).get("displayName") or "",
            "thumb": thumb,
            "page": item.get("viewerUrl") or "",
            "licence": licence,
            # Anything that says NonCommercial or NoDerivs cannot go in
            # something he might sell, and that is worth seeing before the
            # download rather than after.
            "safe": "NonCommercial" not in licence and "NoDerivs" not in licence,
            "detail": "%s faces" % f"{item.get('faceCount') or 0:,}",
            "animated": (item.get("animationCount") or 0) > 0,
        })
    return out


def search_polyhaven(query, limit):
    if not POLYHAVEN:
        return []
    assets = POLYHAVEN.api("/assets", type="hdris")
    query = query.lower().strip()
    out = []
    for key, item in assets.items():
        haystack = " ".join([key, item.get("name", "")]
                            + list(item.get("categories") or [])
                            + list(item.get("tags") or [])).lower()
        if query and query not in haystack:
            continue
        out.append({
            "source": "polyhaven",
            "id": key,
            "kind": "hdri",
            "title": item.get("name") or key,
            "by": ", ".join((item.get("authors") or {}).keys()),
            "thumb": "https://cdn.polyhaven.com/asset_img/thumbs/%s.png?width=340" % key,
            "page": "https://polyhaven.com/a/%s" % key,
            "licence": "CC0",
            "safe": True,
            "detail": ", ".join((item.get("categories") or [])[:3]),
            "downloads": item.get("download_count") or 0,
        })
    out.sort(key=lambda i: -i.get("downloads", 0))
    return out[:limit]


def search_texturelabs(query, limit):
    if not TEXTURELABS:
        return []
    index = TEXTURELABS.index()
    entries = index.values() if isinstance(index, dict) else index
    query = query.lower().strip()
    out = []
    for entry in entries:
        slug = entry.get("slug", "")
        if query and query not in (slug + " " + entry.get("category", "")).lower():
            continue
        out.append({
            "source": "texturelabs",
            "id": slug,
            "kind": "texture",
            "title": entry.get("name") or slug,
            "by": "Texturelabs",
            "thumb": entry.get("thumb") or "",
            "page": entry.get("page") or "",
            "licence": "free for commercial use, not redistributable",
            "safe": True,
            "detail": entry.get("category", ""),
        })
        if len(out) >= limit:
            break
    return out


SEARCHERS = {
    "sketchfab": search_sketchfab,
    "polyhaven": search_polyhaven,
    "texturelabs": search_texturelabs,
}


@tool.get("/api/sources")
def sources(query):
    """Which libraries are reachable, so the page can say so rather than
    offering a search that will come back empty."""
    return {"sources": [
        {"id": "sketchfab", "name": "Sketchfab", "kind": "models",
         "ready": SKETCHFAB is not None, "accent": "#4ea3f5"},
        {"id": "polyhaven", "name": "Poly Haven", "kind": "HDRIs",
         "ready": POLYHAVEN is not None, "accent": "#9ccb3b"},
        {"id": "texturelabs", "name": "Texturelabs", "kind": "textures",
         "ready": TEXTURELABS is not None, "accent": "#c78cf0"},
    ]}


@tool.get("/api/search")
def search(query):
    wanted = query.get("q", "").strip()
    where = query.get("where", "all")
    limit = max(1, min(int(query.get("n") or 24), 60))

    results, problems = [], []
    for name, fn in SEARCHERS.items():
        if where not in ("all", name):
            continue
        try:
            results.extend(fn(wanted, limit))
        except Exception as err:
            problems.append("%s: %s" % (name, err))
            tool.log("%s search failed: %s" % (name, err))

    return {"results": results, "problems": problems, "query": wanted}


# --------------------------------------------------------------------------
# bringing something home
# --------------------------------------------------------------------------

@tool.post("/api/get")
def get(body):
    """Download one thing into the workshop.

    Everything lands under ~/Documents/bengkel/pasar/out/<source>/<name>/ with
    whatever note about its licence the library's own tool writes, so where a
    thing came from is never lost.
    """
    source = body.get("source")
    ident = body.get("id")
    if source not in SEARCHERS or not ident:
        return {"ok": False, "problem": "nothing to fetch"}

    folder = os.path.join(tool.out, source,
                          SAFE_NAME.sub("-", str(ident).lower()).strip("-"))
    os.makedirs(folder, exist_ok=True)

    try:
        if source == "sketchfab":
            token = SKETCHFAB.load_token()
            links = SKETCHFAB.api("/models/%s/download" % ident, token)
            url = (links.get("glb") or links.get("gltf") or {}).get("url")
            if not url:
                return {"ok": False, "problem": "Sketchfab offered no glb for that one"}
            target = os.path.join(folder, "%s.glb" % ident)
            urllib.request.urlretrieve(url, target)
            note(folder, source, ident, body.get("title"), body.get("by"),
                 body.get("licence"), body.get("page"))
            got = target

        elif source == "polyhaven":
            files = POLYHAVEN.api("/files/%s" % ident)
            hdris = files.get("hdri") or {}
            # 2k is the size that is worth having without being absurd: 4k and
            # up are hundreds of megabytes for a background.
            size = "2k" if "2k" in hdris else sorted(hdris)[0]
            url = (hdris[size].get("hdr") or hdris[size].get("exr") or {}).get("url")
            if not url:
                return {"ok": False, "problem": "no downloadable file for that HDRI"}
            target = os.path.join(folder, os.path.basename(urllib.parse.urlparse(url).path))
            urllib.request.urlretrieve(url, target)
            note(folder, source, ident, body.get("title"), body.get("by"), "CC0",
                 body.get("page"))
            got = target

        else:  # texturelabs
            index = TEXTURELABS.index()
            entries = index if isinstance(index, dict) else {e["slug"]: e for e in index}
            entry = entries.get(ident)
            if not entry:
                return {"ok": False, "problem": "that texture is not in the index"}
            # texturelabs' own downloader works in pathlib, not strings.
            TEXTURELABS.download(entry, pathlib.Path(folder), quiet=True)
            note(folder, source, ident, body.get("title"), "Texturelabs",
                 "free for commercial use, credit not required — but NOT "
                 "redistributable, so never ship the texture file inside a model",
                 entry.get("page"))
            files = [f for f in os.listdir(folder)
                     if not f.startswith(".") and not f.endswith(".md")]
            got = os.path.join(folder, files[0]) if files else folder

    except Exception as err:
        tool.log("could not fetch %s/%s: %s" % (source, ident, err))
        return {"ok": False, "problem": str(err)}

    tool.permit(got)
    tool.log("got", os.path.basename(got))
    return {
        "ok": True,
        "path": got,
        "folder": folder,
        "shown": got.replace(HOME, "~"),
        "bytes": os.path.getsize(got) if os.path.isfile(got) else 0,
        "model": got.lower().endswith((".glb", ".gltf")),
    }


def note(folder, source, ident, title, by, licence, page):
    """Write down where a thing came from, beside it.

    Some of these licences require attribution and some forbid selling the
    result. Six months later the only way to know which is a note like this,
    so it is written every time and never left to memory.
    """
    with open(os.path.join(folder, "WHERE-IT-CAME-FROM.md"), "w") as f:
        f.write("# %s\n\n" % (title or ident))
        f.write("- **From:** %s\n" % source)
        f.write("- **By:** %s\n" % (by or "unknown"))
        f.write("- **Licence:** %s\n" % (licence or "unknown"))
        if page:
            f.write("- **Page:** %s\n" % page)
        f.write("\nFetched by pasar into the workshop. Keep this file with the "
                "asset: it is the only record of what you are allowed to do "
                "with it.\n")


@tool.get("/api/mine")
def mine(query):
    """Everything pasar has already brought home."""
    out = []
    for source in sorted(os.listdir(tool.out)) if os.path.isdir(tool.out) else []:
        base = os.path.join(tool.out, source)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            folder = os.path.join(base, name)
            if not os.path.isdir(folder):
                continue
            files = [f for f in os.listdir(folder) if not f.startswith(".")
                     and not f.endswith(".md")]
            if not files:
                continue
            best = next((f for f in files if f.lower().endswith((".glb", ".gltf"))),
                        files[0])
            full = os.path.join(folder, best)
            tool.permit(full)
            out.append({
                "source": source,
                "id": name,
                "title": name,
                "path": full,
                "shown": full.replace(HOME, "~"),
                "model": best.lower().endswith((".glb", ".gltf")),
                "bytes": os.path.getsize(full),
            })
    out.sort(key=lambda i: -os.path.getmtime(i["path"]))
    return {"items": out}


if __name__ == "__main__":
    sys.exit(tool.run())
