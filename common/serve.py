"""
The server every bengkel tool is built on.

boneka and gerak were each written from scratch, and by the second one it was
clear that most of a tool is not the tool: it is a token, an origin check, a
static file server, a way to read a model off the disk safely, a way to run
Blender, and a line printed at startup so bengkel can find the port. Five more
tools would have meant writing that six times and fixing every bug six times.

So it is written once, here, and a tool is what is left over:

    from serve import Tool

    tool = Tool("pasar", __file__, "@@PASAR-READY@@")

    @tool.get("/api/search")
    def search(query):
        return {"results": [...]}

    tool.run()

What a tool gets for free:

  * a fresh token each run, and an origin check, because a server on localhost
    is reachable by every page in the browser
  * its own page served from web/, and the shared pieces from common/web/
  * /api/model, which reads a 3D file off the disk only if it is somewhere a
    tool is allowed to read from
  * /api/library, the scan of every model on the machine, shared between all
    the tools and cached so they are not each walking the disk
  * a Blender runner, for the work a browser cannot do - through the one
    shared Blender MCP, never a Blender of its own (see mcp.py)
  * its own folder under ~/Documents/bengkel/<tool>/ for whatever it makes
  * a watch on whatever started it, so it lets itself out when bengkel goes

Nothing here needs installing: it is the Python that comes with macOS.
"""

import base64
import json
import mimetypes
import os
import re
import secrets
import shutil
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp                                                  # noqa: E402

HOME = os.path.expanduser("~")
COMMON = os.path.dirname(os.path.abspath(__file__))
WORKSHOP = os.path.dirname(COMMON)

# The only folders any tool will read a model out of.
ROOTS = [
    os.path.join(HOME, "Desktop", "projects"),
    os.path.join(HOME, "Documents"),
    os.path.join(HOME, "Downloads"),
]

MODEL_EXT = (".glb", ".gltf", ".fbx", ".blend", ".obj", ".stl", ".dae", ".ply")

SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
             ".godot", "Library", ".Trash", "addons", "build"}

BLENDER = os.environ.get(
    "BENGKEL_BLENDER", "/Applications/Blender.app/Contents/MacOS/Blender")

SAFE_NAME = re.compile(r"[^a-z0-9_-]+")

# One library for all the tools, so six of them do not each walk the disk.
LIBRARY_CACHE = os.path.join(HOME, "Documents", "bengkel", ".library.json")
LIBRARY_AGE = 3600


# --------------------------------------------------------------------------
# reading a model without reading the whole thing
# --------------------------------------------------------------------------

def glb_summary(path):
    """What is in a .glb, from its header alone.

    A .glb is a 12-byte header, a chunk of JSON describing the scene, then the
    binary blob of vertices. Everything a library needs - whether there is a
    skeleton, how many joints, how many animations, how many meshes - is in
    that JSON, which is usually a few kilobytes. So a 40 MB model costs almost
    nothing to describe.
    """
    try:
        with open(path, "rb") as f:
            magic, _version, _length = struct.unpack("<III", f.read(12))
            if magic != 0x46546C67:                    # 'glTF'
                return None
            chunk_len, _chunk_type = struct.unpack("<II", f.read(8))
            doc = json.loads(f.read(chunk_len).decode("utf-8"))
    except Exception:
        return None

    skins = doc.get("skins", [])
    return {
        "rigged": len(skins) > 0,
        "joints": sum(len(s.get("joints", [])) for s in skins),
        "anims": len(doc.get("animations", [])),
        "meshes": len(doc.get("meshes", [])),
        "materials": len(doc.get("materials", [])),
        "images": len(doc.get("images", [])),
    }


def describe(path):
    """One row of the library."""
    real = os.path.realpath(path)
    item = {
        "path": real,
        "name": os.path.basename(real),
        "folder": os.path.dirname(real).replace(HOME, "~"),
        "ext": os.path.splitext(real)[1].lower().lstrip("."),
        "size": os.path.getsize(real),
        "mtime": os.path.getmtime(real),
        "rigged": False, "joints": 0, "anims": 0, "meshes": 0,
    }
    if item["ext"] == "glb":
        summary = glb_summary(real)
        if summary:
            item.update(summary)
    return item


_library_lock = threading.Lock()


