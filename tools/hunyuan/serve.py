#!/usr/bin/env python3
"""
The local 3D generator, as a service.

Runs on the Windows PC inside WSL, listens on the Tailscale address, and turns
an image into a textured mesh with Tencent's Hunyuan3D-2. boneka on the Mac
posts to it and gets a .glb back, which then goes through the same import and
fit-a-skeleton path that was written for the Meshy button.

    python serve.py                 shape only, what install.sh sets up first
    python serve.py --texture       shape and texture, if the extensions built
    python serve.py --port 4488

The model is loaded once, when the first request arrives rather than at
startup, so the service can sit there costing nothing until it is wanted. A
generation holds the GPU, so requests are served one at a time by a lock
rather than by threads fighting over 12 GB of VRAM.

Same two locks on the door as boneka itself: a token minted at startup, and a
refusal to accept a request from a browser origin that is not its own. The
tailnet is private, but private is not the same as safe, and a service that
can write files and burn a GPU should not be open to every page on the network.
"""

import argparse
import base64
import io
import json
import os
import secrets
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

TOKEN = os.environ.get("HUNYUAN_TOKEN") or secrets.token_urlsafe(18)
OUT_DIR = os.path.expanduser("~/hunyuan3d/out")
STATE = {"shape": None, "paint": None, "busy": False, "made": 0}
LOCK = threading.Lock()


def log(*parts):
    sys.stderr.write("[hunyuan] %s\n" % " ".join(str(p) for p in parts))
    sys.stderr.flush()


# --------------------------------------------------------------------------
# the model
# --------------------------------------------------------------------------

def load(with_texture):
    """
    Loaded on first use, not at startup. Several gigabytes go onto the card
    here and stay there, so there is no sense paying that before anyone has
    asked for anything.
    """
    if STATE["shape"] is None:
        from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline
        log("loading the shape model (0.6B, mini-turbo)")
        STATE["shape"] = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
            "tencent/Hunyuan3D-2mini", subfolder="hunyuan3d-dit-v2-mini-turbo")
        log("shape model ready")
    if with_texture and STATE["paint"] is None:
        from hy3dgen.texgen import Hunyuan3DPaintPipeline
        log("loading the paint model")
        STATE["paint"] = Hunyuan3DPaintPipeline.from_pretrained(
            "tencent/Hunyuan3D-2", subfolder="hunyuan3d-paint-v2-0-turbo")
        log("paint model ready")
    return STATE["shape"], STATE["paint"]


def generate(image_bytes, steps, resolution, with_texture, name):
    """One image in, one .glb out. Holds the GPU for its whole run."""
    from PIL import Image

    os.makedirs(OUT_DIR, exist_ok=True)
    shape, paint = load(with_texture)
    picture = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    started = time.time()
    mesh = shape(image=picture, num_inference_steps=steps,
                 octree_resolution=resolution)[0]
    shaped = time.time() - started

    painted = 0.0
    if with_texture and paint is not None:
        mark = time.time()
        mesh = paint(mesh, image=picture)
        painted = time.time() - mark

    STATE["made"] += 1
    path = os.path.join(OUT_DIR, "%s_%03d.glb" % (name or "model", STATE["made"]))
    mesh.export(path)
    return {"file": path, "bytes": os.path.getsize(path),
            "shape_seconds": round(shaped, 1),
            "texture_seconds": round(painted, 1),
            "textured": bool(with_texture and paint is not None)}


# --------------------------------------------------------------------------
# http
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    server_version = "hunyuan-bridge"
    protocol_version = "HTTP/1.1"
    with_texture = False

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body=b"", ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _json(self, code, payload):
        self._send(code, json.dumps(payload))

    def _allowed(self, params):
        origin = self.headers.get("Origin")
        if origin is not None and urlparse(origin).netloc.split(":")[0] not in (
                "127.0.0.1", "localhost"):
            return False
        given = self.headers.get("X-Hunyuan-Token") or (params.get("t") or [""])[0]
        return secrets.compare_digest(given, TOKEN)

    def do_GET(self):
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if url.path == "/health":
            return self._json(200, {
                "ok": True, "busy": STATE["busy"], "made": STATE["made"],
                "loaded": STATE["shape"] is not None,
                "texture": self.with_texture})
        if not self._allowed(params):
            return self._json(403, {"error": "wrong or missing token"})
        if url.path == "/file":
            path = (params.get("p") or [""])[0]
            if not path.startswith(os.path.abspath(OUT_DIR)) or not os.path.isfile(path):
                return self._json(404, {"error": "no such file"})
            with open(path, "rb") as f:
                return self._send(200, f.read(), "model/gltf-binary")
        return self._json(404, {"error": "no such endpoint"})

    def do_POST(self):
        url = urlparse(self.path)
        params = parse_qs(url.query)
        if not self._allowed(params):
            return self._json(403, {"error": "wrong or missing token"})
        if url.path != "/generate":
            return self._json(404, {"error": "no such endpoint"})

        length = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "bad json"})

        try:
            image = base64.b64decode(payload["image"])
        except Exception:
            return self._json(400, {"error": "send an image as base64 in 'image'"})

        if not LOCK.acquire(blocking=False):
            return self._json(429, {"error": "already generating - one at a time, "
                                             "the card cannot do two"})
        STATE["busy"] = True
        try:
            result = generate(
                image,
                int(payload.get("steps", 30)),
                int(payload.get("resolution", 256)),
                bool(payload.get("texture", self.with_texture)),
                payload.get("name", "model"))
            log("made %s in %.0fs" % (result["file"],
                                      result["shape_seconds"] + result["texture_seconds"]))
            return self._json(200, result)
        except Exception as exc:                        # noqa: BLE001
            log("failed:", exc)
            return self._json(500, {"error": str(exc),
                                    "detail": traceback.format_exc()[-800:]})
        finally:
            STATE["busy"] = False
            LOCK.release()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", type=int, default=4488)
    p.add_argument("--texture", action="store_true",
                   help="also paint the mesh (needs the compiled extensions)")
    p.add_argument("--host", default="0.0.0.0",
                   help="0.0.0.0 so the Mac can reach it over Tailscale")
    args = p.parse_args()

    Handler.with_texture = args.texture
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    log("listening on %s:%d" % (args.host, args.port))
    log("texture:", "on" if args.texture else "off (shape only)")
    log("token:", TOKEN)
    log("put that token in ~/.claude/.env on the Mac as HUNYUAN_TOKEN")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("stopping")


if __name__ == "__main__":
    main()
