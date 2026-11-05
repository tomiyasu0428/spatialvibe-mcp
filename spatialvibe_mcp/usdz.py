"""Pack a version's STL meshes (mm, Z-up) into a real-scale USDZ (m, Y-up) for AR Quick Look."""
from pathlib import Path

import trimesh
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

from ._style import CONTEXT_COLOR, part_color


FLOOR_COLOR = (0.95, 0.75, 0.2)


def _floor_meshes(meshes, floor_z):
    """A thin plate at the floor height under the whole scene and a thin post from it up to the
    origin, so AR Quick Look (which can only rest a model on a floor or table) puts the model at its
    real height: place it on that floor, then slide it until the grey context lines up."""
    lo = [min(m.bounds[0][i] for m in meshes) for i in range(2)]
    hi = [max(m.bounds[1][i] for m in meshes) for i in range(2)]
    pad = 20.0
    w, d = hi[0] - lo[0] + 2 * pad, hi[1] - lo[1] + 2 * pad
    plate = trimesh.creation.box((w, d, 1.0))
    plate.apply_translation(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, floor_z - 0.5))
    top = min(0.0, min(m.bounds[0][2] for m in meshes))
    post = trimesh.creation.box((4.0, 4.0, max(top - floor_z, 1.0)))
    post.apply_translation((0.0, 0.0, (floor_z + max(top, floor_z + 1.0)) / 2))
    return plate, post


def build_usdz(vdir: Path, include_context: bool = True, floor_z: float | None = None) -> Path:
    items = [(f, part_color(i), 1.0) for i, f in enumerate(sorted(vdir.glob("part_*.stl")))]
    if include_context:
        items += [(f, CONTEXT_COLOR, 0.35) for f in sorted(vdir.glob("ctx_*.stl"))]
    items = [(trimesh.load(f), f.stem, rgb, a) for f, rgb, a in items]
    if floor_z is not None:
        low = min(m.bounds[0][2] for m, *_ in items)
        if floor_z > low + 0.01:   # the model would sink into the floor
            raise ValueError(f"ar_floor {floor_z} mm is above the lowest point of the model ({low:.1f} mm); "
                             "make the floor context reach down to it or lower ar_floor")
        plate, post = _floor_meshes([m for m, *_ in items], floor_z)
        items += [(plate, "ar_floor", FLOOR_COLOR, 0.30), (post, "ar_floor_post", FLOOR_COLOR, 0.6)]

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
    stage = Usd.Stage.Open(str(usdz))
    r = UsdGeom.BBoxCache(0, ["default"]).ComputeWorldBound(stage.GetDefaultPrim()).ComputeAlignedRange()
    s = r.GetSize()
    return [round(s[0], 4), round(s[1], 4), round(s[2], 4)]
