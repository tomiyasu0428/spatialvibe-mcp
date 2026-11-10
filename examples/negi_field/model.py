"""Long-onion (naganegi) field in late autumn — a scene model, not a printable part.

Axes: X = left/right (+X right), Y = away from the viewer, Z = up. Units: mm, real scale.
Origin = bottom of the furrow the photographer stood in, at the near end of the rows.
Everything is a guess read from two photos: row pitch, ridge height, tree heights and distances
are typical values, not measurements. The hills and mountains are a flat backdrop pulled close.

`parts` / `context` hold the unique solids; `placements` says where each one is repeated.
Run directly to export (the MCP build pipeline is for printable parts and is not used here):

  .venv/bin/python examples/negi_field/model.py [out_dir]

writes scene.json (meshes + placements for viewer.html), field.html (self-contained viewer)
and field.usdz (a 1:200 tabletop diorama for AR Quick Look).
"""
import json
import math
import random
import sys
from pathlib import Path

from build123d import Align, Box, Compound, Cone, Plane, Polygon, Pos, Rectangle, RegularPolygon, Rot, Sphere, extrude, loft

P = dict(
    rows=24,              # ridges modelled (the real field is wider)
    pitch=1100.0,         # ridge centre to ridge centre (guess: typical for earthed-up negi)
    ridge_h=350.0,        # furrow bottom to ridge top (guess from the photo)
    ridge_top=280.0,      # flat width on top of a ridge
    furrow_bottom=160.0,
    rows_left=3,          # ridges to the left of the furrow the photographer stood in
    field_len=45000.0,    # near end to the far headland (guess)
    plant_step=200.0,     # one modelled clump stands for several plants
    leaf_len=650.0,       # leaf length above the ridge
    headland=2500.0,      # bare soil at both ends
    diorama_scale=200,    # USDZ: 1:200
    diorama_thin=4,       # USDZ keeps one clump in this many (file size for a phone)
)
C, MIN = Align.CENTER, Align.MIN
rng = random.Random(16)

# name -> RGB. Each placement picks one, so the same solid can be several colours.
palette = {
    "soil": (0.20, 0.15, 0.11),
    "meadow": (0.52, 0.47, 0.27),
    "leaf_deep": (0.16, 0.38, 0.20),
    "leaf_mid": (0.27, 0.50, 0.22),
    "leaf_light": (0.50, 0.62, 0.26),
    "leaf_yellow": (0.74, 0.68, 0.30),
    "straw": (0.83, 0.72, 0.47),
    "straw_dark": (0.66, 0.56, 0.33),
    "bark": (0.27, 0.22, 0.19),
    "birch": (0.72, 0.69, 0.63),
    "larch": (0.78, 0.50, 0.16),
    "larch_dark": (0.62, 0.38, 0.12),
    "conifer": (0.12, 0.22, 0.16),
    "shrub_red": (0.72, 0.28, 0.14),
    "shrub_orange": (0.82, 0.48, 0.18),
    "hill": (0.36, 0.33, 0.33),
    "mountain": (0.42, 0.50, 0.62),
    "snow": (0.93, 0.95, 0.97),
}

# ---- ground --------------------------------------------------------------------------------
x_first = -(P["rows_left"] - 0.5) * P["pitch"]                 # centre of the leftmost ridge
row_x = [x_first + i * P["pitch"] for i in range(P["rows"])]
field_x0 = row_x[0] - P["pitch"] / 2
field_x1 = row_x[-1] + P["pitch"] / 2
z0 = 20.0                                                      # furrow bottom above the meadow
pts = [(field_x0, -300.0), (field_x0, z0)]
for x in row_x:
    a, b = P["pitch"] / 2 - P["furrow_bottom"] / 2, P["ridge_top"] / 2
    pts += [(x - a, z0), (x - b, z0 + P["ridge_h"]), (x + b, z0 + P["ridge_h"]), (x + a, z0)]
pts += [(field_x1, z0), (field_x1, -300.0)]
ridges = extrude(Plane.XZ * Polygon(*pts, align=None), amount=-P["field_len"])
ridges = Pos(0, P["field_len"], 0) * ridges                   # extrude went toward -Y

soil_w = field_x1 - field_x0 + 2000
headlands = Pos((field_x0 + field_x1) / 2, P["field_len"] / 2, -300) * Box(
    soil_w, P["field_len"] + 2 * P["headland"], 300 + z0, align=(C, C, MIN))
meadow = Pos(-3000, 30000, -400) * Box(100000, 112000, 400, align=(C, C, MIN))


