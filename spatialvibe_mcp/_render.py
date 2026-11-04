"""4-view PNG of a version's parts (opaque) and context (translucent).

Usage: python -m spatialvibe_mcp._render <version_dir>
"""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import trimesh  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

PART_COLORS = [(0.95, 0.55, 0.15), (0.85, 0.30, 0.10), (0.20, 0.55, 0.85), (0.30, 0.70, 0.35)]
JP_FONTS = ["Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP", "Noto Sans JP", "IPAexGothic", "Yu Gothic"]


def _jp_font():
    """First installed Japanese font, or None (then labels fall back to English)."""
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    return next((f for f in JP_FONTS if f in have), None)


FONT = _jp_font()


def main():
    vdir = Path(sys.argv[1])
    meshes = []
    for i, f in enumerate(sorted(vdir.glob("part_*.stl"))):
        meshes.append((trimesh.load(f), (*PART_COLORS[i % len(PART_COLORS)], 1.0), f.stem[5:]))
    for f in sorted(vdir.glob("ctx_*.stl")):
        meshes.append((trimesh.load(f), (0.55, 0.60, 0.68, 0.22), f.stem[4:] + ("（周囲）" if FONT else " (context)")))
    lo = min(m.bounds[0].min() for m, _, _ in meshes)
    hi = max(m.bounds[1].max() for m, _, _ in meshes)

    views = [("斜め前から", 25, -60), ("斜め後ろから", 20, 120), ("真横（右）から", 0, 0), ("下から", -60, -60)]
    if FONT is None:
        views = [(en, e, a) for en, (_, e, a) in zip(("front-oblique", "rear-oblique", "right side", "below"), views)]
    fig = plt.figure(figsize=(13, 10.5))
    for i, (title, elev, azim) in enumerate(views, 1):
        ax = fig.add_subplot(2, 2, i, projection="3d")
        for m, c, _ in meshes:
            ax.add_collection3d(Poly3DCollection(
                m.triangles, facecolor=c, edgecolor=(0, 0, 0, 0.08 if c[3] > 0.5 else 0), linewidth=0.2))
        ax.set_xlim(lo, hi); ax.set_ylim(lo, hi); ax.set_zlim(lo, hi)
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
