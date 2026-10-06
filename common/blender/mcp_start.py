"""
Started with the shared Blender that bengkel opens: turn on the Blender MCP
add-on and start its server on port 9876, the port Claude's `blender` MCP
server and every bengkel tool talk to.

The server has to start from a timer, once Blender's window is up - the add-on
queues its commands onto Blender's main loop, which does not run until then.
"""

import subprocess

import addon_utils
import bpy

PORT = 9876
HIDE = ('ObjC.import("AppKit"); var a = $.NSRunningApplication.runningApplicationsWithBundleIdentifier("org.blenderfoundation.blender"); for (var i = 0; i < a.count; i++) a.objectAtIndex(i).hide;')


def start():
    try:
        addon_utils.enable("addon", default_set=True, persistent=True)
        bpy.context.scene.blendermcp_port = PORT
        bpy.ops.blendermcp.start_server()
        print("bengkel: Blender MCP listening on", PORT)
        for delay in (0.5, 1.5, 3.0):
            bpy.app.timers.register(hide, first_interval=delay)
    except Exception as exc:                          # noqa: BLE001
        print("bengkel: Blender MCP did not start yet:", exc)
        return 1.0                                    # try again in a second
    return None


def hide():
    """Tuck the window away, as Cmd+H would. bengkel opens this Blender to
    work in, not to look at - its Dock icon brings it back. Blender shows
    itself once its window is up, whatever `open -j` asked, so this runs from
    here, a few times over the first seconds."""
    # AppKit's own hide, run through JavaScript for Automation. It sends no
    # Apple Event, so macOS asks no permission - telling System Events to do
    # it instead made macOS ask whether Blender may control System Events.
    subprocess.Popen(["osascript", "-l", "JavaScript", "-e", HIDE],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return None


bpy.app.timers.register(start, first_interval=1.0)
