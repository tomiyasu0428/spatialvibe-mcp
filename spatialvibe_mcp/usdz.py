"""Pack a version's STL meshes (mm, Z-up) into a real-scale USDZ (m, Y-up) for AR Quick Look."""
from pathlib import Path

import trimesh
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

from ._style import CONTEXT_COLOR, part_color


FLOOR_COLOR = (0.95, 0.75, 0.2)


def _floor_meshes(meshes, floor_z):
    """A yellow plate on the floor IN FRONT of the scene (the user's side, -Y), and a thin post from
    it up to the origin height with an arm back to the origin. AR Quick Look can only rest a model on
    a floor or table: the user puts the plate on free floor in front of the real thing, so it never
    has to overlap a wheel, a chair or a boat side, and the model appears at its real height."""
    lo = [min(m.bounds[0][i] for m in meshes) for i in range(3)]
    hi = [max(m.bounds[1][i] for m in meshes) for i in range(3)]
    w = max(hi[0] - lo[0], 160.0)
    d = 120.0
    y_edge = lo[1] - 20.0                      # plate's far edge: just in front of the whole scene
    plate = trimesh.creation.box((w, d, 1.0))
    plate.apply_translation(((lo[0] + hi[0]) / 2, y_edge - d / 2, floor_z - 0.5))
    out = [plate]
    h = -floor_z
    if h > 5.0:                               # post up to the origin height, then an arm back to it
        post = trimesh.creation.box((4.0, 4.0, h))
        post.apply_translation((0.0, y_edge, floor_z + h / 2))
        arm = trimesh.creation.box((4.0, -y_edge, 4.0))
        arm.apply_translation((0.0, y_edge / 2, 0.0))
        out += [post, arm]
    return out


def build_usdz(vdir: Path, include_context: bool = True, floor_z: float | None = None) -> Path:
    items = [(f, part_color(i), 1.0) for i, f in enumerate(sorted(vdir.glob("part_*.stl")))]
    if include_context:
        items += [(f, CONTEXT_COLOR, 0.35) for f in sorted(vdir.glob("ctx_*.stl"))]
    items = [(trimesh.load(f), f.stem, rgb, a) for f, rgb, a in items]
    if floor_z is not None:
        # a context that only models the floor itself (a slab below it) is replaced by the plate
        items = [it for it in items if not (it[1].startswith("ctx_") and it[0].bounds[1][2] <= floor_z + 0.5)]
        low = min(m.bounds[0][2] for m, *_ in items)
        if floor_z > low + 0.01:   # the model would sink into the floor
            raise ValueError(f"ar_floor {floor_z} mm is above the lowest point of the model ({low:.1f} mm); "
                             "make the floor context reach down to it or lower ar_floor")
        extra = _floor_meshes([m for m, *_ in items], floor_z)
        items += [(extra[0], "ar_floor", FLOOR_COLOR, 0.30)]
        items += [(m, f"ar_floor_post{k}", FLOOR_COLOR, 0.6) for k, m in enumerate(extra[1:])]

    parts_only = [m for m, stem, *_ in items if stem.startswith("part_")]
    if parts_only:   # small parts are hard to find in AR: a yellow arrow points down at them
        import numpy as np
        plo = np.min([m.bounds[0] for m in parts_only], axis=0)
        phi = np.max([m.bounds[1] for m in parts_only], axis=0)
        if max(phi - plo) < 80.0:
            arrow = trimesh.creation.cone(radius=12.0, height=35.0)
            arrow.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))  # tip down
            c = (plo + phi) / 2
            arrow.apply_translation((c[0], c[1], phi[2] + 15.0 + 35.0))
            items.append((arrow, "ar_pointer", FLOOR_COLOR, 0.9))

    usdc = vdir / "model.usdc"
    stage = Usd.Stage.CreateNew(str(usdc))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/Root")
    stage.SetDefaultPrim(root.GetPrim())
    root.AddRotateXOp().Set(-90.0)                       # Z-up -> Y-up
    root.AddScaleOp().Set(Gf.Vec3f(0.001, 0.001, 0.001))  # mm -> m

    for m, stem, rgb, alpha in items:
        name = "m_" + "".join(ch if ch.isalnum() else "_" for ch in stem)
        mesh = UsdGeom.Mesh.Define(stage, f"/Root/{name}")
        mesh.CreatePointsAttr([Gf.Vec3f(*map(float, v)) for v in m.vertices])
        mesh.CreateFaceVertexCountsAttr([3] * len(m.faces))
        mesh.CreateFaceVertexIndicesAttr([int(i) for i in m.faces.flatten()])
        mesh.CreateSubdivisionSchemeAttr("none")
        mat = UsdShade.Material.Define(stage, f"/Root/{name}_mat")
        sh = UsdShade.Shader.Define(stage, f"/Root/{name}_mat/pbr")
        sh.CreateIdAttr("UsdPreviewSurface")
        sh.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*rgb))
        sh.CreateInput("opacity", Sdf.ValueTypeNames.Float).Set(alpha)
        sh.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.6)
        mat.CreateSurfaceOutput().ConnectToSource(sh.ConnectableAPI(), "surface")
        UsdShade.MaterialBindingAPI.Apply(mesh.GetPrim()).Bind(mat)
    stage.GetRootLayer().Save()

    usdz = vdir / "model.usdz"
    if not UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(str(usdc)), str(usdz)):
        raise RuntimeError("USDZ packaging failed")
    return usdz


def usdz_size_m(usdz: Path):
    """Size of the real things in the USDZ (parts and context), without the AR helpers (floor plate,
    post, pointer arrow)."""
    stage = Usd.Stage.Open(str(usdz))
    cache = UsdGeom.BBoxCache(0, ["default"])
    rng = Gf.Range3d()
    for prim in stage.Traverse():
        if prim.IsA(UsdGeom.Mesh) and not prim.GetName().startswith("m_ar_"):
            rng.UnionWith(cache.ComputeWorldBound(prim).ComputeAlignedRange())
    s = rng.GetSize()
    return [round(s[0], 4), round(s[1], 4), round(s[2], 4)]


if __name__ == "__main__":
    import json
    import sys

    work = Path(sys.argv[1])
    try:
        package = build_usdz(work, bool(int(sys.argv[2])), json.loads(sys.argv[3]))
    except ValueError as exc:
        raise SystemExit(str(exc))
    (work / "size.json").write_text(json.dumps(usdz_size_m(package)))
