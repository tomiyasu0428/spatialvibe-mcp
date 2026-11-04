"""Dimension sheet: one tall PNG meant to be read on a phone in the field.

Header: part count and overall size of the printed parts. One row per part: colour, size W×D×H,
holes, whether it fits the print bed, and two flat views (top, front) with dimension lines.
Footer: what to buy (`hardware`) and what to check before printing (`checks`) from the script.

Usage: python -m spatialvibe_mcp._sheet <version_dir>
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import trimesh  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402

from spatialvibe_mcp._style import jp_font, part_color  # noqa: E402

FONT = jp_font()
JA = FONT is not None
T = {  # label text, Japanese when a font exists
    "parts": ("部品 {n} 個", "{n} parts"),
    "overall": ("全体 {s} mm（印刷する部品だけ）", "overall {s} mm (printed parts only)"),
    "holes": ("穴", "holes"), "half": ("円弧", "arc"), "none": ("なし", "none"),
    "bed_ok": ("ベッドに入る ✓", "fits bed ✓"), "bed_ng": ("ベッドに入らない ✗", "too big for bed ✗"),
    "top": ("上から", "top"), "front": ("正面から", "front"),
    "buy": ("買うもの", "Hardware"), "check": ("印刷前に確認", "Check before printing"),
    "missing": ("（スクリプトに書かれていません）", "(not given in the script)"),
}


def t(key, **kw):
    return T[key][0 if JA else 1].format(**kw)


def fmt(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


def size_text(size):
    return " × ".join(fmt(v) for v in size)


def _dim(ax, p0, p1, text, offset, horizontal):
    """Dimension line with arrows between p0 and p1, shifted by offset, label in the middle."""
    (x0, y0), (x1, y1) = p0, p1
    if horizontal:
        y0 = y1 = y0 - offset
        ax.plot([x0, x0], [p0[1], y0], color="0.5", lw=0.6)
        ax.plot([x1, x1], [p1[1], y1], color="0.5", lw=0.6)
    else:
        x0 = x1 = x0 - offset
        ax.plot([p0[0], x0], [y0, y0], color="0.5", lw=0.6)
        ax.plot([p1[0], x1], [y1, y1], color="0.5", lw=0.6)
    ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="<->", color="0.15", lw=1.0))
    ax.text((x0 + x1) / 2, (y0 + y1) / 2, text, ha="center", va="center", fontsize=12, fontweight="bold",
            rotation=0 if horizontal else 90, bbox=dict(facecolor="white", edgecolor="none", pad=1.5))


def _view(ax, mesh, axes, color, title, labels):
    a, b = axes
    tri = mesh.triangles[:, :, [a, b]]
    ax.add_collection(PolyCollection(tri, facecolors=[color], edgecolors=[color], linewidths=0.4))
    lo, hi = mesh.bounds[0][[a, b]], mesh.bounds[1][[a, b]]
    span = max(hi - lo)
    pad = span * 0.32 + 6
    _dim(ax, (lo[0], lo[1]), (hi[0], lo[1]), labels[0], span * 0.12 + 3, True)
    _dim(ax, (lo[0], lo[1]), (lo[0], hi[1]), labels[1], span * 0.12 + 3, False)
    cx, cy = (lo + hi) / 2
    half = span / 2 + pad
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy - half, cy + half)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=11, color="0.3")


def main():
    vdir = Path(sys.argv[1])
    res = json.loads((vdir / "result.json").read_text(encoding="utf-8"))
    files = sorted(vdir.glob("part_*.stl"))  # same order (and colours) as preview and USDZ
    if FONT:
        plt.rcParams["font.family"] = FONT
    n = len(files)
    row_h, head_h = 2.7, 1.25
    lines = max(len(res.get("hardware", [])), 1) + max(len(res.get("checks", [])), 1) + 2
    foot_h = 0.32 * lines + 0.4
    fig = plt.figure(figsize=(9, head_h + row_h * n + foot_h), dpi=120)
    H = head_h + row_h * n + foot_h

    def y(inch):  # figure fraction from top, in inches
        return 1 - inch / H

    fig.text(0.04, y(0.45), f"{vdir.parent.name}  {vdir.name}", fontsize=20, fontweight="bold")
    overall = res.get("parts_size_mm")
    fig.text(0.04, y(0.95), t("parts", n=n) + ("   " + t("overall", s=size_text(overall)) if overall else ""),
             fontsize=13)

    for i, f in enumerate(files):
        name = f.stem[5:]
        info = res.get("parts", {}).get(name, {})
        mesh = trimesh.load(f)
        size = info.get("bbox_mm", {}).get("size") or list(mesh.extents)
        top = head_h + row_h * i
        fig.add_artist(plt.Line2D([0.03, 0.97], [y(top + 0.05)] * 2, color="0.85", lw=1))
        c = part_color(i)
        fig.add_artist(plt.Rectangle((0.04, y(top + 0.55)), 0.035, 0.18 / H * 2, color=c, transform=fig.transFigure))
        fig.text(0.09, y(top + 0.45), name, fontsize=15, fontweight="bold")
        fig.text(0.04, y(top + 0.95), f"{size_text(size)} mm", fontsize=14)
        hs = info.get("holes") or []
        hole_txt = ", ".join(f"{t('half') + ' ' if h.get('half') else ''}Ø{fmt(h['d'])}×{h['n']}" for h in hs)
        fig.text(0.04, y(top + 1.35), f"{t('holes')}: {hole_txt or t('none')}", fontsize=11, wrap=True)
        if "fits_bed" in info:
            bed = res.get("bed_mm") or []
            ok = info["fits_bed"]
            fig.text(0.04, y(top + 1.75), (t("bed_ok") if ok else t("bed_ng")) + f"  ({size_text(bed)})",
                     fontsize=11, color="0.25" if ok else "#c0392b")
        fig.text(0.04, y(top + 2.1), f"W × D × H (X × Y × Z)", fontsize=9, color="0.55")
        ax1 = fig.add_axes((0.38, y(top + row_h - 0.1), 0.29, (row_h - 0.3) / H))
        _view(ax1, mesh, (0, 1), c, t("top"), (fmt(size[0]), fmt(size[1])))
        ax2 = fig.add_axes((0.68, y(top + row_h - 0.1), 0.29, (row_h - 0.3) / H))
        _view(ax2, mesh, (0, 2), c, t("front"), (fmt(size[0]), fmt(size[2])))

    ytop = head_h + row_h * n + 0.2
    fig.add_artist(plt.Line2D([0.03, 0.97], [y(ytop - 0.1)] * 2, color="0.85", lw=1))
    for key, items in (("buy", res.get("hardware", [])), ("check", res.get("checks", []))):
        fig.text(0.04, y(ytop + 0.25), t(key), fontsize=13, fontweight="bold")
        ytop += 0.32
        for line in items or [t("missing")]:
            fig.text(0.07, y(ytop + 0.25), "・" + line if JA else "- " + line, fontsize=11)
            ytop += 0.32
        ytop += 0.12
    fig.savefig(vdir / "sheet.png")


if __name__ == "__main__":
    main()
