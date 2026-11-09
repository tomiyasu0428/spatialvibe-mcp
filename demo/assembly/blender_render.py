"""Blender (bpy) backdrop for the assembly reel: the same timeline as assembly.html, rendered with
real lighting, soft shadows and a phone screen that glows.

Run by render.py --blender with the separate Blender venv (bpy needs its own Python):
  .venv-blender/bin/python demo/assembly/blender_render.py out/<story>_scene.npz out/<story>_blender [--frames A-B] [--engine eevee|cycles]

Input (written by render.py): <scene>.npz with one triangle array per object in model axes
(mm, Z up), and <scene>.json with kinds, step order, slide vector and the screen image path.
Output: <dir>/NNNN.png, numbered by the 30 fps frame index of the whole reel, only for the part
of the reel where the 3D is on screen. Keep the timing constants in sync with assembly.html.
"""
import argparse
import json
import math
import time
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

FPS = 30
MM = 0.001


# ---- timeline (same numbers and curves as assembly.html) ----------------------------------------
def timeline(n_steps):
    T = {"in": 0, "read": 4200, "ctx": 9000, "steps": 11200, "step": 2400}
    T["fit"] = T["steps"] + n_steps * T["step"]
    T["ar"] = T["fit"] + 3600
    T["final"] = T["ar"] + 3400
    return T


def clamp(x, a=0.0, b=1.0):
    return min(b, max(a, x))


