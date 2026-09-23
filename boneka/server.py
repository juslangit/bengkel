#!/usr/bin/env python3
"""
boneka - the local server.

It does three jobs and nothing else:

  1. keeps one Blender running in the background and talks to it in JSON,
  2. serves the page you look at and the .glb files Blender writes,
  3. pushes Blender's progress to the page as it happens, so you watch the
     model being built rather than waiting for it.

Nothing here needs installing: it is the Python that comes with macOS plus the
Blender already on the machine.

On safety: a server on localhost with no lock on it can be driven by any web
page you happen to have open, so this one checks two things on every request -
a token made fresh each run, and that the request came from this app's own
address. Neither is optional.
"""

import json
import mimetypes
import os
import queue
import secrets
import subprocess
import sys
import threading
import time
import re
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(HERE, "web")
CLIPS = os.path.join(HERE, "animations")
BLENDER = os.environ.get(
    "BONEKA_BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")
MARK = "@@BK@@"
PORT = int(os.environ.get("BONEKA_PORT", "8777"))

# One machine-readable line at startup, so a program that launches boneka -
# sanggar does - can find out which port it settled on and what this run's
# token is, instead of scraping the human-readable log.
READY_MARK = "@@BONEKA-READY@@"
TOKEN = secrets.token_urlsafe(18)


def log(*parts):
    sys.stderr.write("[boneka] %s\n" % " ".join(str(p) for p in parts))
    sys.stderr.flush()


# --------------------------------------------------------------------------
# the Blender process
# --------------------------------------------------------------------------