def library(refresh=False, log=print):
    """Every model on the machine, cached for an hour and shared by the tools."""
    with _library_lock:
        if not refresh and os.path.exists(LIBRARY_CACHE):
            if time.time() - os.path.getmtime(LIBRARY_CACHE) < LIBRARY_AGE:
                try:
                    with open(LIBRARY_CACHE) as f:
                        return json.load(f)
                except Exception:
                    pass

        started = time.time()
        out = []
        for root in ROOTS:
            if not os.path.isdir(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames
                               if d not in SKIP_DIRS and not d.startswith(".")]
                for name in filenames:
                    if not name.lower().endswith(MODEL_EXT):
                        continue
                    try:
                        out.append(describe(os.path.join(dirpath, name)))
                    except OSError:
                        continue
        out.sort(key=lambda i: (not i["rigged"], -i["mtime"]))

        os.makedirs(os.path.dirname(LIBRARY_CACHE), exist_ok=True)
        with open(LIBRARY_CACHE, "w") as f:
            json.dump(out, f)
        log("library: %d models (%d rigged) in %.1fs"
            % (len(out), sum(1 for i in out if i["rigged"]), time.time() - started))
        return out


# --------------------------------------------------------------------------
# the tool
# --------------------------------------------------------------------------

class Tool:
    """One bengkel tool: a server, a page, and whatever routes it adds."""

    def __init__(self, name, tool_file, ready_mark, title=None):
        self.name = name
        self.title = title or name
        self.here = os.path.dirname(os.path.abspath(tool_file))
        self.web = os.path.join(self.here, "web")
        self.ready_mark = ready_mark
        self.token = secrets.token_urlsafe(18)
        self.port = 0
        self.bound = 0

        self.data = os.environ.get("BENGKEL_DATA") \
            or os.path.join(HOME, "Documents", "bengkel", name)
        self.out = os.path.join(self.data, "out")

        self._routes = {"GET": {}, "POST": {}}
        # Files handed over by hand this run - dropped in, or chosen in a
        # dialog. The scanned folders cover almost everything, but a model on
        # a USB stick is not in them.
        self._permitted = set()
        self._permit_lock = threading.Lock()

    # ── saying things ─────────────────────────────────────────────────

    def log(self, *parts):
        sys.stderr.write("[%s] %s\n" % (self.name, " ".join(str(p) for p in parts)))
        sys.stderr.flush()

    # ── adding routes ─────────────────────────────────────────────────

    # What the foundation answers itself, before a tool's own routes are
    # reached. A tool registering one of these would be writing a handler that
    # is never called, and finding that out is an hour of wondering why a page
    # gets the wrong answer - so it is refused at startup instead.
    BUILT_IN = {
        "GET": {"/", "/index.html", "/favicon.ico", "/api/library",
                "/api/model", "/api/describe", "/api/where"},
        "POST": {"/api/permit", "/api/save", "/api/reveal"},
    }

    def _claim(self, method, path):
        if path in self.BUILT_IN[method]:
            raise ValueError(
                "%s already answers %s %s itself, so %s's own handler would "
                "never be called. Give it another name."
                % (__name__, method, path, self.name))
        if path in self._routes[method]:
            raise ValueError("%s is registered twice in %s" % (path, self.name))

    def get(self, path):
        """@tool.get('/api/thing') — the handler is called with the query."""
        self._claim("GET", path)

        def keep(fn):
            self._routes["GET"][path] = fn
            return fn
        return keep

    def post(self, path):
        """@tool.post('/api/thing') — the handler is called with the body."""
        self._claim("POST", path)

        def keep(fn):
            self._routes["POST"][path] = fn
            return fn
        return keep

    # ── reading files ─────────────────────────────────────────────────

    def permit(self, path):
        """Let this run read one file that is outside the scanned folders."""
        try:
            real = os.path.realpath(path)
        except OSError:
            return None
        if not os.path.isfile(real):
            return None
        with self._permit_lock:
            self._permitted.add(real)
        return real

    def allowed(self, path):
        """True only if this really is a file the tool may read.

        realpath first, so `..` and symlinks are resolved before anything is
        compared - checking the string alone would let both of those through.
        """
        try:
            real = os.path.realpath(path)
        except OSError:
            return False
        if not os.path.isfile(real):
            return False
        if any(real.startswith(os.path.realpath(r) + os.sep) for r in ROOTS):
            return True
        with self._permit_lock:
            return real in self._permitted

    # ── Blender, for what a browser cannot do ─────────────────────────

    def blender(self, script, job, timeout=900):
        """Run one job through the shared Blender MCP and hand back what it said.

        `script` is a file in the tool's own blender/ folder. The job is passed
        as JSON on disk, and the answer comes back on one line beginning with
        @@JOB@@, so it can be found among whatever else the script printed. The
        script runs in a scene of its own inside the shared Blender - see mcp.py.
        """
        jobs = os.path.join(self.data, ".jobs")
        os.makedirs(jobs, exist_ok=True)
        job_file = os.path.join(jobs, "job-%s.json" % secrets.token_hex(6))
        with open(job_file, "w") as f:
            json.dump(job, f)

        started = time.time()
        self.log("blender (mcp):", script, job.get("job", ""))
        try:
            printed = mcp.run_job(os.path.join(self.here, "blender", script),
                                  [job_file], label=self.name, timeout=timeout)
        except mcp.BlenderError as exc:
            return {"ok": False, "problems": [str(exc)]}
        finally:
            try:
                os.remove(job_file)
            except OSError:
                pass

        mark = "@@JOB@@"
        for line in printed.splitlines():
            if line.startswith(mark):
                answer = json.loads(line[len(mark):])
                answer["seconds"] = round(time.time() - started, 1)
                self.log("blender finished in %.1fs" % answer["seconds"])
                return answer

        tail = printed.strip().splitlines()[-3:]
        return {"ok": False, "problems": ["Blender said nothing back. " + " / ".join(tail)]}

    # ── running ───────────────────────────────────────────────────────

    def run(self, argv=None):
        argv = sys.argv if argv is None else argv
        for folder in (self.data, self.out):
            os.makedirs(folder, exist_ok=True)

        self.port = int(os.environ.get("%s_PORT" % self.name.upper(), "0"))
        handler = _handler_for(self)

        try:
            server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        except OSError as err:
            if err.errno == 48:
                self.log("port %d is already in use." % self.port)
                return 1
            raise

        # The port asked for and the port bound are different things whenever
        # 0 was asked for, and everything after this - the address printed, the
        # origin check on every request - is built from the one we really got.
        self.bound = server.server_address[1]
        url = "http://127.0.0.1:%d/?t=%s" % (self.bound, self.token)

        self.log("%s is running" % self.name)
        self.log(url)
        print("%s%s" % (self.ready_mark, json.dumps(
            {"url": url, "port": self.bound, "token": self.token,
             "data": self.data})), flush=True)

        self._watch_parent()
        threading.Thread(target=lambda: library(log=self.log), daemon=True).start()

        if "--no-open" not in argv:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            self.log("stopped")
        return 0

    def _watch_parent(self):
        """Leave when whatever started us has gone.

        bengkel stops its tools when it quits, but a force-quit never reaches
        that code and an orphan would sit holding a port forever. Watch who the
        parent IS rather than whether the old one answers a signal: a killed
        process stays in the table as a zombie until it is reaped, and
        signalling a zombie succeeds.
        """
        if not os.environ.get("BENGKEL_PARENT"):
            return
        started_under = os.getppid()

        def watch():
            while True:
                time.sleep(1)
                if os.getppid() != started_under:
                    # Leave first and talk afterwards: our stderr is a pipe to
                    # the thing that just died, and writing to it would raise
                    # and kill this thread before it got to the line that
                    # matters.
                    os._exit(0)

        threading.Thread(target=watch, daemon=True).start()