def ease(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def out(x):
    return 1 - (1 - clamp(x)) ** 3


def span(t, a, b):
    return clamp((t - a) / (b - a))


# ---- scene ---------------------------------------------------------------------------------------
def mesh_object(name, tris, mat):
    v = tris.reshape(-1, 3) * MM
    faces = [(i, i + 1, i + 2) for i in range(0, len(v), 3)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(v.tolist(), [], faces)
    me.validate()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    lines_collection().objects.link(ob)
    # weld the triangle soup so smooth-by-angle and freestyle see real edges
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
    bm.to_mesh(me)
    bm.free()
    for p in me.polygons:
        p.use_smooth = False
    me.materials.append(mat)
    return ob


def lines_collection():
    """Objects that get freestyle outlines (not the floor: its border would draw a horizon line)."""
    c = bpy.data.collections.get("lines") or bpy.data.collections.new("lines")
    if c.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(c)
    return c


def principled(name, color, rough=0.5, metal=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    if "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = coat
    if hasattr(m, "surface_render_method"):
        m.surface_render_method = "BLENDED"
    return m, b


def srgb(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("outdir")
    ap.add_argument("--frames", help="A-B (30 fps frame indices of the whole reel)")
    ap.add_argument("--engine", default="cycles", choices=["eevee", "cycles"])
    ap.add_argument("--samples", type=int, default=0)
    ap.add_argument("--step", type=int, default=1, help="render every Nth frame (2 = quick 15 fps pass; run again with 1 to fill in)")
    ap.add_argument("--scale", type=int, default=100, help="resolution percentage (for quick tests)")
    a = ap.parse_args(argv)

    npz = np.load(a.scene)
    meta = json.loads(Path(a.scene).with_suffix(".json").read_text(encoding="utf-8"))
    steps = meta["steps"]
    T = timeline(len(steps))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = 1080, 1920
    sc.render.resolution_percentage = a.scale
    sc.render.fps = FPS
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = "AgX" if "AgX" in [e.identifier for e in sc.view_settings.bl_rna.properties["view_transform"].enum_items] else "Filmic"
    sc.view_settings.look = "AgX - Base Contrast" if sc.view_settings.view_transform == "AgX" else "None"
    if a.engine == "cycles":
        sc.render.engine = "CYCLES"
        sc.cycles.device = "CPU"
        sc.cycles.samples = a.samples or 16
        sc.cycles.use_denoising = True
    else:
        sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in [e.identifier for e in sc.render.bl_rna.properties["engine"].enum_items] else "BLENDER_EEVEE"
        sc.eevee.taa_render_samples = a.samples or 48
        for attr, val in (("use_shadows", True), ("use_raytracing", True), ("shadow_ray_count", 2), ("shadow_step_count", 8)):
            if hasattr(sc.eevee, attr):
                setattr(sc.eevee, attr, val)
    # CAD-style outlines
    sc.render.use_freestyle = True
    sc.render.line_thickness_mode = "ABSOLUTE"
    sc.render.line_thickness = 1.6
    ls = sc.view_layers[0].freestyle_settings.linesets.new("edges")
    ls.select_by_visibility = True
    ls.select_crease = True
    ls.select_silhouette = True
    ls.select_border = True
    ls.select_by_collection = True
    ls.collection = lines_collection()
    ls.linestyle.color = (0.08, 0.08, 0.09)
    ls.linestyle.thickness = 1.3 * a.scale / 100
    sc.view_layers[0].freestyle_settings.crease_angle = math.radians(145)

    # world: soft warm studio
    w = bpy.data.worlds.new("studio")
    sc.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs["Color"].default_value = (*srgb("#efeee9"), 1)
    w.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.3
    sc.render.film_transparent = True   # the page's paper gradient shows through; the floor only catches shadows

    # materials
    WHITE, ORANGE = np.array(srgb("#f3f1ec")), np.array(srgb("#ff5a1f"))
    floor_m, _ = principled("floor", srgb("#e9e7e1"), rough=0.9)
    pipe_m, _ = principled("pipe", srgb("#b8bdc2"), rough=0.28, metal=0.9)
    phone_m, phone_b = principled("phone", srgb("#0d0e10"), rough=0.35, coat=0.25)

    objs = {}
    for name, kind in meta["kinds"].items():
        if kind == "parts":
            m, b = principled(f"part_{name}", tuple(WHITE), rough=0.55)
            if "Subsurface Weight" in b.inputs:
                b.inputs["Subsurface Weight"].default_value = 0.05
            objs[name] = (mesh_object(name, npz[name], m), b)
        elif kind == "context":
            m, b = (phone_m, phone_b) if name == meta["screen_of"] else (pipe_m, None)
            objs[name] = (mesh_object(name, npz[name], m), b)
    # pipe: smooth shading (it is a cylinder)
    for name, kind in meta["kinds"].items():
        if kind == "context" and name != meta["screen_of"]:
            for p in objs[name][0].data.polygons:
                p.use_smooth = True
            objs[name][0].data.shade_smooth_by_angle(angle=math.radians(40)) if hasattr(objs[name][0].data, "shade_smooth_by_angle") else None

    # phone screen: emissive image, planar UVs (u along X, v along the slide axis)
    scr = None
    if "_screen" in npz.files:
        m = bpy.data.materials.new("screen")
        m.use_nodes = True
        nt = m.node_tree
        for n in list(nt.nodes):
            nt.nodes.remove(n)
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(str(Path(meta["screen_png"]).resolve()))
        em = nt.nodes.new("ShaderNodeEmission")
        mix = nt.nodes.new("ShaderNodeMixShader")
        dark = nt.nodes.new("ShaderNodeBsdfPrincipled")
        dark.inputs["Base Color"].default_value = (0.01, 0.012, 0.016, 1)
        dark.inputs["Roughness"].default_value = 0.15
        outn = nt.nodes.new("ShaderNodeOutputMaterial")
        nt.links.new(tex.outputs["Color"], em.inputs["Color"])
        nt.links.new(dark.outputs[0], mix.inputs[1])
        nt.links.new(em.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], outn.inputs[0])
        em.inputs["Strength"].default_value = 2.2
        scr = mesh_object("screen", npz["_screen"], m)
        me = scr.data
        uvl = me.uv_layers.new()
        up = Vector(meta["slide"]).normalized()
        co = [v.co for v in me.vertices]
        us = [c.x for c in co]
        vs = [c.dot(up) for c in co]
        for loop in me.loops:
            c = me.vertices[loop.vertex_index].co
            uvl.data[loop.index].uv = ((c.x - min(us)) / (max(us) - min(us)), (c.dot(up) - min(vs)) / (max(vs) - min(vs)))
        scr_mix = mix

    # floor well below the pipe, so the holder casts a soft shadow
    pz = min(float(npz[n][..., 2].min()) for n in meta["kinds"]) * MM
    bpy.ops.mesh.primitive_plane_add(size=8, location=(0, 0, pz - 0.16))
    floor = bpy.context.object
    floor.data.materials.append(floor_m)
    floor.is_shadow_catcher = True

    # lights: big soft key from the front-left, rim from behind-right
    def area(name, loc, energy, size, color="#ffffff"):
        L = bpy.data.lights.new(name, "AREA")
        L.energy, L.size, L.color = energy, size, srgb(color)
        o = bpy.data.objects.new(name, L)
        o.location = loc
        sc.collection.objects.link(o)
        d = Vector((0, 0, 0.08)) - o.location
        o.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        return o
    area("key", (-0.35, -0.55, 0.9), 220, 0.35)
    area("rim", (0.6, 0.55, 0.45), 70, 0.5, "#ffd9bf")
    area("fill", (0.7, -0.6, 0.15), 18, 1.2)

    # camera
    cd = bpy.data.cameras.new("cam")
    cd.sensor_fit = "VERTICAL"
    cd.angle_y = math.radians(26)
    cd.clip_start, cd.clip_end = 0.05, 20
    cam = bpy.data.objects.new("cam", cd)
    sc.collection.objects.link(cam)
    sc.camera = cam

    # centre of the printed parts (same as three.js: parts bbox centre), +30 mm up
    pts = np.concatenate([npz[n].reshape(-1, 3) for n, k in meta["kinds"].items() if k == "parts"])
    ctr = (pts.min(0) + pts.max(0)) / 2 * MM + np.array([0, 0, 0.030])

    slide = Vector(meta["slide"]).normalized()
    f_on = math.ceil((T["ctx"] - 200) * FPS / 1000)
    f_off = math.floor((T["final"] + 300) * FPS / 1000)
    if a.frames:
        f_on, f_off = (int(x) for x in a.frames.split("-"))
    sc.frame_start, sc.frame_end = f_on, f_off
    pipe_name = next(n for n, k in meta["kinds"].items() if k == "context" and n != meta["screen_of"])

    for f in range(f_on, f_off + 1):
        t = f * 1000 / FPS
        sc.frame_set(f)
        k = span(t, T["ctx"], T["ar"] + 2000)
        az = math.radians(-42 + 70 * ease(k))
        el = math.radians(16 + 6 * math.sin(k * math.pi))
        dist = (1080 - 160 * ease(span(t, T["ctx"], T["steps"] + 2 * T["step"])) + 60 * ease(span(t, T["ar"], T["ar"] + 1500))) * MM
        # three.js (x, y, z) = model (X, Z, -Y)
        cam.location = Vector(ctr) + Vector((dist * math.cos(el) * math.sin(az), -dist * math.cos(el) * math.cos(az), dist * math.sin(el)))
        cam.rotation_euler = (Vector(ctr) - cam.location).to_track_quat("-Z", "Y").to_euler()
        cam.keyframe_insert("location", frame=f)
        cam.keyframe_insert("rotation_euler", frame=f)

        p = out(span(t, T["ctx"], T["ctx"] + 1100))
        po = objs[pipe_name][0]
        po.scale = (max(p, 0.001), 1, 1)
        po.hide_render = p <= 0.001
        po.keyframe_insert("scale", frame=f)
        po.keyframe_insert("hide_render", frame=f)

        ghost = span(t, T["ctx"] + 600, T["ctx"] + 1400)
        drop = ease(span(t, T["fit"], T["fit"] + 1300))
        ph, phb = objs[meta["screen_of"]]
        ph.location = slide * (80 * (1 - drop) * MM)
        alpha = 0.18 * ghost + 0.82 * span(t, T["fit"], T["fit"] + 500)
        phb.inputs["Alpha"].default_value = alpha
        phb.inputs["Alpha"].keyframe_insert("default_value", frame=f)
        ph.hide_render = alpha <= 0.001
        ph.keyframe_insert("location", frame=f)
        ph.keyframe_insert("hide_render", frame=f)
        if scr:
            glow = span(t, T["fit"] + 1300, T["fit"] + 1900)
            scr.location = ph.location
            scr.hide_render = glow <= 0.001
            scr_mix.inputs[0].default_value = glow
            scr_mix.inputs[0].keyframe_insert("default_value", frame=f)
            scr.keyframe_insert("location", frame=f)
            scr.keyframe_insert("hide_render", frame=f)

        for i, s in enumerate(steps):
            ob, b = objs[s["part"]]
            s0 = T["steps"] + i * T["step"]
            pp = span(t, s0, s0 + 1000)
            d = -1 if s.get("from") == "below" else 1
            ob.location = (0, 0, d * 160 * (1 - out(pp)) * MM)
            ob.hide_render = pp <= 0.001
            hot = (1 - span(t, s0 + T["step"] - 500, s0 + T["step"])) if t >= s0 else 0
            b.inputs["Base Color"].default_value = (*(WHITE + (ORANGE - WHITE) * hot), 1)
            b.inputs["Base Color"].keyframe_insert("default_value", frame=f)
            ob.keyframe_insert("location", frame=f)
            ob.keyframe_insert("hide_render", frame=f)

    # constant interpolation: every frame is keyed with its exact value
    for ad in [o.animation_data for o in bpy.data.objects] + [m.node_tree.animation_data for m in bpy.data.materials if m.node_tree]:
        if ad and ad.action:
            fcs = ad.action.fcurves if hasattr(ad.action, "fcurves") else [fc for l in ad.action.layers for s in l.strips for cb in s.channelbags for fc in cb.fcurves]
            for fc in fcs:
                for kp in fc.keyframe_points:
                    kp.interpolation = "CONSTANT"

    outdir = Path(a.outdir).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    for f in range(f_on, f_off + 1, a.step):
        dst = outdir / f"{f:04d}.png"
        if dst.exists():
            continue
        sc.frame_set(f)
        sc.render.filepath = str(dst)
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f"frame {f}/{f_off}  {time.time() - t0:.1f} s", flush=True)
    (outdir / "frames.json").write_text(json.dumps({"fps": FPS, "first": f_on, "last": f_off, "step": a.step}), encoding="utf-8")


main()
