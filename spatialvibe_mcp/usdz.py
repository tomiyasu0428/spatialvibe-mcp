"""Pack a version's STL meshes (mm, Z-up) into a real-scale USDZ (m, Y-up) for AR Quick Look.

Usage: python -m spatialvibe_mcp.usdz <in_dir> <out_dir> <include_context: 0|1>
The server runs this inside the sandbox (the meshes came from generated code) and admits
<out_dir>/model.usdz and reads <out_dir>/size.json afterwards.
"""
import json
import sys
from pathlib import Path

PART_COLORS = [(0.95, 0.55, 0.15), (0.85, 0.30, 0.10), (0.20, 0.55, 0.85), (0.30, 0.70, 0.35)]


def build_usdz(vdir: Path, include_context: bool = True, out_dir: Path | None = None) -> Path:
    import trimesh
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdShade, UsdUtils

    out_dir = out_dir or vdir
    items = [(f, PART_COLORS[i % len(PART_COLORS)], 1.0) for i, f in enumerate(sorted(vdir.glob("part_*.stl")))]
    if include_context:
        items += [(f, (0.55, 0.60, 0.68), 0.35) for f in sorted(vdir.glob("ctx_*.stl"))]

    usdc = out_dir / "model.usdc"
    stage = Usd.Stage.CreateNew(str(usdc))
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.y)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)
    root = UsdGeom.Xform.Define(stage, "/Root")
    stage.SetDefaultPrim(root.GetPrim())
    root.AddRotateXOp().Set(-90.0)                       # Z-up -> Y-up
    root.AddScaleOp().Set(Gf.Vec3f(0.001, 0.001, 0.001))  # mm -> m

    for f, rgb, alpha in items:
        name = "m_" + "".join(ch if ch.isalnum() else "_" for ch in f.stem)
        m = trimesh.load(f, force="mesh")
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

    usdz = out_dir / "model.usdz"
    if not UsdUtils.CreateNewARKitUsdzPackage(Sdf.AssetPath(str(usdc)), str(usdz)):
        raise RuntimeError("USDZ packaging failed")
    return usdz


def usdz_size_m(usdz: Path):
    from pxr import Usd, UsdGeom
    stage = Usd.Stage.Open(str(usdz))
    r = UsdGeom.BBoxCache(0, ["default"]).ComputeWorldBound(stage.GetDefaultPrim()).ComputeAlignedRange()
    s = r.GetSize()
    return [round(s[0], 4), round(s[1], 4), round(s[2], 4)]


def main():
    from spatialvibe_mcp._isolation import apply_child_limits
    apply_child_limits()
    src, out, include_context = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3] == "1"
    usdz = build_usdz(src, include_context, out)
    (out / "size.json").write_text(json.dumps(usdz_size_m(usdz)), encoding="utf-8")


if __name__ == "__main__":
    main()
