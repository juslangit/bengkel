"""
The remesher, run inside a headless Blender.

A model off the internet is built to look right in a render: half a million
triangles, no UVs worth the name, and a mesh nobody can animate. A model for a
game has to be light, has to have UVs, and has to keep the detail it just lost
somewhere — in a normal map.

This does that chain, in one go, with nobody watching:

    1. remesh      rebuild the surface out of even quads
    2. unwrap      cut and lay out UVs on the new surface
    3. bake        record the original's detail into a normal map
    4. LODs        reduce the result for distance, keeping the same map

The maths here is lifted from Retopo Kit, the Blender add-on that solved the
same problem with a person watching it. The numbers are the ones that were
found to work on real sculpts — two percent of the diagonal for ray distance,
four pixels of island margin, the quad-size-to-face-count formula — and they
are not re-derived here, only re-used.

Called by jaring's server with a job file:

    {"job": "remesh", "source": "...glb", "quad_cm": 2.0, "texture": 2048,
     "lods": 2, "symmetry": true, "out": "/where/to/put/it"}

and answers on one line beginning with @@JOB@@.
"""

import json
import math
import os
import sys
import time

import bpy
import bmesh
from mathutils import Vector

ANSWER = "@@JOB@@"


# --------------------------------------------------------------------------
# measuring, before deciding anything
# --------------------------------------------------------------------------

