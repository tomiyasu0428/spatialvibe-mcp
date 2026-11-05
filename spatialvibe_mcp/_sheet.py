"""Dimension sheet: one tall PNG meant to be read on a phone in the field.

Header: part count, overall size of the printed parts, which way the views look, and warnings.
One row per part: colour, size W×D×H, holes with numbered centres, whether it fits the print bed,
the part's own warnings, and three flat views (top, front, side) with dimension lines and the
numbered hole centres marked. Footer: what to buy (`hardware`) and what to check before printing
(`checks`) from the script.

View convention (also in WORKFLOW.md): the person stands at -Y and looks toward +Y, +X is their
right, +Z is up. 正面 = what that person sees.

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
    "holes": ("穴", "holes"), "half": ("円弧", "arc"), "none": ("なし", "none"), "slot": ("長穴", "slot"),
    "bed_ok": ("ベッドに入る ✓", "fits bed ✓"), "bed_ng": ("ベッドに入らない ✗", "too big for bed ✗"),
    "top": ("上から（+Z側）", "top (from +Z)"), "front": ("正面から（−Y側・右が+X）", "front (from −Y, +X right)"),
    "side": ("右横から（+X側・右が+Y）", "right side (from +X, +Y right)"),
    "conv": ("向き: 使う人は −Y 側に立って +Y を見る（右手が +X、上が +Z）", "View: person at −Y looking +Y (+X right, +Z up)"),
    "warn": ("注意", "Warnings"), "mark": ("注意: ", "! "), "pos": ("穴の中心 (X, Y, Z mm)", "hole centres (X, Y, Z mm)"),
    "more": ("ほか {n} 個", "{n} more"),
    "buy": ("買うもの", "Hardware"), "check": ("印刷前に確認", "Check before printing"),
    "missing": ("（スクリプトに書かれていません）", "(not given in the script)"),
}


def wrap(text, width=26):
    """Split into lines that fit the left column (Japanese has no spaces to break on)."""
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


def t(key, **kw):
    return T[key][0 if JA else 1].format(**kw)


def fmt(v):
    txt = f"{v:.1f}".rstrip("0").rstrip(".")
    return "0" if txt in ("-0", "") else txt


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


def _view(ax, mesh, axes, color, title, labels, marks=()):
    a, b = axes
    tri = mesh.triangles[:, :, [a, b]]
    ax.add_collection(PolyCollection(tri, facecolors=[color], edgecolors=[color], linewidths=0.4))
    lo, hi = mesh.bounds[0][[a, b]], mesh.bounds[1][[a, b]]
    span = max(hi - lo)
    pad = span * 0.32 + 6
    _dim(ax, (lo[0], lo[1]), (hi[0], lo[1]), labels[0], span * 0.12 + 3, True)
    _dim(ax, (lo[0], lo[1]), (lo[0], hi[1]), labels[1], span * 0.12 + 3, False)
    for num, (u, v) in marks:  # numbered hole centres seen end-on in this view
        r = span * 0.035 + 1
        ax.plot([u - r, u + r], [v, v], color="black", lw=0.9)
        ax.plot([u, u], [v - r, v + r], color="black", lw=0.9)
        ax.text(u + r * 0.9, v + r * 0.9, str(num), fontsize=8, fontweight="bold", color="black",
                bbox=dict(facecolor="white", edgecolor="none", pad=0.3, alpha=0.8))
    cx, cy = (lo + hi) / 2
    half = span / 2 + pad
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy - half, cy + half)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_title(title, fontsize=9, color="0.3")


def main():
    vdir = Path(sys.argv[1])
    res = json.loads((vdir / "result.json").read_text(encoding="utf-8"))
    files = sorted(vdir.glob("part_*.stl"))  # same order (and colours) as preview and USDZ
    if FONT:
        plt.rcParams["font.family"] = FONT
    n = len(files)
    warnings = res.get("warnings", [])
    infos = [res.get("parts", {}).get(f.stem[5:], {}) for f in files]
    MAXPOS = 8

    def row_lines(info):
        hl = info.get("hole_list") or []
        own = [ln for w in warnings if w.startswith(f"{info.get('_name')}:")
               for ln in wrap(t("mark") + w[len(info.get('_name')) + 1:].strip())]
        n_pos = min(len(hl), MAXPOS) + (1 if len(hl) > MAXPOS else 0) + (1 if hl else 0)
        return 1.4 + 0.26 * n_pos + 0.32 + 0.27 * len(own) + 0.35  # inches of text in the left column

    for f, info in zip(files, infos):
        info["_name"] = f.stem[5:]
    rows = [max(2.9, row_lines(info)) for info in infos]
    glob_w = [ln for w in warnings if not any(w.startswith(f"{i['_name']}:") for i in infos)
              for ln in wrap(w, 52)]
    head_h = 1.55 + (0.3 + 0.27 * len(glob_w) if glob_w else 0)
    lines = max(len(res.get("hardware", [])), 1) + max(len(res.get("checks", [])), 1) + 2
    foot_h = 0.32 * lines + 0.4
    H = head_h + sum(rows) + foot_h
    fig = plt.figure(figsize=(9, H), dpi=120)

    def y(inch):  # figure fraction from top, in inches
        return 1 - inch / H

    fig.text(0.04, y(0.45), f"{vdir.parent.name}  {vdir.name}", fontsize=20, fontweight="bold")
    overall = res.get("parts_size_mm")
    fig.text(0.04, y(0.95), t("parts", n=n) + ("   " + t("overall", s=size_text(overall)) if overall else ""),
             fontsize=13)
    fig.text(0.04, y(1.3), t("conv"), fontsize=9.5, color="0.4")
    if glob_w:
        fig.text(0.04, y(1.72), t("warn"), fontsize=12, fontweight="bold", color="#c0392b")
        for k, w in enumerate(glob_w):
            fig.text(0.07, y(1.99 + 0.27 * k), w, fontsize=10, color="#c0392b")

    top = head_h
    for i, (f, info, row_h) in enumerate(zip(files, infos, rows)):
        name = info["_name"]
        mesh = trimesh.load(f)
        size = info.get("bbox_mm", {}).get("size") or list(mesh.extents)
        fig.add_artist(plt.Line2D([0.03, 0.97], [y(top + 0.05)] * 2, color="0.85", lw=1))
        c = part_color(i)
        fig.add_artist(plt.Rectangle((0.04, y(top + 0.55)), 0.03, 0.18 / H * 2, color=c, transform=fig.transFigure))
        fig.text(0.085, y(top + 0.45), name, fontsize=14, fontweight="bold")
        fig.text(0.04, y(top + 0.85), f"{size_text(size)} mm", fontsize=13)
        fig.text(0.04, y(top + 1.08), "W × D × H (X × Y × Z)", fontsize=8, color="0.55")
        hs = info.get("holes") or []
        def htxt(h):
            if h.get("slot_length"):
                return f"{t('slot')} {fmt(h['d'])}×{fmt(h['slot_length'])}×{h['n']}"
            return f"{t('half') + ' ' if h.get('half') else ''}Ø{fmt(h['d'])}×{h['n']}"
        hole_txt = ", ".join(htxt(h) for h in hs)
        fig.text(0.04, y(top + 1.4), f"{t('holes')}: {hole_txt or t('none')}", fontsize=10)
        yy = top + 1.4
        hl = info.get("hole_list") or []
        marks = {"Z": [], "Y": [], "X": []}
        if hl:
            yy += 0.26
            fig.text(0.04, y(yy), t("pos"), fontsize=8.5, color="0.45")
            for k, h in enumerate(hl, 1):
                x0, y0, z0 = h["at"]
                if h["axis"] in marks:
                    marks[h["axis"]].append((k, {"Z": (x0, y0), "Y": (x0, z0), "X": (y0, z0)}[h["axis"]]))
                if k <= MAXPOS:
                    yy += 0.26
                    if h.get("kind") == "slot":
                        label = f"{t('slot')} {fmt(h['d'])}×{fmt(h['length'])}"
                    else:
                        label = f"Ø{fmt(h['d'])}" + (f" {t('half')}" if h["half"] else "")
                    fig.text(0.05, y(yy), f"{k}. {label}  ({fmt(x0)}, {fmt(y0)}, {fmt(z0)})", fontsize=9)
            if len(hl) > MAXPOS:
                yy += 0.26
                fig.text(0.05, y(yy), t("more", n=len(hl) - MAXPOS), fontsize=9, color="0.45")
        if "fits_bed" in info:
            yy += 0.32
            bed = res.get("bed_mm") or []
            ok = info["fits_bed"]
            fig.text(0.04, y(yy), (t("bed_ok") if ok else t("bed_ng")) + f"  ({size_text(bed)})",
                     fontsize=10, color="0.25" if ok else "#c0392b")
        for w in warnings:
            if w.startswith(f"{name}:"):
                for ln in wrap(t("mark") + w[len(name) + 1:].strip()):
                    yy += 0.27
                    fig.text(0.04, y(yy), ln, fontsize=9.5, color="#c0392b")
        vh = (row_h - 0.35) / H
        for col, (axes, key, lab, mk) in enumerate((
                ((0, 1), "top", (size[0], size[1]), marks["Z"]),
                ((0, 2), "front", (size[0], size[2]), marks["Y"]),
                ((1, 2), "side", (size[1], size[2]), marks["X"]))):
            ax = fig.add_axes((0.37 + col * 0.21, y(top + row_h - 0.1), 0.2, vh))
            _view(ax, mesh, axes, c, t(key), (fmt(lab[0]), fmt(lab[1])), mk)
        top += row_h

    ytop = top + 0.2
    fig.add_artist(plt.Line2D([0.03, 0.97], [y(ytop - 0.1)] * 2, color="0.85", lw=1))
    for key, items in (("buy", res.get("hardware", [])), ("check", res.get("checks", []))):
        fig.text(0.04, y(ytop + 0.25), t(key), fontsize=13, fontweight="bold")
        ytop += 0.32
        for line in items or [t("missing")]:
            fig.text(0.07, y(ytop + 0.25), "・" + line if JA else "- " + line, fontsize=11)
            ytop += 0.32
        ytop += 0.12
    fig.savefig(vdir / "sheet.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