# ---- plants --------------------------------------------------------------------------------
def blade(length, lean, azimuth):
    """One leaf: a thin strip that tapers and bends outward."""
    s = length / 650.0
    sections = [(0, 0, 0, 44, 9), (70, 400, 20, 34, 7), (260, 640, 58, 3, 2)]
    faces = [Pos(x * s, 0, z * s) * Rot(0, tilt, 0) * Rectangle(w, t) for x, z, tilt, w, t in sections]
    return Rot(0, 0, azimuth) * Rot(0, lean, 0) * loft(faces, ruled=True)


def clump(n, length, spread):
    """A fan of leaves, as negi grows: two ranks, opening left and right of the plant."""
    out = []
    for k in range(n):
        side = 0 if k % 2 == 0 else 180
        out.append(blade(length * rng.uniform(0.7, 1.08), rng.uniform(-14, 12),
                         side + rng.uniform(-spread, spread)))
    return Compound(children=out)


def cone_at(base, r0, r1, length, tilt, azimuth):
    # a five-sided tapered stick: OCC tessellates a true cone into hundreds of triangles
    stick = loft([RegularPolygon(r0, 5), Pos(0, 0, length) * RegularPolygon(r1, 5)], ruled=True)
    return Pos(*base) * Rot(0, 0, azimuth) * Rot(0, tilt, 0) * stick


def tip(base, length, tilt, azimuth):
    t, a = math.radians(tilt), math.radians(azimuth)
    return (base[0] + length * math.sin(t) * math.cos(a), base[1] + length * math.sin(t) * math.sin(a),
            base[2] + length * math.cos(t))


def bare_tree(height, r):
    """Leafless broadleaf: trunk, a few big limbs, then twigs."""
    limbs = [cone_at((0, 0, 0), r, r * 0.35, height, 0, 0)]

    def grow(base, length, radius, tilt, az, depth):
        limbs.append(cone_at(base, radius, radius * 0.4, length, tilt, az))
        if depth == 0:
            return
        for f in (0.55, 0.8, 1.0):
            p = tip(base, length * f, tilt, az)
            grow(p, length * rng.uniform(0.45, 0.6), radius * 0.5, tilt + rng.uniform(-15, 30),
                 az + rng.uniform(-70, 70), depth - 1)

    for k in range(6):
        zb = height * rng.uniform(0.35, 0.9)
        grow((0, 0, zb), height * rng.uniform(0.28, 0.4), r * 0.45, rng.uniform(25, 50),
             k * 60 + rng.uniform(-25, 25), 2)
    return Compound(children=limbs)


def stacked_cones(height, radius, tiers, start):
    out = []
    for k in range(tiers):
        f = k / tiers
        zb = height * (start + (1 - start) * f)
        out.append(Pos(0, 0, zb) * Cone(radius * (1 - 0.75 * f), 30, height * (1 - start) / tiers * 1.5,
                                        align=(C, C, MIN)))
    return Compound(children=out)


def blob(r):
    return Compound(children=[Pos(dx * r, dy * r, r * (0.7 + dz)) * Sphere(r * s)
                              for dx, dy, dz, s in [(0, 0, 0, 1), (0.6, 0.2, -0.2, 0.7), (-0.5, 0.4, -0.1, 0.75),
                                                    (0.1, -0.6, -0.25, 0.65)]])


def silhouette(profile, depth):
    """A flat cut-out standing on the ground (backdrop): profile = [(x, height), ...]."""
    poly = [(profile[0][0], 0)] + profile + [(profile[-1][0], 0)]
    return extrude(Plane.XZ * Polygon(*poly, align=None), amount=-depth)


parts = {}                                    # nothing here is meant to be printed as is
context = {
    "ridges": ridges, "headlands": headlands, "meadow": meadow,
    "negi_a": clump(8, P["leaf_len"], 40), "negi_b": clump(9, P["leaf_len"] * 0.95, 50),
    "negi_c": clump(7, P["leaf_len"] * 1.05, 32),
    "reed": clump(7, 1700, 80),               # tall dry grass behind the field
    "tree_a": bare_tree(11000, 190), "tree_b": bare_tree(9000, 150), "tree_c": bare_tree(13000, 220),
    "trunk": cone_at((0, 0, 0), 170, 60, 15000, 0, 0),
    "larch_crown": stacked_cones(16000, 1500, 8, 0.3),
    "conifer_crown": stacked_cones(15000, 2600, 7, 0.12),
    "shrub": blob(1000),
    "hills": silhouette([(-45000, 2500), (-36000, 7000), (-25000, 5500), (-14000, 8500), (-3000, 6000),
                         (8000, 7500), (20000, 5000), (32000, 6500), (45000, 3000)], 600),
    "mountains": silhouette([(-50000, 6000), (-40000, 15000), (-33000, 13000), (-24000, 21000),
                             (-19000, 19500), (-14000, 24000), (-6000, 15000), (2000, 12500),
                             (12000, 9000), (24000, 10500), (38000, 7000)], 600),
    "snowcap": silhouette([(-26500, 19000), (-24000, 21100), (-21500, 20000), (-19000, 19600),
                           (-16800, 21500), (-14000, 24100), (-11300, 21000), (-13500, 21800),
                           (-16000, 20300), (-19000, 18300), (-23000, 19500)], 700),
}

