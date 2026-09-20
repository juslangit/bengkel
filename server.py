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
    """
    global PORT
    for port in range(PORT, PORT + 10):
        try:
            httpd = Server(("127.0.0.1", port), Handler)
        except OSError as exc:
            if exc.errno not in (48, 98):               # in use, macOS / Linux
                raise
            continue
        if port != PORT:
            log("port %d was busy, using %d instead" % (PORT, port))
        PORT = port
        return httpd
    raise SystemExit(
        "ports %d-%d are all busy. boneka is probably already running - "
        "open the address it printed, or stop it first." % (PORT, PORT + 9))


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