# --------------------------------------------------------------------------
# the handler
# --------------------------------------------------------------------------

def _handler_for(tool):

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):
            pass

        def handle_one_request(self):
            """A page closing a connection is not an error.

            When the app quits, open connections are cut, and the stock handler
            prints a traceback for each one. They bury anything that matters.
            """
            try:
                super().handle_one_request()
            except (ConnectionResetError, BrokenPipeError):
                self.close_connection = True

        # -- guards ----------------------------------------------------

        def authorised(self):
            origin = self.headers.get("Origin")
            if origin and origin not in ("http://127.0.0.1:%d" % tool.bound,
                                         "http://localhost:%d" % tool.bound):
                return False
            query = parse_qs(urlparse(self.path).query)
            given = (self.headers.get("X-Bengkel-Token")
                     or (query.get("t") or [""])[0])
            return secrets.compare_digest(given, tool.token)

        # -- replies ---------------------------------------------------

        def send_json(self, obj, status=200):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_bytes(self, body, ctype, status=200):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def send_file(self, path, ctype=None):
            if not ctype:
                ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
                if path.endswith(".js"):
                    ctype = "text/javascript; charset=utf-8"
                elif path.endswith(".css"):
                    ctype = "text/css; charset=utf-8"
            try:
                with open(path, "rb") as f:
                    body = f.read()
            except OSError:
                return self.send_json({"error": "cannot read that file"}, 404)
            self.send_bytes(body, ctype)

        def under(self, base, rest):
            full = os.path.realpath(os.path.join(base, rest))
            if not full.startswith(os.path.realpath(base) + os.sep):
                return None
            return full

        def read_body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode("utf-8"))
            except Exception:
                return {}

        # -- routes ----------------------------------------------------

        def do_GET(self):
            url = urlparse(self.path)
            path, query = url.path, parse_qs(url.query)

            # The page itself is the one thing served without a token: it is
            # where the token is handed over in the first place.
            if path in ("/", "/index.html"):
                try:
                    with open(os.path.join(tool.web, "index.html")) as f:
                        page = f.read()
                except OSError:
                    return self.send_json({"error": "web/index.html is missing"}, 500)
                # The placeholder must not be a name the page also uses, or
                # `window.BENGKEL_TOKEN = "__TOKEN__"` becomes
                # `window.<the token> = "<the token>"` and the page cannot find
                # its own token. The marker and the variable differ on purpose.
                page = (page.replace("__BENGKEL_TOKEN__", tool.token)
                            .replace("__BENGKEL_TOOL__", tool.name))
                return self.send_bytes(page.encode("utf-8"), "text/html; charset=utf-8")

            if path.startswith("/web/"):
                full = self.under(tool.web, path[len("/web/"):])
                return self.send_file(full) if full else self.send_json({"error": "no"}, 403)

            if path.startswith("/common/"):
                full = self.under(os.path.join(COMMON, "web"), path[len("/common/"):])
                return self.send_file(full) if full else self.send_json({"error": "no"}, 403)

            if path == "/favicon.ico":
                return self.send_bytes(b"", "image/x-icon", 204)

            if not self.authorised():
                return self.send_json({"error": "not authorised"}, 403)

            if path == "/api/library":
                refresh = (query.get("refresh") or ["0"])[0] == "1"
                return self.send_json({"items": library(refresh, tool.log)})

            if path == "/api/model":
                target = unquote((query.get("path") or [""])[0])
                if not tool.allowed(target):
                    return self.send_json({"error": "outside the allowed folders"}, 403)
                return self.send_file(target, "model/gltf-binary")

            if path == "/api/describe":
                target = unquote((query.get("path") or [""])[0])
                if not tool.allowed(target):
                    return self.send_json({"error": "that file was not offered"}, 403)
                return self.send_json(describe(target))

            if path == "/api/where":
                return self.send_json({
                    "tool": tool.name, "data": tool.data, "out": tool.out,
                    "shown": tool.out.replace(HOME, "~"),
                    "blender": os.path.exists(BLENDER),
                })

            handler = tool._routes["GET"].get(path)
            if handler:
                return self.send_json(handler({k: v[0] for k, v in query.items()}))

            return self.send_json({"error": "unknown route"}, 404)

        def do_POST(self):
            if not self.authorised():
                return self.send_json({"error": "not authorised"}, 403)
            path = urlparse(self.path).path
            body = self.read_body()

            if path == "/api/permit":
                wanted = body.get("paths") or ([body["path"]] if body.get("path") else [])
                ok = [p for p in (tool.permit(w) for w in wanted) if p]
                return self.send_json({"ok": bool(ok), "paths": ok})

            if path == "/api/save":
                # The browser can build a file but cannot choose where on the
                # disk to put it, so it hands the bytes here.
                name = SAFE_NAME.sub("-", (body.get("name") or "out").lower()).strip("-")
                ext = (body.get("ext") or "bin").lower().lstrip(".")
                try:
                    raw = base64.b64decode(body.get("data") or "")
                except Exception:
                    return self.send_json({"error": "bad data"}, 400)
                if not raw:
                    return self.send_json({"error": "empty file"}, 400)
                full = os.path.join(tool.out, "%s.%s" % (name or "out", ext))
                with open(full, "wb") as f:
                    f.write(raw)
                tool.log("wrote", os.path.basename(full), "%.1f KB" % (len(raw) / 1024))
                return self.send_json({"ok": True, "path": full,
                                       "shown": full.replace(HOME, "~"),
                                       "bytes": len(raw)})

            if path == "/api/reveal":
                target = body.get("path") or tool.out
                if os.path.realpath(target).startswith(os.path.realpath(tool.data)):
                    os.system("open -R %s" % json.dumps(target))
                    return self.send_json({"ok": True})
                return self.send_json({"error": "no"}, 403)

            handler = tool._routes["POST"].get(path)
            if handler:
                return self.send_json(handler(body))

            return self.send_json({"error": "unknown route"}, 404)

    return Handler