# ---- placements: (shape name, colour name, x, y, z, turn about Z in degrees, scale) ---------
placements = [("ridges", "soil", 0, 0, 0, 0, 1), ("headlands", "soil", 0, 0, 0, 0, 1),
              ("meadow", "meadow", 0, 0, 0, 0, 1),
              ("hills", "hill", 0, 74000, 0, 0, 1), ("mountains", "mountain", 0, 84000, 0, 0, 1),
              ("snowcap", "snow", 0, 83900, 0, 0, 1)]


def put(name, colour, x, y, z=0.0, turn=0.0, scale=1.0):
    placements.append((name, colour, round(x), round(y), round(z), round(turn, 1), round(scale, 3)))


top = z0 + P["ridge_h"] - 30
leaf_colours = ["leaf_deep"] * 5 + ["leaf_mid"] * 6 + ["leaf_light"] * 3 + ["leaf_yellow"]
for x in row_x:
    y = rng.uniform(100, 300)
    while y < P["field_len"] - 100:
        # the fan opens across the row, with some scatter
        put(rng.choice(["negi_a", "negi_b", "negi_c"]), rng.choice(leaf_colours), x + rng.uniform(-45, 45), y,
            top, rng.choice([0, 180]) + rng.uniform(-40, 40), rng.uniform(0.82, 1.12))
        y += P["plant_step"] * rng.uniform(0.8, 1.2)

# dry reed band behind the right half of the field
for _ in range(900):
    put("reed", rng.choice(["straw", "straw", "straw_dark"]), rng.uniform(6000, 36000),
        rng.uniform(P["field_len"] + 3200, P["field_len"] + 7500), 0, rng.uniform(0, 360), rng.uniform(0.7, 1.15))
# rough grass and shrubs on the bank to the left
bank_x = field_x0 - 1300
for _ in range(700):
    put("reed", rng.choice(["straw_dark", "meadow", "straw"]), bank_x - abs(rng.gauss(0, 3500)),
        rng.uniform(-2000, P["field_len"] + 6000), 0, rng.uniform(0, 360), rng.uniform(0.3, 0.6))
for _ in range(16):
    put("shrub", rng.choice(["shrub_red", "shrub_red", "shrub_orange", "straw_dark"]),
        bank_x - rng.uniform(3500, 11000), rng.uniform(2000, 44000), 0, rng.uniform(0, 360), rng.uniform(0.5, 1.2))
for _ in range(11):
    put(rng.choice(["tree_a", "tree_b"]), rng.choice(["birch", "bark"]), bank_x - rng.uniform(4000, 12000),
        rng.uniform(0, 46000), 0, rng.uniform(0, 360), rng.uniform(0.8, 1.15))

# tree line behind the field: bare broadleaves left and centre, larches then dark conifers right
back = P["field_len"] + 8000
for _ in range(34):
    put(rng.choice(["tree_a", "tree_b", "tree_c"]), rng.choice(["bark", "bark", "birch"]),
        rng.uniform(-16000, 15000), back + rng.uniform(0, 9000), 0, rng.uniform(0, 360), rng.uniform(0.85, 1.25))
for _ in range(20):
    x, y, s = rng.uniform(15000, 27000), back + rng.uniform(1000, 9000), rng.uniform(0.85, 1.2)
    put("trunk", "bark", x, y, 0, 0, s)
    put("larch_crown", rng.choice(["larch", "larch", "larch_dark"]), x, y, 0, rng.uniform(0, 360), s)
for _ in range(16):
    x, y, s = rng.uniform(26000, 40000), back + rng.uniform(1500, 10000), rng.uniform(0.8, 1.15)
    put("trunk", "bark", x, y, 0, 0, s * 0.8)
    put("conifer_crown", "conifer", x, y, 0, rng.uniform(0, 360), s)

