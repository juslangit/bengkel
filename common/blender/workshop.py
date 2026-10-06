"""
Small helpers for Blender scripts that run in bengkel's shared MCP Blender.
"""

import bpy


def fresh_scene():
    """Start the job from an empty scene.

    Headless, that was read_factory_settings. In the shared Blender it must not
    be: a factory reset unloads every add-on, the MCP server with them, and
    throws away whatever else is open. So empty only the scene this job was
    given - bengkel's MCP runner creates it for the job and removes it after.
    """
    if bpy.app.background:
        bpy.ops.wm.read_factory_settings(use_empty=True)
        return
    scene = bpy.context.scene
    for obj in list(scene.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def save_blend(path):
    """Write this job's scene, and only it, to a .blend.

    save_as_mainfile in the shared Blender would write every scene open in it -
    Claude's, boneka's - into the tool's output, and unless told `copy` it
    would also make that output the file Blender has open, so the next Cmd+S
    anywhere overwrites it. libraries.write takes just the scene and what it
    uses, and leaves the open file alone.
    """
    if bpy.app.background:
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True)
        return
    bpy.data.libraries.write(path, {bpy.context.scene}, path_remap="ABSOLUTE",
                             compress=True)
