"""4-view PNG of a version's parts (opaque) and context (translucent).

Usage: python -m spatialvibe_mcp._render <in_dir> <out.png>
<in_dir> holds the part_*.stl / ctx_*.stl copies the server admitted; the server runs this inside
the sandbox because the meshes came from generated code.
"""
import sys
from pathlib import Path

from spatialvibe_mcp._isolation import apply_child_limits

apply_child_limits()

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

PART_COLORS = [(0.95, 0.55, 0.15), (0.85, 0.30, 0.10), (0.20, 0.55, 0.85), (0.30, 0.70, 0.35)]
FONT = "Hiragino Sans"


def main():
    vdir, png = Path(sys.argv[1]), Path(sys.argv[2])
    meshes = []
    for i, f in enumerate(sorted(vdir.glob("part_*.stl"))):
        meshes.append((trimesh.load(f, force="mesh"), (*PART_COLORS[i % len(PART_COLORS)], 1.0), f.stem[5:]))
    for f in sorted(vdir.glob("ctx_*.stl")):
        meshes.append((trimesh.load(f, force="mesh"), (0.55, 0.60, 0.68, 0.22), f.stem[4:] + "（周囲）"))
    lo = min(m.bounds[0].min() for m, _, _ in meshes)
    hi = max(m.bounds[1].max() for m, _, _ in meshes)

    views = [("斜め前から", 25, -60), ("斜め後ろから", 20, 120), ("真横（右）から", 0, 0), ("下から", -60, -60)]
    fig = plt.figure(figsize=(13, 10.5))
    for i, (title, elev, azim) in enumerate(views, 1):
        ax = fig.add_subplot(2, 2, i, projection="3d")
        for m, c, _ in meshes:
            ax.add_collection3d(Poly3DCollection(
                m.triangles, facecolor=c, edgecolor=(0, 0, 0, 0.08 if c[3] > 0.5 else 0), linewidth=0.2))
        ax.set_xlim(lo, hi); ax.set_ylim(lo, hi); ax.set_zlim(lo, hi)
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(title, fontname=FONT)
        ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z")
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for _, c, _ in meshes],
               labels=[n for _, _, n in meshes], loc="lower center", ncol=len(meshes), prop={"family": FONT})
    plt.tight_layout(rect=(0, 0.04, 1, 1))
    plt.savefig(png, dpi=80)


if __name__ == "__main__":
    main()
