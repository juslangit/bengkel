"""
Blender, through Blender MCP.

Every tool in bengkel that needs Blender goes through here. Nothing starts a
Blender of its own any more: there is one, running the Blender MCP add-on on
port 9876, and it is the same one Claude drives through its `blender` MCP
server. What boneka builds, Claude can look at and change, and the other way
round.

If that Blender is not running, the first tool to need it opens it - hidden,
without taking focus. The add-on refuses to start in `blender --background`
(its commands run on Blender's own timer, which a headless Blender never
ticks), so "in the background" means a normal Blender with its window tucked
away. Click its Dock icon to watch it work.

Sharing one Blender means sharing one file, so nobody works in anyone else's
scene:

  * a one-off job (jaring, kulit, hantar, gerak) runs in a scene of its own,
    and when it finishes that scene and everything the job created is removed,
    and whatever scene was showing before is put back;
  * boneka keeps a scene called `boneka`, which stays between commands so the
    model, the rig and the pose are still there for the next button.

Nothing here quits Blender. It is shared, so it is not ours to close.
"""

import fcntl
import json
import os
import socket
import subprocess
import time

HOST = "127.0.0.1"
PORT = int(os.environ.get("BENGKEL_MCP_PORT", "9876"))
BLENDER_APP = os.environ.get("BENGKEL_BLENDER_APP", "/Applications/Blender.app")
COMMON = os.path.dirname(os.path.abspath(__file__))
STARTER = os.path.join(COMMON, "blender", "mcp_start.py")
HIDE = ('ObjC.import("AppKit"); var a = $.NSRunningApplication.runningApplicationsWithBundleIdentifier("org.blenderfoundation.blender"); for (var i = 0; i < a.count; i++) a.objectAtIndex(i).hide;')
LOCK = os.path.join(os.path.expanduser("~"), "Documents", "bengkel", ".mcp-launch.lock")

# The data-blocks a job can create. Whatever is new in these after a job was
# made by it, and is removed with its scene.
TRACKED = ("objects", "meshes", "materials", "images", "textures", "actions",
           "armatures", "cameras", "lights", "curves", "node_groups",
           "collections", "worlds", "scenes")


class BlenderError(RuntimeError):
    pass


def call(kind, params=None, timeout=60):
    """Send one command to the add-on and return its result."""
    try:
        sock = socket.create_connection((HOST, PORT), timeout=5)
    except OSError as exc:
        raise BlenderError("Blender MCP is not answering on port %d (%s)" % (PORT, exc))
    sock.settimeout(timeout)
    try:
        sock.sendall(json.dumps({"type": kind, "params": params or {}}).encode())
        buf = b""
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                raise BlenderError("Blender took longer than %d seconds" % timeout)
            if not chunk:
                raise BlenderError("Blender closed the connection mid-answer")
            buf += chunk
            try:
                answer = json.loads(buf.decode("utf-8"))
                break
            except (ValueError, UnicodeDecodeError):
                continue
    finally:
        sock.close()
    if answer.get("status") != "success":
        raise BlenderError(_message(answer.get("message", "Blender reported an error")))
    return answer.get("result")


def _message(text):
    # execute_code errors arrive as JSON carrying the traceback
    try:
        detail = json.loads(text)
        return "%s: %s\n%s" % (detail.get("exception_type"), detail.get("message"),
                               detail.get("traceback", "")[-1500:])
    except (ValueError, TypeError, AttributeError):
        return str(text)


def alive():
    try:
        call("ping", timeout=5)
        return True
    except BlenderError:
        return False


def ensure(wait=120):
    """Make sure the shared MCP Blender is up, opening it hidden if it is not."""
    if alive():
        return
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, "w") as lock:
        # two tools asking at once must not open two Blenders
        fcntl.flock(lock, fcntl.LOCK_EX)
        if alive():
            return
        if not os.path.isdir(BLENDER_APP):
            raise BlenderError("Blender is not at %s - set BENGKEL_BLENDER_APP" % BLENDER_APP)
        # -g: do not bring it forward, -j: launch hidden, -n: a new instance even
        # if some other Blender is open without the MCP server running
        subprocess.Popen(["open", "-g", "-j", "-n", "-a", BLENDER_APP,
                          "--args", "--python", STARTER],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + wait
        while time.time() < deadline:
            time.sleep(1)
            if alive():
                hide()
                return
    raise BlenderError("Opened Blender but its MCP server did not start within %d s" % wait)


def hide():
    """Tuck Blender's window away, as Cmd+H would.

    `open -j` asks for a hidden launch, but Blender shows itself once its
    window is up, so it is hidden again after its MCP server answers.
    """
    # AppKit's own hide through JavaScript for Automation: no Apple Event, so
    # no permission prompt (asking System Events to do it needs one)
    subprocess.run(["osascript", "-l", "JavaScript", "-e", HIDE],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)


def execute(code, timeout=900):
    """Run Python inside the shared Blender; returns what it printed."""
    ensure()
    result = call("execute_code", {"code": code}, timeout=timeout)
    return (result or {}).get("result", "")


def run_job(script, args, label="job", timeout=900):
    """Run a tool's Blender script as if it were `blender --python script -- args`.

    It runs in a scene of its own, which is removed afterwards along with
    everything the script created. Returns everything the script printed.
    """
    code = _JOB_TEMPLATE % {
        "script": json.dumps(os.path.abspath(script)),
        "folder": json.dumps(os.path.dirname(os.path.abspath(script))),
        "common": json.dumps(os.path.join(COMMON, "blender")),
        "args": json.dumps([str(a) for a in args]),
        "label": json.dumps("bengkel-" + label),
        "tracked": json.dumps(TRACKED),
    }
    return execute(code, timeout=timeout)


_JOB_TEMPLATE = r'''
import bpy, runpy, sys
_tracked = %(tracked)s
_before = {a: {i.as_pointer() for i in getattr(bpy.data, a)} for a in _tracked if hasattr(bpy.data, a)}
_wm = bpy.context.window_manager
_shown = [w.scene for w in _wm.windows]
_scene = bpy.data.scenes.new(%(label)s)
for _w in _wm.windows:
    _w.scene = _scene
_argv, _path = sys.argv, list(sys.path)
sys.argv = [bpy.app.binary_path, "--python", %(script)s, "--"] + %(args)s
sys.path[:0] = [%(folder)s, %(common)s]
try:
    runpy.run_path(%(script)s, run_name="__main__")
finally:
    sys.argv, sys.path[:] = _argv, _path
    for _w, _s in zip(_wm.windows, _shown):
        try:
            _w.scene = _s
        except ReferenceError:
            pass
    _new = []
    for _a, _old in _before.items():
        _new += [i for i in getattr(bpy.data, _a) if i.as_pointer() not in _old]
    if _new:
        bpy.data.batch_remove(_new)
'''
