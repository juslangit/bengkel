"""
Give a model its surface, inside a headless Blender.

Each part gets a flat colour with a photograph multiplied over it, plus a
normal map and a roughness map derived from the same photograph. That shape —
an image and a constant colour into a Multiply, into Base Color — is the one
Blender's glTF exporter recognises as `baseColorFactor x baseColorTexture`, so
one greyscale map is shared by every part using that surface while each keeps
its own colour. Anything more elaborate in the node tree does not survive the
export, which is a thing you discover by looking at the result rather than by
reading a message.

The maps themselves are not made here. boneka's tools/pbr.py derives them from
one photograph, and its numbers were arrived at by looking at real surfaces, so
it is used rather than reinvented — but it is written in Pillow and numpy, and
Blender ships its own Python without either. kulit's server runs it first, in
system Python, and hands this three finished file paths.

Job:

    {"job": "dress", "source": "...glb", "out": "...",
     "parts": [{"name": "Body", "colour": "#8b5a2b", "surface": "wood",
                "scale": 1.0,
                "maps": {"detail": "...png", "normal": "...png",
                         "rough": "...png", "metallic": 0.8}}]}
"""

import json
import os
import sys
import time

import bpy

ANSWER = "@@JOB@@"


# --------------------------------------------------------------------------
# colours
# --------------------------------------------------------------------------

def hex_to_rgba(value):
    """#rrggbb to linear RGBA.

    Blender works in linear light and a hex colour is sRGB, so the conversion
    is not a divide by 255. Skipping it makes every colour come out visibly
    paler than the swatch that was clicked.
    """
    value = (value or "#cccccc").lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    out = []
    for i in (0, 2, 4):
        channel = int(value[i:i + 2], 16) / 255.0
        out.append(channel / 12.92 if channel <= 0.04045
                   else ((channel + 0.055) / 1.055) ** 2.4)
    return (out[0], out[1], out[2], 1.0)


# --------------------------------------------------------------------------
# the maps
# --------------------------------------------------------------------------

def image(path):
    img = bpy.data.images.load(path, check_existing=True)
    # Every one of these is data, not a picture. A normal map read as sRGB
    # comes out with the wrong slope and the light falls the wrong way.
    img.colorspace_settings.name = "Non-Color"
    return img


def material_for(name, colour, made, scale):
    """Flat colour, with the photograph's detail multiplied over it."""
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    nodes, links = material.node_tree.nodes, material.node_tree.links
    bsdf = next(n for n in nodes if n.type == "BSDF_PRINCIPLED")
    rgba = hex_to_rgba(colour)
    bsdf.inputs["Base Color"].default_value = rgba
    bsdf.inputs["Roughness"].default_value = 0.62

    if not made.get("detail"):
        return material

    # How many times the photograph repeats across the model. One mapping node
    # feeds every image, so the three maps cannot drift out of register with
    # each other - which shows up as relief that does not match the grain.
    coords = nodes.new("ShaderNodeTexCoord")
    coords.location = (-1200, 0)
    mapping = nodes.new("ShaderNodeMapping")
    mapping.location = (-1000, 0)
    mapping.inputs["Scale"].default_value = (scale, scale, scale)
    links.new(coords.outputs["UV"], mapping.inputs["Vector"])

    def tex(path, y):
        node = nodes.new("ShaderNodeTexImage")
        node.image = image(path)
        node.location = (-780, y)
        links.new(mapping.outputs["Vector"], node.inputs["Vector"])
        return node

    if made.get("rough"):
        links.new(tex(made["rough"], -40).outputs["Color"], bsdf.inputs["Roughness"])

    if made.get("normal"):
        normal = nodes.new("ShaderNodeNormalMap")
        normal.location = (-420, -330)
        links.new(tex(made["normal"], -330).outputs["Color"], normal.inputs["Color"])
        links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])

    if made.get("metallic"):
        bsdf.inputs["Metallic"].default_value = float(made["metallic"])

    # ShaderNodeMix, not the legacy ShaderNodeMixRGB: Blender 5's glTF
    # exporter reads the modern node as baseColorFactor x baseColorTexture and
    # silently ignores the old one, which loses the colour and leaves every
    # part the same flat grey.
    mix = nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    mix.inputs["Factor"].default_value = 1.0
    mix.inputs[6].default_value = rgba
    mix.location = (-420, 240)
    links.new(tex(made["detail"], 240).outputs["Color"], mix.inputs[7])
    links.new(mix.outputs[2], bsdf.inputs["Base Color"])
    return material


