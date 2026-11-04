"""4-view PNG of a version's parts (opaque) and context (translucent).

Usage: python -m spatialvibe_mcp._render <version_dir>
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

from spatialvibe_mcp._style import CONTEXT_COLOR, jp_font, part_color  # noqa: E402

FONT = jp_font()


def _clip(mesh, lo, hi):
    """Cut a mesh to the box lo..hi (keeps the part of a long pipe that is near the parts)."""
    try:
        for axis in range(3):
            for sign, val in ((1, lo[axis]), (-1, hi[axis])):
                normal = np.zeros(3)
                normal[axis] = sign
                origin = np.zeros(3)
                origin[axis] = val
                mesh = trimesh.intersections.slice_mesh_plane(mesh, normal, origin, cap=True)
                if mesh is None or not len(mesh.faces):
                    return None
        return mesh
    except Exception:
        return mesh


def main():
    vdir = Path(sys.argv[1])
    meshes = []
    for i, f in enumerate(sorted(vdir.glob("part_*.stl"))):
        meshes.append((trimesh.load(f), (*part_color(i), 1.0), f.stem[5:]))
    for f in sorted(vdir.glob("ctx_*.stl")):
        meshes.append((trimesh.load(f), (*CONTEXT_COLOR, 0.22), f.stem[4:] + ("（周囲）" if FONT else " (context)")))
    # frame the printed parts; long context (a 2 m pipe...) is cut to the frame instead of shrinking the parts
    n_parts = sum(1 for _, c, _ in meshes if c[3] == 1.0)
    plo = np.min([m.bounds[0] for m, _, _ in meshes[:n_parts]], axis=0)
    phi = np.max([m.bounds[1] for m, _, _ in meshes[:n_parts]], axis=0)
    half = max((phi - plo).max() / 2 * 1.25, 20.0)
    mid = (plo + phi) / 2
    lo, hi = mid - half, mid + half
    meshes = meshes[:n_parts] + [(_clip(m, lo, hi), c, n) for m, c, n in meshes[n_parts:]]
    meshes = [x for x in meshes if x[0] is not None and len(x[0].faces)]

    views = [("斜め前から", 25, -60), ("斜め後ろから", 20, 120), ("真横（右）から", 0, 0), ("下から", -60, -60)]
    if FONT is None:
        views = [(en, e, a) for en, (_, e, a) in zip(("front-oblique", "rear-oblique", "right side", "below"), views)]
    fig = plt.figure(figsize=(13, 10.5))
    for i, (title, elev, azim) in enumerate(views, 1):
        ax = fig.add_subplot(2, 2, i, projection="3d")
        for m, c, _ in meshes:
            ax.add_collection3d(Poly3DCollection(
                m.triangles, facecolor=c, edgecolor=(0, 0, 0, 0.08 if c[3] > 0.5 else 0), linewidth=0.2))
        ax.set_xlim(lo[0], hi[0]); ax.set_ylim(lo[1], hi[1]); ax.set_zlim(lo[2], hi[2])
        ax.set_box_aspect((1, 1, 1))
        ax.view_init(elev=elev, azim=azim)
        ax.set_title(title, fontname=FONT) if FONT else ax.set_title(title)
        ax.set_xlabel("X"); ax.set_ylabel("Y"); ax.set_zlabel("Z")
    fig.legend(handles=[plt.Rectangle((0, 0), 1, 1, color=c) for _, c, _ in meshes],
               labels=[n for _, _, n in meshes], loc="lower center", ncol=len(meshes), prop={"family": FONT} if FONT else None)
    plt.tight_layout(rect=(0, 0.04, 1, 1))
    plt.savefig(vdir / "preview.png", dpi=80)


if __name__ == "__main__":
    main()
