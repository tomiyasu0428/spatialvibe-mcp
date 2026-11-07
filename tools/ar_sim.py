"""Simulate how AR Quick Look shows a published USDZ, without an iPhone.

Usage: python tools/ar_sim.py <model.usdz> <out.png> [--eye 1.5] [--back 1.0]

AR Quick Look rests a model on the detected floor/table with the bottom of its bounding box
(assumption used here; confirm on a real iPhone). This script reports where the script's origin
(the mounting point) ends up above that surface, whether a floor plate (ar_floor) is present,
the real size of every piece, and renders a perspective view from a standing person on the user
side (script -Y), with a 10 cm floor grid, so a reviewer can judge what the user will see.
Prints a JSON summary.
"""
import json
import sys
from pathlib import Path

import numpy as np
from pxr import Usd, UsdGeom


def load(usdz):
    stage = Usd.Stage.Open(str(usdz))
    mpu = UsdGeom.GetStageMetersPerUnit(stage)
    cache = UsdGeom.XformCache()
    meshes = []
    for prim in stage.Traverse():
        if not prim.IsA(UsdGeom.Mesh):
            continue
        m = UsdGeom.Mesh(prim)
        pts = np.array(m.GetPointsAttr().Get(), dtype=float)
        M = np.array(cache.GetLocalToWorldTransform(prim), dtype=float)
        pts = (np.c_[pts, np.ones(len(pts))] @ M)[:, :3] * mpu
        idx = np.array(m.GetFaceVertexIndicesAttr().Get(), dtype=int).reshape(-1, 3)
        meshes.append((prim.GetName(), pts, idx))
    origin = np.array([0, 0, 0, 1.0]) @ np.array(cache.GetLocalToWorldTransform(stage.GetDefaultPrim()))
    return meshes, origin[:3] * mpu, mpu, UsdGeom.GetStageUpAxis(stage)


def main():
    usdz, out = Path(sys.argv[1]), Path(sys.argv[2])
    eye = float(sys.argv[sys.argv.index("--eye") + 1]) if "--eye" in sys.argv else 1.5
    back = float(sys.argv[sys.argv.index("--back") + 1]) if "--back" in sys.argv else 1.0
    meshes, origin, mpu, up = load(usdz)
    allp = np.vstack([p for _, p, _ in meshes])
    lo, hi = allp.min(0), allp.max(0)
    floor_y = lo[1]                                   # Quick Look rests the bbox bottom on the surface
    has_floor = any(n.startswith("m_ar_floor") for n, _, _ in meshes)
    pieces = {}
    for n, p, _ in meshes:
        s = p.max(0) - p.min(0)
        # USD Y-up -> script axes: x = width, y(script) = -Z(usd) depth, z = height
        pieces[n] = {"size_cm": [round(s[0] * 100, 1), round(s[2] * 100, 1), round(s[1] * 100, 1)],
                     "lowest_above_floor_cm": round((p[:, 1].min() - floor_y) * 100, 1)}
    summary = {
        "meters_per_unit": mpu, "up_axis": up,
        "scene_size_cm": [round(v * 100, 1) for v in (hi[0] - lo[0], hi[2] - lo[2], hi[1] - lo[1])],
        "has_floor_plate": has_floor,
        "origin_above_resting_surface_cm": round((origin[1] - floor_y) * 100, 1),
        "rests_on": "黄色い床の板 (ar_floor)" if has_floor else "モデルの一番下の点",
        "pieces": pieces,
        "assumption": "Quick Look rests the bounding-box bottom on the detected surface; real iPhone not checked",
    }

    # perspective view from a standing person on the user side (script -Y = USD +Z)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from spatialvibe_mcp._style import jp_font
    f = jp_font()
    if f:
        plt.rcParams["font.family"] = [f, "DejaVu Sans"]
    from matplotlib.collections import LineCollection, PolyCollection
    top = hi[1]
    centre = np.array([(lo[0] + hi[0]) / 2, floor_y + (top - floor_y) / 2, (lo[2] + hi[2]) / 2])
    back = max(back, 1.3 * (top - floor_y), 1.1 * (hi[0] - lo[0]))   # step back until it all fits
    cam = np.array([centre[0], eye, hi[2] + back])
    fwd = centre - cam
    fwd /= np.linalg.norm(fwd)
    right = np.cross(fwd, [0, 1, 0])
    right /= np.linalg.norm(right)
    upv = np.cross(right, fwd)

    def proj(P):
        d = P - cam
        z = d @ fwd
        return np.c_[(d @ right) / z, (d @ upv) / z], z

    fig, ax = plt.subplots(figsize=(6, 7.5), dpi=110)
    g = np.arange(-1.0, 1.01, 0.1)
    lines = []
    for v in g:   # 10 cm grid on the resting surface
        for a, b in (([lo[0] + v, floor_y, lo[2] - 1.0], [lo[0] + v, floor_y, hi[2] + 0.2]),
                     ([lo[0] - 1.0, floor_y, (lo[2] + hi[2]) / 2 + v], [hi[0] + 1.0, floor_y, (lo[2] + hi[2]) / 2 + v])):
            q, z = proj(np.array([a, b]))
            if (z > 0.05).all():
                lines.append(q)
    ax.add_collection(LineCollection(lines, colors="0.8", linewidths=0.6, zorder=0))
    polys, cols, depth = [], [], []
    for n, p, idx in meshes:
        q, z = proj(p)
        if n.startswith("m_ar_floor"):
            c = (0.95, 0.75, 0.2, 0.45)
        elif n.startswith("m_ctx"):
            c = (0.55, 0.58, 0.62, 0.35)
        else:
            c = (0.25, 0.5, 0.95, 0.95)
        tri = q[idx]
        zz = z[idx].mean(1)
        ok = (z[idx] > 0.05).all(1)
        polys += list(tri[ok])
        cols += [c] * int(ok.sum())
        depth += list(zz[ok])
    order = np.argsort(-np.array(depth))
    ax.add_collection(PolyCollection([polys[i] for i in order], facecolors=[cols[i] for i in order],
                                     edgecolors="none"))
    if polys:   # frame on everything that is drawn (with a margin), keeping the aspect
        allq = np.vstack(polys)
        (x0, y0), (x1, y1) = allq.min(0), allq.max(0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        half = max((x1 - x0) / 1.2, (y1 - y0) / 1.5) * 0.6 + 0.02
        ax.set_xlim(cx - half * 1.2 / 1.5 * 1.25, cx + half * 1.2 / 1.5 * 1.25)
        ax.set_ylim(cy - half, cy + half)
    else:
        ax.set_xlim(-0.6, 0.6)
        ax.set_ylim(-0.75, 0.75)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(f"AR 見え方の模擬（目の高さ {eye} m・{back:.1f} m 手前から）\n"
                 f"取付け点は置いた面から {summary['origin_above_resting_surface_cm']} cm 上 / "
                 f"置かれるのは {summary['rests_on']}", fontsize=9)
    fig.savefig(out, bbox_inches="tight")
    summary["image"] = str(out)
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