# --------------------------------------------------------------------------
# the job
# --------------------------------------------------------------------------

def load(path):
    lower = path.lower()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    if lower.endswith((".glb", ".gltf")):
        bpy.ops.import_scene.gltf(filepath=path)
    elif lower.endswith(".fbx"):
        bpy.ops.import_scene.fbx(filepath=path)
    elif lower.endswith(".obj"):
        bpy.ops.wm.obj_import(filepath=path)
    elif lower.endswith(".blend"):
        bpy.ops.wm.open_mainfile(filepath=path)
    else:
        raise RuntimeError("kulit does not know how to open %s"
                           % os.path.splitext(path)[1])
    return [o for o in bpy.context.scene.objects if o.type == "MESH"]


def unwrap_if_bare(obj):
    """A model with no UVs shows a texture as one smeared pixel.

    jaring's output always has them; a download often does not, and neither
    says so. Rather than refuse, give it a quick projection and mention it.
    """
    if obj.data.uv_layers:
        return False
    obj.data.uv_layers.new(name="UVMap")
    for other in bpy.context.scene.objects:
        other.select_set(other is obj)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=1.15, island_margin=0.002)
    bpy.ops.object.mode_set(mode="OBJECT")
    return True


def run(job):
    out = job["out"]
    os.makedirs(out, exist_ok=True)
    stem = job["name"]

    meshes = load(job["source"])
    if not meshes:
        raise RuntimeError("there is no mesh in that file")

    wanted = {p["name"]: p for p in job["parts"]}
    notes, dressed = [], []

    for obj in meshes:
        part = wanted.get(obj.name)
        if part is None:
            # A part nobody chose for keeps whatever it had; silently painting
            # it a default colour would be worse than leaving it.
            continue
        if unwrap_if_bare(obj):
            notes.append("%s had no UVs, so it was given a quick projection. "
                         "Run it through jaring for a proper one." % obj.name)

        made = {k: v for k, v in (part.get("maps") or {}).items()
                if k == "metallic" or (v and os.path.exists(v))}
        material = material_for("kulit_" + obj.name, part.get("colour"),
                                made, float(part.get("scale") or 1.0))
        obj.data.materials.clear()
        obj.data.materials.append(material)
        dressed.append({"name": obj.name,
                        "surface": part.get("surface") or "detail",
                        "colour": part.get("colour"),
                        "textured": bool(made.get("detail"))})

    if not dressed:
        raise RuntimeError("none of the parts named are in that model")

    plain = [d["name"] for d in dressed if not d["textured"]]
    if plain:
        notes.append("No photograph was found for %s, so %s came out as flat "
                     "colour. boneka's textures/source folder is where they live."
                     % (", ".join(sorted({d["surface"] for d in dressed
                                          if not d["textured"]})),
                        ", ".join(plain[:4]) + ("…" if len(plain) > 4 else "")))

    for obj in bpy.context.scene.objects:
        obj.select_set(True)
    glb = os.path.join(out, "%s.glb" % stem)
    bpy.ops.export_scene.gltf(filepath=glb, export_format="GLB",
                              use_selection=False, export_yup=True,
                              export_apply=False, export_image_format="JPEG")

    blend = os.path.join(out, "%s.blend" % stem)
    bpy.ops.wm.save_as_mainfile(filepath=blend)

    return {"ok": True, "glb": glb, "blend": blend,
            "dressed": dressed, "notes": notes,
            "bytes": os.path.getsize(glb)}


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
