"""
Make a watertight lump for the tests, and export it as a .glb.

Quadriflow only works on a closed surface. Every model on this machine that is
worth remeshing is a downloaded game character, and not one of them is closed —
they are a dozen open shells with holes where the geometry meets. Those all go
down jaring's voxel path, which means the quad path would never be tested at
all without something built for the purpose.

So: a sphere, dense enough that remeshing it is a real reduction and not a
rounding error, roughened enough that the remesh has something to do, and
closed by construction.

    blender --background --factory-startup --python make-blob.py -- out.glb
"""

import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.5, segments=128, ring_count=64)
blob = bpy.context.active_object
blob.name = "blob"

# Dent it, so the surface is not something a remesher can reproduce by
# accident, and a baked normal map has real detail to record.
texture = bpy.data.textures.new("lumps", type="CLOUDS")
texture.noise_scale = 0.35
displace = blob.modifiers.new("lumps", "DISPLACE")
displace.texture = texture
displace.strength = 0.22
bpy.ops.object.modifier_apply(modifier=displace.name)

# Half a metre across and a metre tall-ish, which is a believable prop rather
# than a unit sphere at the origin.
blob.scale = (1.0, 0.85, 1.4)
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)

bpy.ops.export_scene.gltf(filepath=out, export_format="GLB",
                          use_selection=True, export_yup=True)
print("BLOB %d triangles" % sum(max(len(p.vertices) - 2, 1)
                                for p in blob.data.polygons))