origin = "写真②で立っていた溝の底・うねの手前の端"
user_view = "畑の手前の端に立って、うねに沿って奥を見たとき"


# ---- export --------------------------------------------------------------------------------
def tessellate(shape, tol):
    verts, tris = shape.tessellate(tol, 0.6)
    return [(v.X, v.Y, v.Z) for v in verts], [tuple(t) for t in tris]


def export(out: Path):
    out.mkdir(parents=True, exist_ok=True)
    fine = {"ridges", "headlands", "meadow", "hills", "mountains", "snowcap"}
    meshes = {n: tessellate(s, 1.0 if n in fine else (4.0 if n.startswith(("negi", "reed")) else 60.0))
              for n, s in context.items()}
    scene = {
        "units": "mm, Z up", "origin": origin, "palette": palette,
        "meshes": {n: {"v": [round(c) for p in v for c in p], "i": [k for t in f for k in t]}
                   for n, (v, f) in meshes.items()},
        "groups": {},     # shape name -> flat [colour index, x, y, z, turn, scale] * n
    }
    names = list(palette)
    for name, colour, *xf in placements:
        scene["groups"].setdefault(name, []).extend([names.index(colour)] + xf)
    text = json.dumps(scene, ensure_ascii=False, separators=(",", ":"))
    (out / "scene.json").write_text(text, encoding="utf-8")
    template = (Path(__file__).parent / "viewer.html").read_text(encoding="utf-8")
    (out / "field.html").write_text(template.replace("/*SCENE*/null", text), encoding="utf-8")
    tri_total = sum(len(meshes[n][1]) for n, *_ in placements)
    usdz = write_usdz(out, meshes)
    return {"placements": len(placements), "triangles": tri_total, "usdz": str(usdz),
            "html_kb": round((out / "field.html").stat().st_size / 1024)}


def write_usdz(out: Path, meshes):
    """One mesh per colour, mm Z-up -> m Y-up, shrunk to a tabletop diorama."""
    import numpy as np
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils, Vt

    by_colour = {}
    for k, (name, colour, x, y, z, turn, scale) in enumerate(placements):
        if name.startswith(("negi", "reed")) and k % P["diorama_thin"]:
            continue                                   # a tabletop model needs far fewer leaves
        v = np.asarray(meshes[name][0], dtype=np.float64) * scale
        c, s = math.cos(math.radians(turn)), math.sin(math.radians(turn))
        v = np.column_stack([v[:, 0] * c - v[:, 1] * s + x, v[:, 0] * s + v[:, 1] * c + y, v[:, 2] + z])
        vs, fs, n = by_colour.setdefault(colour, [[], [], 0])
        vs.append(v)
        fs.append(np.asarray(meshes[name][1], dtype=np.int64) + n)
        by_colour[colour][2] = n + len(v)

    usdc = out / "field.usdc"
    stage = Usd.Stage.CreateNew(str(usdc))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/Root")
    stage.SetDefaultPrim(root.GetPrim())
    k = 0.001 / P["diorama_scale"]
    root.AddRotateXOp().Set(-90.0)
    root.AddScaleOp().Set(Gf.Vec3f(k, k, k))
    # centre the diorama on the field and stand it on the table
    root.AddTranslateOp().Set(Gf.Vec3d(-(field_x0 + field_x1) / 2, -P["field_len"] / 2, 400.0))
    for colour, (vs, fs, _) in by_colour.items():
        v, f = np.vstack(vs).astype(np.float32), np.vstack(fs).astype(np.int32)
        mesh = UsdGeom.Mesh.Define(stage, f"/Root/{colour}")
        mesh.CreatePointsAttr(Vt.Vec3fArray.FromNumpy(v))
        mesh.CreateFaceVertexCountsAttr(Vt.IntArray.FromNumpy(np.full(len(f), 3, dtype=np.int32)))
        mesh.CreateFaceVertexIndicesAttr(Vt.IntArray.FromNumpy(f.flatten()))
        mesh.CreateSubdivisionSchemeAttr("none")
        mat = UsdShade.Material.Define(stage, f"/Root/{colour}_mat")
        sh = UsdShade.Shader.Define(stage, f"/Root/{colour}_mat/pbr")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*palette[colour]))
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.85)
        mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)
    stage.GetRootLayer().Save()
    usdz = out / "field.usdz"
    if not UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(str(usdc)), str(usdz)):
        raise RuntimeError("USDZ packaging failed")
    usdc.unlink()
    return usdz


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out"
    print(json.dumps(export(target), ensure_ascii=False, indent=1))