class Worker:
    def __init__(self, session):
        self.session = session
        os.makedirs(session, exist_ok=True)
        self.lock = threading.Lock()
        self.listeners = []
        self.history = []
        self.ready = threading.Event()
        self.busy = False
        self.proc = None
        self.start()

    def start(self):
        if not os.path.exists(BLENDER):
            raise SystemExit(
                "Blender is not at %s - set BONEKA_BLENDER to where it is" % BLENDER)
        self.proc = subprocess.Popen(
            [BLENDER, "--background", "--factory-startup", "--python",
             os.path.join(HERE, "blender", "worker.py"), "--", self.session],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for line in self.proc.stdout:
            line = line.rstrip("\n")
            if not line.startswith(MARK):
                continue
            try:
                event = json.loads(line[len(MARK):].strip())
            except ValueError:
                continue
            if event.get("event") == "ready":
                self.ready.set()
            if event.get("event") == "idle":
                self.busy = False
            self.publish(event)
        self.publish({"event": "stopped",
                      "message": "Blender closed - restart boneka"})

    def publish(self, event):
        with self.lock:
            self.history.append(event)
            self.history[:] = self.history[-400:]
            for q in list(self.listeners):
                q.put(event)

    def subscribe(self):
        q = queue.Queue()
        with self.lock:
            self.listeners.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.listeners:
                self.listeners.remove(q)

    def send(self, message):
        if self.proc.poll() is not None:
            raise RuntimeError("Blender is not running any more")
        self.busy = True
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def stop(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


# --------------------------------------------------------------------------
# Meshy, which costs real credits and so is never called on its own
# --------------------------------------------------------------------------

def read_env_key(name):
    path = os.path.expanduser("~/.claude/.env")
    if os.environ.get(name):
        return os.environ[name]
    if not os.path.exists(path):
        return None
    for line in open(path):
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return None


def meshy_request(path, payload=None, method="GET"):
    key = read_env_key("MESHY_API_KEY")
    if not key:
        raise RuntimeError("no MESHY_API_KEY in ~/.claude/.env")
    url = "https://api.meshy.ai/openapi/" + path.lstrip("/")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": "Bearer " + key,
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def meshy_job(worker, prompt, art_style="realistic"):
    """Runs on its own thread; progress goes out on the same event stream."""
    try:
        worker.publish({"event": "meshy", "stage": "starting", "prompt": prompt})
        created = meshy_request("v2/text-to-3d", {
            "mode": "preview", "prompt": prompt, "art_style": art_style,
            "should_remesh": True, "topology": "quad", "target_polycount": 20000,
        }, method="POST")
        task_id = created.get("result") or created.get("id")
        worker.publish({"event": "meshy", "stage": "queued", "task": task_id})

        deadline = time.time() + 600
        while time.time() < deadline:
            time.sleep(4)
            task = meshy_request("v2/text-to-3d/%s" % task_id)
            status = task.get("status")
            worker.publish({"event": "meshy", "stage": status.lower(),
                            "progress": task.get("progress", 0)})
            if status == "SUCCEEDED":
                url = (task.get("model_urls") or {}).get("glb")
                if not url:
                    raise RuntimeError("Meshy finished but sent no .glb back")
                out = os.path.join(worker.session, "meshy_%s.glb" % task_id[:8])
                with urllib.request.urlopen(url, timeout=180) as r, open(out, "wb") as f:
                    f.write(r.read())
                worker.publish({"event": "meshy", "stage": "downloaded",
                                "file": os.path.basename(out)})
                worker.send({"cmd": "import", "path": out})
                return
            if status in ("FAILED", "CANCELED", "EXPIRED"):
                raise RuntimeError("Meshy job %s: %s" % (
                    status.lower(), (task.get("task_error") or {}).get("message", "")))
        raise RuntimeError("Meshy took longer than ten minutes")
    except Exception as exc:                            # noqa: BLE001
        worker.publish({"event": "error", "message": "Meshy: %s" % exc})
        worker.publish({"event": "idle", "cmd": "meshy"})


# --------------------------------------------------------------------------
# reference pictures - look at the real thing before judging the model
# --------------------------------------------------------------------------

COMMONS = "https://commons.wikimedia.org/w/api.php"
IMAGE_HOSTS = ("upload.wikimedia.org", "thumb.wikimedia.org")
AGENT = "boneka/1.0 (local 3D tool; contact: local user)"

# Commons ranks a chicken egg and a chicken soup as highly as a chicken, so
# the obvious wrong answers are dropped rather than shown as reference
UNHELPFUL = ("egg", "soup", "meat", "recipe", "cooked", "roast", "dish",
             "logo", "map", "coat of arms", "stamp", "flag of", "diagram",
             "chart", "seal of", "emblem", "skeleton of", "anatomy of",
             "sign", "icon", "nugget", "curry", "fried")


def reference_images(subject, limit=4):
    """Photographs of the real thing, from Wikimedia Commons. No key needed."""
    query = urllib.parse.urlencode({
        "action": "query", "generator": "search",
        "gsrsearch": "%s filetype:bitmap" % subject,
        "gsrnamespace": "6", "gsrlimit": str(limit * 4),
        "prop": "imageinfo", "iiprop": "url|extmetadata",
        "iiurlwidth": "420", "format": "json",
    })
    req = urllib.request.Request(COMMONS + "?" + query,
                                 headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode())

    pages = ((data.get("query") or {}).get("pages") or {}).values()
    out = []
    for page in sorted(pages, key=lambda p: p.get("index", 99)):
        title = page.get("title", "")[5:]          # drop the "File:" prefix
        lowered = title.lower()
        if any(word in lowered for word in UNHELPFUL):
            continue
        info = (page.get("imageinfo") or [{}])[0]
        thumb = (info.get("thumburl") or "").split("?")[0]   # drop the tracking tail
        if not thumb:
            continue
        meta = info.get("extmetadata") or {}
        out.append({
            "title": os.path.splitext(title)[0].replace("_", " "),
            "thumb": thumb,
            "page": info.get("descriptionurl", ""),
            "licence": (meta.get("LicenseShortName") or {}).get("value", ""),
            "credit": re.sub(r"<[^>]+>", "",
                             (meta.get("Artist") or {}).get("value", ""))[:70],
        })
        if len(out) >= limit:
            break
    return out


def fetch_thumbnail(url):
    """
    Fetched by the server, not the page, so the browser makes no third-party
    request and the origin rule stays true for everything on screen.
    """
    host = urlparse(url).netloc
    if host not in IMAGE_HOSTS:
        raise RuntimeError("that is not a Wikimedia image")
    req = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.read(), resp.headers.get("Content-Type", "image/jpeg")



# --------------------------------------------------------------------------
# palettes - the built-in moods, plus anything on Lospec
# --------------------------------------------------------------------------

LOSPEC = "https://lospec.com/palette-list"
PALETTE_CACHE = os.path.join(HERE, "palettes")

sys.path.insert(0, os.path.join(HERE, "blender"))
import palette as palettes                                 # noqa: E402


def cached_palette(name):
    path = os.path.join(PALETTE_CACHE, palettes.slug(name) + ".json")
    if os.path.exists(path):
        try:
            return json.load(open(path))
        except ValueError:
            return None
    return None


def store_palette(name, data):
    os.makedirs(PALETTE_CACHE, exist_ok=True)
    with open(os.path.join(PALETTE_CACHE, palettes.slug(name) + ".json"),
              "w") as f:
        json.dump(data, f)


def resolve_palette(name):
    """
    A built-in mood, something already fetched, or a Lospec palette. Once
    fetched it is kept on disk, so a palette you have used before keeps
    working with the network unplugged.
    """
    key = palettes.slug(name)
    if not key:
        return None
    if key in palettes.MOODS:
        return {"name": key, "source": "built in",
                "colors": palettes.normalise(palettes.MOODS[key])}
    hit = cached_palette(key)
    if hit:
        hit["source"] = "Lospec (cached)"
        return hit

    req = urllib.request.Request("%s/%s.json" % (LOSPEC, key),
                                 headers={"User-Agent": AGENT})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise RuntimeError(
                "no palette called %r - try one of %s, or search Lospec"
                % (name, ", ".join(palettes.known_moods()[:4])))
        raise RuntimeError("Lospec said %s" % exc.code)
    except urllib.error.URLError:
        raise RuntimeError("cannot reach Lospec - offline? the built-in "
                           "palettes still work")
    colors = palettes.normalise(raw.get("colors"))
    if len(colors) < 2:
        raise RuntimeError("that palette has no colours in it")
    data = {"name": raw.get("name") or key, "slug": key, "colors": colors,
            "author": raw.get("author") or "", "source": "Lospec"}
    store_palette(key, data)
    return data


def search_palettes(query, limit=12):
    """Lospec's own list, so a name can be found without leaving the app."""
    params = urllib.parse.urlencode({
        "colorNumberFilterType": "any", "page": 0,
        "tag": palettes.slug(query), "sortingType": "default"})
    req = urllib.request.Request(LOSPEC + "/load?" + params,
                                 headers={"User-Agent": AGENT})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode())
    out = []
    for p in (data.get("palettes") or [])[:limit]:
        colors = palettes.normalise(p.get("colors"))
        if len(colors) >= 2:
            out.append({"name": p.get("title") or p.get("slug"),
                        "slug": p.get("slug"), "colors": colors})
    return out



# --------------------------------------------------------------------------
# textures, from Texturelabs
#
# These are photographs, not PBR material sets - there are no normal or
# roughness maps - so they are used as a *multiply* over the colour a part
# already has. The palette still decides the colour; the texture decides that
# the surface is not perfectly flat. That keeps the two systems from fighting.
#
# Licence, which is why nothing here is ever committed: free for commercial
# use, no credit needed, but not redistributable and not to be shipped inside
# a 3D model file. https://texturelabs.org/terms/
# --------------------------------------------------------------------------

TEXTURE_DIR = os.path.join(HERE, "textures")
TEXTURELABS = "https://texturelabs.org/wp-content/uploads"

# Hand-picked. The site is full of design overlays and decorative tilework
# alongside the real surfaces - one "brick" turned out to be Moroccan zellij,
# one "fabric" a photograph of a t-shirt on white - so the ones used here were
# looked at first rather than taken at random.
CURATED = {
    "metal": ["Metal_167", "Metal_131", "Metal_126"],
    "wood": ["Wood_127", "Wood_162", "Wood_230"],
    "fabric": ["Fabric_121", "Fabric_181", "Fabric_123"],
    "leather": ["Wood_253", "Fabric_124", "Metal_257"],
    "stone": ["Stone_124", "Stone_151", "Stone_126"],
    "concrete": ["Concrete_143", "Concrete_184", "Concrete_151"],
    "brick": ["Brick_167"],
    "soil": ["Soil_126", "Soil_121", "Soil_145"],
    "detail": ["Grunge_201", "Grunge_328", "Grunge_160"],
}

# How hard each surface pushes, how rough it is and how metallic, all live in
# tools/pbr.py next to the code that derives the maps.


sys.path.insert(0, os.path.join(HERE, "tools"))
import pbr                                                  # noqa: E402


def texture_for(material, seed=0):
    """
    The full set of maps for a surface - colour detail, normal and roughness,
    plus how metallic it is - fetching and deriving them the first time and
    reusing them ever after. Returns None if they cannot be had (offline, say)
    and the model is simply built in flat colour, as it was before.
    """
    options = CURATED.get(material) or CURATED["detail"]
    name = options[seed % len(options)]
    raw = os.path.join(TEXTURE_DIR, "source", name + "S.jpg")
    ready = os.path.join(TEXTURE_DIR, "maps")
    done = os.path.join(ready, "%s_%sS_detail.png" % (material, name))
    if os.path.exists(done):
        return {"detail": done,
                "normal": done.replace("_detail.png", "_normal.png"),
                "rough": done.replace("_detail.png", "_rough.png"),
                "metallic": pbr.SURFACES.get(material, pbr.SURFACES["detail"])[4],
                "name": "%s_%s" % (material, name)}
    try:
        if not os.path.exists(raw):
            os.makedirs(os.path.dirname(raw), exist_ok=True)
            req = urllib.request.Request(
                "%s/Texturelabs_%sS.jpg" % (TEXTURELABS, name),
                headers={"User-Agent": AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(raw, "wb") as f:
                    f.write(resp.read())
        made = pbr.build(raw, material, ready)
        made["name"] = "%s_%s" % (material, name)
        return made
    except Exception as exc:                            # noqa: BLE001
        log("texture %s unavailable (%s)" % (material, exc))
        return None


def texture_set(prompt):
    """
    One texture per surface, chosen from the prompt so that the same prompt
    always comes out the same, and two different prompts do not both get the
    same plank of wood.
    """
    seed = sum(ord(c) for c in (prompt or ""))
    out, credits = {}, []
    for material in CURATED:
        maps = texture_for(material, seed)
        if maps:
            out[material] = maps
            credits.append(maps["name"])
    return out, credits



# --------------------------------------------------------------------------
# the local 3D generator, on the Windows PC
#
# The open-weight equivalent of Meshy - Tencent's Hunyuan3D-2 - running on the
# RTX 3060 at the academy and reached over Tailscale. An image goes over, a
# textured mesh comes back, and it lands in the same import-and-fit-a-skeleton
# path that was written for the Meshy button.
#
# Two addresses in ~/.claude/.env:
#   HUNYUAN_URL    http://100.104.28.73:4488
#   HUNYUAN_TOKEN  printed by serve.py when it starts
#
# The PC is at the academy and is often off, so every call here is written to
# fail quickly and say so rather than to hang.
# --------------------------------------------------------------------------

def hunyuan_where():
    url = read_env_key("HUNYUAN_URL")
    token = read_env_key("HUNYUAN_TOKEN")
    return (url.rstrip("/") if url else None), token


def hunyuan_call(path, payload=None, timeout=20):
    url, token = hunyuan_where()
    if not url:
        raise RuntimeError("no HUNYUAN_URL in ~/.claude/.env - the PC service "
                           "has not been set up yet")
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        "%s%s" % (url, path), data=data,
        method="POST" if data else "GET",
        headers={"Content-Type": "application/json",
                 "X-Hunyuan-Token": token or ""})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def hunyuan_fetch(remote_path, into):
    url, token = hunyuan_where()
    req = urllib.request.Request(
        "%s/file?t=%s&p=%s" % (url, urllib.parse.quote(token or ""),
                               urllib.parse.quote(remote_path)),
        headers={"X-Hunyuan-Token": token or ""})
    with urllib.request.urlopen(req, timeout=180) as resp, open(into, "wb") as f:
        f.write(resp.read())
    return into


def hunyuan_job(image_b64, name, texture):
    """
    Runs on its own thread; progress goes out on the same event stream the
    rest of the app uses. A generation takes a minute or two on that card.
    """
    try:
        WORKER.publish({"event": "local3d", "stage": "sending"})
        result = hunyuan_call("/generate", {
            "image": image_b64, "name": name, "texture": bool(texture),
            "steps": 30, "resolution": 256}, timeout=900)
        if result.get("error"):
            raise RuntimeError(result["error"])
        WORKER.publish({"event": "local3d", "stage": "fetching",
                        "seconds": result.get("shape_seconds", 0)
                        + result.get("texture_seconds", 0)})
        into = os.path.join(WORKER.session, "local_%s.glb" % name)
        hunyuan_fetch(result["file"], into)
        WORKER.publish({"event": "local3d", "stage": "done",
                        "file": os.path.basename(into),
                        "textured": result.get("textured", False)})
        WORKER.send({"cmd": "import", "path": into})
    except urllib.error.URLError as exc:
        WORKER.publish({"event": "error",
                        "message": "cannot reach the PC (%s). Is it on, and is "
                                   "serve.py running?" % exc.reason})
        WORKER.publish({"event": "idle", "cmd": "local3d"})
    except Exception as exc:                            # noqa: BLE001
        WORKER.publish({"event": "error", "message": "local generator: %s" % exc})
        WORKER.publish({"event": "idle", "cmd": "local3d"})



# --------------------------------------------------------------------------
# lighting
#
# Three lamps in a void is what a 3D program looks like. A room full of light
# is what a photograph looks like - so the viewport is lit by a real
# environment, and the model is lit by the same thing from every direction at
# once. It is the cheapest large step towards something looking real, and it
# costs nothing: Poly Haven is CC0.
# --------------------------------------------------------------------------

HDRI_DIR = os.path.join(HERE, "hdri")
DEFAULT_HDRI = "brown_photostudio_02_1k.hdr"


def hdri_path():
    path = os.path.join(HDRI_DIR, DEFAULT_HDRI)
    return path if os.path.exists(path) else None



# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "boneka"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # -- guards ------------------------------------------------------------
    def _origin_ok(self):
        origin = self.headers.get("Origin")
        if origin is None:
            return True                      # a plain page load, not a cross-site call
        host = urlparse(origin).netloc
        return host in ("127.0.0.1:%d" % PORT, "localhost:%d" % PORT)

    def _token_ok(self, params):
        given = self.headers.get("X-Boneka-Token") or (params.get("t") or [""])[0]
        return secrets.compare_digest(given, TOKEN)

    # -- plumbing ----------------------------------------------------------
    def _send(self, code, body=b"", ctype="application/json", extra=None):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload), "application/json")

    def _file(self, path):
        if not os.path.isfile(path):
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if path.endswith(".glb"):
            ctype = "model/gltf-binary"
        if path.endswith(".js"):
            ctype = "text/javascript"
        with open(path, "rb") as f:
            self._send(200, f.read(), ctype)

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        url = urlparse(self.path)
        params = parse_qs(url.query)
        route = url.path

        if route == "/":
            return self._file(os.path.join(WEB, "index.html"))
        if route.startswith("/web/"):
            return self._safe_static(WEB, route[len("/web/"):])
        if route.startswith("/session/"):
            return self._safe_static(WORKER.session, route[len("/session/"):])

        if route.startswith("/api/"):
            if not self._origin_ok():
                return self._json(403, {"error": "wrong origin"})
            if not self._token_ok(params):
                return self._json(403, {"error": "wrong or missing token"})
            if route == "/api/hello":
                return self._json(200, {
                    "ready": WORKER.ready.is_set(), "busy": WORKER.busy,
                    "session": os.path.basename(WORKER.session),
                    "clips": self._clips(),
                    "meshy": bool(read_env_key("MESHY_API_KEY"))})
            if route == "/api/clips":
                return self._json(200, {"clips": self._clips()})
            if route == "/api/local3d/health":
                where, _ = hunyuan_where()
                if not where:
                    return self._json(200, {"configured": False})
                try:
                    state = hunyuan_call("/health", timeout=6)
                    state["configured"] = True
                    return self._json(200, state)
                except Exception as exc:                # noqa: BLE001
                    return self._json(200, {"configured": True, "ok": False,
                                            "error": str(exc)})
            if route == "/api/hdri":
                path = hdri_path()
                if not path:
                    return self._json(404, {"error": "no environment map"})
                with open(path, "rb") as f:
                    return self._send(200, f.read(), "image/vnd.radiance")
            if route == "/api/palettes":
                query = (params.get("q") or [""])[0].strip()
                out = {"moods": palettes.known_moods(),
                       "cached": sorted(
                           os.path.splitext(f)[0]
                           for f in os.listdir(PALETTE_CACHE)
                           if f.endswith(".json"))
                       if os.path.isdir(PALETTE_CACHE) else [],
                       "found": []}
                if query:
                    try:
                        out["found"] = search_palettes(query)
                    except Exception as exc:            # noqa: BLE001
                        out["note"] = str(exc)
                return self._json(200, out)
            if route == "/api/palette":
                try:
                    return self._json(200, resolve_palette(
                        (params.get("name") or [""])[0]))
                except Exception as exc:                # noqa: BLE001
                    return self._json(404, {"error": str(exc)})
            if route == "/api/reference":
                subject = (params.get("q") or [""])[0].strip()
                if not subject:
                    return self._json(400, {"error": "nothing to look up"})
                try:
                    return self._json(200, {"subject": subject,
                                            "images": reference_images(subject)})
                except Exception as exc:                # noqa: BLE001
                    return self._json(200, {"subject": subject, "images": [],
                                            "note": str(exc)})
            if route == "/api/reference/image":
                try:
                    body, ctype = fetch_thumbnail((params.get("u") or [""])[0])
                except Exception as exc:                # noqa: BLE001
                    return self._json(400, {"error": str(exc)})
                return self._send(200, body, ctype)
            if route == "/api/events":
                return self._events()
        return self._send(404, b"not found", "text/plain")

    def do_POST(self):
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if not url.path.startswith("/api/"):
            return self._send(404, b"not found", "text/plain")
        if not self._origin_ok():
            return self._json(403, {"error": "wrong origin"})
        if not self._token_ok(params):
            return self._json(403, {"error": "wrong or missing token"})

        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "bad json"})

        if url.path == "/api/command":
            cmd = payload.get("cmd")
            if cmd not in ("build", "rig", "animate", "clip", "rest", "import",
                           "export", "ping"):
                return self._json(400, {"error": "unknown command"})
            if cmd == "build" and payload.get("textures", True):
                # the server fetches and prepares; Blender is handed file
                # paths, so the worker never reaches the network
                paths, credits = texture_set(payload.get("prompt", ""))
                payload = dict(payload, textures=paths, texture_credits=credits)
            if cmd == "build" and payload.get("palette"):
                # the page names a palette; Blender is handed the colours, so
                # the worker never has to reach the network
                try:
                    found = resolve_palette(payload["palette"])
                except Exception as exc:                # noqa: BLE001
                    return self._json(400, {"error": str(exc)})
                payload = dict(payload, palette=found["colors"],
                               palette_name=found["name"])
            try:
                WORKER.send(payload)
            except Exception as exc:                    # noqa: BLE001
                return self._json(500, {"error": str(exc)})
            return self._json(200, {"ok": True})

        if url.path == "/api/meshy":
            if not payload.get("confirm"):
                return self._json(400, {"error": "Meshy costs credits and was "
                                                 "not confirmed"})
            prompt = (payload.get("prompt") or "").strip()
            if not prompt:
                return self._json(400, {"error": "no prompt"})
            threading.Thread(target=meshy_job, args=(WORKER, prompt,
                                                     payload.get("style",
                                                                 "realistic")),
                             daemon=True).start()
            return self._json(200, {"ok": True})

        if url.path == "/api/local3d":
            image = (payload.get("image") or "").split(",")[-1]
            if not image:
                return self._json(400, {"error": "no image"})
            threading.Thread(
                target=hunyuan_job,
                args=(image, payload.get("name", "model"),
                      payload.get("texture", False)),
                daemon=True).start()
            return self._json(200, {"ok": True})

        if url.path == "/api/meshy/balance":
            try:
                return self._json(200, meshy_request("v1/balance"))
            except Exception as exc:                    # noqa: BLE001
                return self._json(502, {"error": str(exc)})

        return self._json(404, {"error": "no such endpoint"})

    # -- helpers -----------------------------------------------------------
    def _safe_static(self, root, relative):
        path = os.path.abspath(os.path.join(root, relative))
        if not path.startswith(os.path.abspath(root) + os.sep):
            return self._send(403, b"no", "text/plain")
        return self._file(path)

    def _clips(self):
        if not os.path.isdir(CLIPS):
            return []
        return sorted(f for f in os.listdir(CLIPS) if f.lower().endswith(".fbx"))

    def _events(self):
        q = WORKER.subscribe()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            for event in list(WORKER.history):
                self._push(event)
            while True:
                try:
                    self._push(q.get(timeout=15))
                except queue.Empty:
                    self.wfile.write(b": keep-alive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            WORKER.unsubscribe(q)

    def _push(self, event):
        self.wfile.write(("data: %s\n\n" % json.dumps(event)).encode())
        self.wfile.flush()


class Server(ThreadingHTTPServer):
    """
    The stock server prints a full stack trace when a browser hangs up, which
    happens every time you reload the page: the live progress connection is a
    long-lived one, and closing it is a reset from the server's point of view.
    It is not an error, and printing it as one makes a working tool look broken.
    """
    daemon_threads = True

    def handle_error(self, request, client_address):
        kind = sys.exc_info()[0]
        if kind in (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
            return
        super().handle_error(request, client_address)


def open_server():
    """
    Take the first free port from the usual one upwards, so a second boneka
    opens beside the first instead of dying on a stack trace.

    BONEKA_PORT=0 means "any free port", which is how bengkel starts boneka so
    it never collides with one already open in a browser. The port we end up
    on then has nothing to do with the one we asked for, so it is read back
    off the socket - everything after this, the address boneka prints and the
    origin check on every request, is built from PORT.
    """
    global PORT
    wanted = PORT
    for port in range(wanted, wanted + 10):
        try:
            httpd = Server(("127.0.0.1", port), Handler)
        except OSError as exc:
            if exc.errno not in (48, 98):               # in use, macOS / Linux
                raise
            continue
        PORT = httpd.server_address[1]                  # the one we really got
        if wanted and PORT != wanted:
            log("port %d was busy, using %d instead" % (wanted, PORT))
        return httpd
    raise SystemExit(
        "ports %d-%d are all busy. boneka is probably already running - "
        "open the address it printed, or stop it first." % (wanted, wanted + 9))


def main():
    global WORKER
    httpd = open_server()
    session = os.path.join(HERE, "sessions",
                           time.strftime("session-%Y%m%d-%H%M%S"))
    WORKER = Worker(session)
    url = "http://127.0.0.1:%d/?t=%s" % (PORT, TOKEN)
    log("Blender:", BLENDER)
    log("session:", session)
    log("open:", url)
    print("%s%s" % (READY_MARK, json.dumps(
        {"url": url, "port": PORT, "token": TOKEN, "session": session})), flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stopping")
    finally:
        WORKER.stop()


if __name__ == "__main__":
    main()
