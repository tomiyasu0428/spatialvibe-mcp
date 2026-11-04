"""Pack a version's STL meshes (mm, Z-up) into a real-scale USDZ (m, Y-up) for AR Quick Look."""
from pathlib import Path

import trimesh
from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

from ._style import CONTEXT_COLOR, part_color


def build_usdz(vdir: Path, include_context: bool = True) -> Path:
    items = [(f, part_color(i), 1.0) for i, f in enumerate(sorted(vdir.glob("part_*.stl")))]
    if include_context:
        items += [(f, CONTEXT_COLOR, 0.35) for f in sorted(vdir.glob("ctx_*.stl"))]

    usdc = vdir / "model.usdc"
    stage = Usd.Stage.CreateNew(str(usdc))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/Root")
    stage.SetDefaultPrim(root.GetPrim())
    root.AddRotateXOp().Set(-90.0)                       # Z-up -> Y-up
    root.AddScaleOp().Set(Gf.Vec3f(0.001, 0.001, 0.001))  # mm -> m

    for f, rgb, alpha in items:
        name = "m_" + "".join(ch if ch.isalnum() else "_" for ch in f.stem)
        m = trimesh.load(f)
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