def surface_area(obj):
    """Total area of the object in square metres, with modifiers applied."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    mesh = evaluated.to_mesh()
    # Polygon areas are in the object's own space, so its scale has to be
    # folded back in or a model imported at 0.01 looks a hundred times smaller
    # than it is and gets a hundred times too few faces.
    scale = obj.matrix_world.to_scale()
    factor = abs(scale.x * scale.y * scale.z) ** (2.0 / 3.0)
    area = sum(polygon.area for polygon in mesh.polygons) * factor
    evaluated.to_mesh_clear()
    return area


def faces_for_quad_size(area, quad_cm):
    """How many quads of that size it takes to cover this much surface.

    A quad s metres across covers s * s square metres, so the count is the area
    divided by that. Clamped to a range Quadriflow can actually work in.
    """
    side = max(quad_cm, 0.01) / 100.0
    return max(20, min(int(area / (side * side)), 500000))


def diagonal_cm(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    low = Vector(min(c[i] for c in corners) for i in range(3))
    high = Vector(max(c[i] for c in corners) for i in range(3))
    return (high - low).length * 100.0


def ray_distance_m(obj):
    """How far the bake rays travel.

    Two percent of the model's own diagonal: far enough to reach the detail,
    not far enough to punch through and hit the opposite side.
    """
    return max(0.2, diagonal_cm(obj) * 0.02) / 100.0


def nonmanifold_edges(mesh):
    """Edges not shared by exactly two faces. Quadriflow refuses any mesh with
    these, and downloaded models are full of them."""
    bm = bmesh.new()
    bm.from_mesh(mesh)
    count = sum(1 for edge in bm.edges if not edge.is_manifold)
    bm.free()
    return count


def triangles(obj):
    return sum(max(len(p.vertices) - 2, 1) for p in obj.data.polygons)


def extent(obj):
    """How big the object is in the world, in metres, as (x, y, z).

    Reported with every result so that "it came back the same size it went in"
    is something a test can check rather than something you notice by eye a
    week later.
    """
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return [round(max(c[i] for c in corners) - min(c[i] for c in corners), 4)
            for i in range(3)]


# --------------------------------------------------------------------------
# loading, and getting down to one object
# --------------------------------------------------------------------------

def wipe():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def load(path):
    lower = path.lower()
    if lower.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    elif lower.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    elif lower.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path)
    elif lower.endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        raise RuntimeError("jaring does not know how to open %s"
                           % os.path.splitext(path)[1])
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def as_one(meshes):
    """Join every mesh into one object.

    A downloaded model arrives as twenty separate pieces — a body, two eyes,
    six buttons — and remeshing each separately would give twenty shells that
    no longer fit together. Quadriflow wants one continuous surface, so they
    are joined first. Armatures and empties are left where they are.
    """
    if not meshes:
        raise RuntimeError("there is no mesh in that file")

    for obj in bpy.context.scene.objects:
        obj.select_set(False)

    # Modifiers have to go before a join or they apply to the wrong geometry.
    for obj in meshes:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        for mod in list(obj.modifiers):
            if mod.type in ("ARMATURE",):
                obj.modifiers.remove(mod)

    # A model imported from glTF arrives parented into one or two empties that
    # carry the whole scene's rotation and scale. Only the mesh is exported at
    # the end, so anything still living on a parent is silently dropped - and
    # a model whose root node scaled it by a hundredth comes back a hundred
    # times too big, looking like a remesh that went mad rather than a
    # transform that went missing. Clearing the parent keeps the transform on
    # the mesh itself; applying it then makes it real geometry, which is also
    # what the area and diagonal measured below depend on.
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]

    if len(meshes) > 1:
        bpy.ops.object.join()
    joined = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    weld(joined)
    return joined


def weld(obj, threshold=0.0001):
    """Merge vertices that are in the same place, and face the same way out.

    glTF has no shared vertices: every triangle carries its own three corners,
    because each corner holds its own normal and UV. A model that has been
    through a .glb therefore arrives as loose triangles that merely touch, and
    **every single edge in it is non-manifold** — a sphere exported and
    re-imported came back with 32,512 of them.

    Quadriflow needs a closed surface. Without this step it never gets one, no
    matter what the model is, so every remesh fell back to voxels and the quad
    path might as well not have existed. A tenth of a millimetre is far below
    anything modelled on purpose and far above floating-point noise.

    Normals are made consistent at the same time: welded triangles that face
    opposite ways are still a hole as far as a remesher is concerned.
    """
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=threshold)
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


# --------------------------------------------------------------------------
# the four steps
# --------------------------------------------------------------------------

def remesh(high, quad_cm, symmetry, sharp):
    """Rebuild the surface out of even quads. Returns (low, how, target, area)."""
    area = surface_area(high)
    if area <= 0.0:
        raise RuntimeError("that model has no surface area to remesh")
    target = faces_for_quad_size(area, quad_cm)
    want = extent(high)
    holes = nonmanifold_edges(high.data)

    def fresh_copy():
        copy = high.copy()
        copy.data = high.data.copy()
        copy.name = "LP_" + high.name
        copy.data.name = copy.name
        for collection in high.users_collection:
            collection.objects.link(copy)
        # Materials come off: it is about to be given one of its own with the
        # baked map in it, and the original's twelve would fight it.
        copy.data.materials.clear()
        return copy

    def alone(obj):
        for other in bpy.context.scene.objects:
            other.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

    low = fresh_copy()
    alone(low)

    try:
        outcome = bpy.ops.object.quadriflow_remesh(
            mode="FACES", target_faces=target,
            use_mesh_symmetry=symmetry, use_preserve_sharp=sharp,
            use_preserve_boundary=True, smooth_normals=True, seed=0)
    except RuntimeError:
        outcome = {"CANCELLED"}

    # Two ways Quadriflow fails, and it announces neither.
    #
    # It cancels rather than raising when it dislikes a mesh, leaving an
    # untouched copy that looks like a result and then bakes a flat, useless
    # normal map from it. And on a mesh that is not watertight - which every
    # downloaded game character is, being a dozen open shells - it returns
    # FINISHED and hands back shards: a different shape, at a different size,
    # in a different place. A paladin 1.3 metres tall came back 8 metres
    # across, and nothing anywhere said so.
    #
    # Comparing the result's own size against what went in catches both, and
    # catches whatever third way there is that has not been seen yet. A real
    # remesh of a thing is the same size as the thing.
    kept_shape = (
        "FINISHED" in outcome
        and all(abs(a - b) <= 0.05 * max(b, 1e-6) for a, b in zip(extent(low), want))
    )
    if kept_shape:
        return low, "quads", target, area

    # Voxels do not care about holes. The same quad size drives the voxel
    # size, so the one setting he chose still means what it said. The mangled
    # copy is thrown away first - what Quadriflow left behind is not a
    # starting point for anything.
    bpy.data.objects.remove(low, do_unlink=True)
    low = fresh_copy()
    alone(low)

    low.data.remesh_voxel_size = max(quad_cm / 100.0, 0.0005)
    low.data.remesh_voxel_adaptivity = 0.0
    try:
        voxels = bpy.ops.object.voxel_remesh()
    except RuntimeError:
        voxels = {"CANCELLED"}
    if "FINISHED" not in voxels:
        raise RuntimeError("neither quads nor voxels would take that mesh "
                           "(%s edges are not watertight)" % f"{holes:,}")
    return low, "voxels", target, area


def unwrap(low, texture):
    """Cut and lay out UVs. Returns how much of the map the islands fill."""
    mesh = low.data
    if not mesh.uv_layers:
        mesh.uv_layers.new(name="UVMap")

    # A few pixels between islands, as a fraction of the texture, so the bake
    # cannot bleed from one island into its neighbour.
    margin = 4.0 / texture

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(66.0),
                             island_margin=margin, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.seams_from_islands()
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.pack_islands(margin=margin, rotate=True)
    bpy.ops.object.mode_set(mode="OBJECT")

    layer = mesh.uv_layers.active
    total = 0.0
    for polygon in mesh.polygons:
        loops = [layer.data[i].uv for i in polygon.loop_indices]
        # Shoelace: the area of a polygon from its corners.
        area = 0.0
        for i in range(len(loops)):
            a, b = loops[i], loops[(i + 1) % len(loops)]
            area += a.x * b.y - b.x * a.y
        total += abs(area) * 0.5
    return min(total * 100.0, 100.0)


def material_with(low, image, name):
    """Give the low-poly a material with somewhere to bake into.

    The image node is deliberately left unconnected. Wiring the map into the
    shader before the bake makes the material read the very image the bake is
    writing, which Blender reports as a circular dependency and resolves by
    guessing. The wire goes in afterwards, in wire_up(), once there is
    something real in the image to read.
    """
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    low.data.materials.clear()
    low.data.materials.append(material)

    nodes = material.node_tree.nodes
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.image.colorspace_settings.name = "Non-Color"
    texture.location = (-700, 0)
    return texture


def wire_up(low, texture):
    """Connect the finished map into the material, so it travels with the
    model instead of sitting beside it unused."""
    tree = low.data.materials[0].node_tree
    nodes, links = tree.nodes, tree.links
    principled = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")

    normal = nodes.new("ShaderNodeNormalMap")
    normal.location = (-380, 0)
    links.new(texture.outputs["Color"], normal.inputs["Color"])
    links.new(normal.outputs["Normal"], principled.inputs["Normal"])


def bake(low, high, texture):
    """Project the original's surface detail onto the new one as a normal map.

    The low-poly is smooth and dumb. The bake fires a ray out of every pixel of
    its surface, finds where that ray hits the original, and writes down which
    way the original was facing there. The result makes the light behave as
    though the detail were still present.
    """
    image = bpy.data.images.new(low.name + "_Normal", texture, texture,
                                alpha=False, float_buffer=False, is_data=True)
    node = material_with(low, image, low.name + "_Material")
    # The node has to be the selected one or Blender bakes into whichever
    # image node it finds first, which may be one of the original's.
    node.select = True
    low.data.materials[0].node_tree.nodes.active = node

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1          # a normal bake reads geometry, not light
    scene.cycles.device = "CPU"

    high.hide_set(False)
    high.hide_render = False
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    high.select_set(True)
    low.select_set(True)
    bpy.context.view_layer.objects.active = low

    distance = ray_distance_m(low)
    settings = scene.render.bake
    # None of these are inherited from the file. A scene where somebody last
    # baked vertex colours otherwise fails with "no active color attribute",
    # which says nothing at all about the real problem.
    settings.target = "IMAGE_TEXTURES"
    settings.use_selected_to_active = True
    settings.use_cage = False
    settings.cage_extrusion = distance
    settings.max_ray_distance = distance * 2.0
    settings.margin = max(2, texture // 512)
    settings.use_clear = True

    bpy.ops.object.bake(type="NORMAL", normal_space="TANGENT")
    wire_up(low, node)
    return image


def apply_modifiers(obj):
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    baked = bpy.data.meshes.new_from_object(
        obj.evaluated_get(depsgraph), preserve_all_data_layers=True,
        depsgraph=depsgraph)
    previous = obj.data
    obj.data = baked
    obj.data.name = obj.name
    obj.modifiers.clear()
    if previous.users == 0:
        bpy.data.meshes.remove(previous)


def make_lods(low, levels, ratio=0.5):
    """Build the reduced versions, named the way Unreal reads them.

    Each level is decimated down from the one above rather than remeshed from
    the original. That matters: reducing an existing mesh keeps its UVs, so
    every level shares the one normal map that was already baked. Remeshing
    each level would need its own unwrap and its own texture, which is not how
    LODs work.
    """
    base = low.name
    low.name = base + "_LOD0"
    low.data.name = low.name

    made = [low]
    previous = low
    for level in range(1, levels + 1):
        copy = previous.copy()
        copy.data = previous.data.copy()
        copy.name = "%s_LOD%d" % (base, level)
        copy.data.name = copy.name
        for collection in previous.users_collection:
            collection.objects.link(copy)

        decimate = copy.modifiers.new("LOD", "DECIMATE")
        decimate.decimate_type = "COLLAPSE"
        decimate.ratio = ratio
        decimate.use_collapse_triangulate = True
        apply_modifiers(copy)
        # A collapse decimate can leave faces with no area, which the glTF
        # exporter reports as "not valid" and then writes out anyway.
        copy.data.validate(verbose=False)

        made.append(copy)
        previous = copy
    return made


# --------------------------------------------------------------------------
# the job
# --------------------------------------------------------------------------

def run(job):
    source = job["source"]
    quad_cm = float(job.get("quad_cm") or 2.0)
    texture = int(job.get("texture") or 2048)
    levels = int(job.get("lods") or 0)
    want_bake = bool(job.get("bake", True))
    out = job["out"]
    os.makedirs(out, exist_ok=True)
    stem = job.get("name") or os.path.splitext(os.path.basename(source))[0]

    notes = []
    wipe()
    high = as_one(load(source))
    before = triangles(high)
    was = extent(high)

    low, how, target, area = remesh(high, quad_cm, bool(job.get("symmetry", True)),
                                    bool(job.get("sharp", True)))
    if how == "voxels":
        notes.append(
            "Quadriflow could not make quads out of that mesh — it is not "
            "watertight, which almost every downloaded model is not. It was "
            "remeshed with voxels instead: even, and the right shape, but not "
            "in neat quad rows.")
    after = triangles(low)

    coverage = unwrap(low, texture)
    if coverage < 25.0:
        notes.append("The UV islands only fill %d%% of the map, so most of the "
                     "texture is empty space. A simpler shape packs better."
                     % round(coverage))

    map_path = ""
    if want_bake:
        image = bake(low, high, texture)
        map_path = os.path.join(out, "%s_normal.png" % stem)
        image.filepath_raw = map_path
        image.file_format = "PNG"
        image.save()

    # The original is not part of what gets exported, and leaving it in the
    # file means the .glb carries the half-million triangles we just spent a
    # minute removing.
    bpy.data.objects.remove(high, do_unlink=True)

    pieces = make_lods(low, levels) if levels else [low]
    counts = [triangles(p) for p in pieces]

    # One file per level, not all of them in one.
    #
    # LODs are alternatives to each other: a game engine picks one by distance
    # and draws that. Exported into a single .glb they are not alternatives,
    # they are four copies of a model standing inside one another, and the file
    # that was supposed to be the light one is heavier than the original.
    files = []
    for index, piece in enumerate(pieces):
        for obj in bpy.context.scene.objects:
            obj.select_set(obj is piece)
        bpy.context.view_layer.objects.active = piece

        name = stem if index == 0 else "%s_LOD%d" % (stem, index)
        path = os.path.join(out, "%s.glb" % name)
        bpy.ops.export_scene.gltf(filepath=path, export_format="GLB",
                                  use_selection=True, export_yup=True,
                                  export_apply=True)
        files.append({"level": index, "path": path, "tris": counts[index]})

    glb = files[0]["path"]

    # The .blend keeps all of them together, because that is the file you open
    # when you want to look at the levels side by side.
    blend = os.path.join(out, "%s.blend" % stem)
    bpy.ops.wm.save_as_mainfile(filepath=blend)

    return {
        "ok": True,
        "glb": glb,
        "blend": blend,
        "normal": map_path,
        "before": before,
        "after": after,
        "was": was,
        "now": extent(pieces[0]),
        "target": target,
        "how": how,
        "area": round(area, 3),
        "coverage": round(coverage, 1),
        "lods": files,
        "notes": notes,
    }


def main():
    job_file = sys.argv[sys.argv.index("--") + 1]
    with open(job_file) as f:
        job = json.load(f)
    started = time.time()
    try:
        answer = run(job)
    except Exception as err:
        answer = {"ok": False, "problems": [str(err)]}
    answer["seconds"] = round(time.time() - started, 1)
    print(ANSWER + json.dumps(answer), flush=True)


if __name__ == "__main__":
    main()
