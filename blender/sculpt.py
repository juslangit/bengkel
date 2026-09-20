"""
The sculpt pass.

A body made of a box, two cylinders and a sphere reads as a box, two cylinders
and a sphere however carefully they are placed. This is the step that turns an
assembly into a form.

Headless Blender cannot drive sculpt-mode brushes - they need a viewport - but
it can drive the thing a sculptor actually reaches for first, which is the
voxel remesh. Every soft part is rebuilt as one continuous skin over the volume
they occupy together, so the seam where an arm meets a shoulder stops being a
seam, and then the surface is relaxed and shaded smooth.

Three things have to survive that, and each is handled here:

  * **Colour.** A remesh keeps one material, so the parts are grouped by colour
    and each group is remeshed on its own. A blue torso and a skin-coloured
    forearm stay blue and skin-coloured, and the join between them reads as a
    sleeve, which is what it is.
  * **Weights.** A remesh throws away vertex groups, so the groups are painted
    on before and transferred back afterwards from the original geometry. That
    is what keeps the rig exact rather than guessed.
  * **Thin things.** A voxel grid swallows anything thinner than about two
    voxels. Those parts are measured and left alone rather than dissolved.
"""

import bpy
from mathutils import Vector


def fuse(objects, plan, on_progress=None):
    """
    Remesh the soft parts of a model into continuous skins, colour by colour,
    and hand back every object still in the scene.
    """
    soft, hard = _split(objects, plan)
    if not soft:
        return list(objects)

    height = max(plan.get("height", 1.0), 1e-3)

    groups = {}
    for obj in soft:
        key = obj.data.materials[0].name if obj.data.materials else "_none"
        groups.setdefault(key, []).append(obj)

    # The grid is sized per colour group, not once for the whole model. One
    # tiny part - the tip of an ear - used to drag the global voxel size down
    # until the body was remeshed at a millimetre, which both exploded the
    # triangle count and left every intersection as a visible crease, because
    # a grid that fine simply reproduces the parts it was given.
    made, leftover = [], []
    for i, (key, members) in enumerate(sorted(groups.items())):
        if on_progress:
            on_progress(i, len(groups), key)
        voxel = _voxel_size(members, height)
        survives = [o for o in members if _thinnest(o) >= voxel * 1.6]
        leftover += [o for o in members if o not in survives]
        if survives:
            made.append(_fuse_group(survives, voxel))
    return made + hard + leftover


def _split(objects, plan):
    hardness = {st["part"]: st.get("hard", True) for st in plan["steps"]}
    soft, hard = [], []
    for obj in objects:
        if obj.type != "MESH":
            continue
        (hard if hardness.get(obj.get("bk_part", obj.name), True) else soft).append(obj)
    return soft, hard


def _dimensions(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return [max(c[i] for c in corners) - min(c[i] for c in corners)
            for i in range(3)]


def _thinnest(obj):
    return min(_dimensions(obj))


def _voxel_size(members, height):
    """
    Fine enough to keep the slimmest thing in this group, coarse enough to
    actually fuse where parts overlap and not to drown the machine.

    The slimmest limb on a person is the hand, at about four centimetres
    across. The floor of height/220 stops one small part from making the whole
    group absurdly dense; anything under it is excluded from the group instead
    and kept as it was built.
    """
    widths = sorted(_thinnest(o) for o in members)
    slimmest = widths[0] if widths else height * 0.05
    if len(widths) > 2 and slimmest < height / 60.0:
        slimmest = widths[1]          # ignore one runt, not the whole spread
    return max(min(slimmest / 2.6, height / 55.0), height / 200.0, 1e-4)


def _fuse_group(members, voxel):
    source = _join([_copy(o) for o in members], "bk_weights")
    skin = _join(members, "bk_skin")

    material = skin.data.materials[0] if skin.data.materials else None
    _voxel_remesh(skin, voxel)
    _relax(skin, iterations=6, factor=0.62)

    skin.data.materials.clear()
    if material:
        skin.data.materials.append(material)
    for poly in skin.data.polygons:
        poly.use_smooth = True

    _transfer_weights(source, skin)
    bpy.data.objects.remove(source, do_unlink=True)

    skin["bk_part"] = members[0].get("bk_part", skin.name)
    skin["bk_sculpted"] = True
    return skin


def _copy(obj):
    dup = obj.copy()
    dup.data = obj.data.copy()
    bpy.context.collection.objects.link(dup)
    return dup


def _join(objects, name):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    if len(objects) > 1:
        bpy.ops.object.join()
    joined = bpy.context.active_object
    joined.name = name
    return joined


def _voxel_remesh(obj, voxel):
    mesh = obj.data
    mesh.remesh_voxel_size = voxel
    mesh.remesh_voxel_adaptivity = 0.0
    for flag in ("use_remesh_fix_poles", "use_remesh_preserve_volume"):
        if hasattr(mesh, flag):
            setattr(mesh, flag, True)
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.voxel_remesh()


def _relax(obj, iterations, factor):
    """Take the stair-stepping off the voxel grid without losing the form."""
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new("bk_relax", "SMOOTH")
    mod.factor = factor
    mod.iterations = iterations
    bpy.ops.object.modifier_apply(modifier=mod.name)


def _transfer_weights(source, skin):
    """
    Paint the original parts' vertex groups back onto the new skin. Nearest
    face, interpolated, so a vertex between two bones gets a share of both.
    """
    if not source.vertex_groups:
        return
    bpy.ops.object.select_all(action="DESELECT")
    source.select_set(True)
    skin.select_set(True)
    bpy.context.view_layer.objects.active = skin

    mod = skin.modifiers.new("bk_weights", "DATA_TRANSFER")
    mod.object = source
    mod.use_vert_data = True
    mod.data_types_verts = {"VGROUP_WEIGHTS"}
    mod.vert_mapping = "POLYINTERP_NEAREST"
    mod.layers_vgroup_select_src = "ALL"
    mod.layers_vgroup_select_dst = "NAME"
    try:
        bpy.ops.object.datalayout_transfer(modifier=mod.name)
        bpy.ops.object.modifier_apply(modifier=mod.name)
    except RuntimeError:
        skin.modifiers.remove(mod)
        _nearest_group_fallback(source, skin)


def _nearest_group_fallback(source, skin):
    """If the transfer modifier refuses, give every vertex its nearest part."""
    names = [g.name for g in source.vertex_groups]
    if not names:
        return
    made = {n: skin.vertex_groups.new(name=n) for n in names}
    matrix = source.matrix_world
    points = [(matrix @ v.co, v.groups[0].group if v.groups else 0)
              for v in source.data.vertices]
    for vert in skin.data.vertices:
        here = skin.matrix_world @ vert.co
        best = min(points, key=lambda p: (p[0] - here).length_squared)
        made[names[min(best[1], len(names) - 1)]].add([vert.index], 1.0, "REPLACE")
