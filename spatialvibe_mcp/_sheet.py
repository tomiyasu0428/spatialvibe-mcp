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
    "fit": ("合わせる寸法（形から測った値）", "Fit dimensions (measured on the shape)"),
    "spacing": ("穴の間隔", "hole spacing"), "cbore": ("座ぐり", "c-bore"), "csk": ("皿", "csk"),
    "depth": ("深さ", "depth"), "clear": ("{to} とのすき間 {mm} mm", "gap to {to}: {mm} mm"),
    "touch": ("{to} に接する", "touches {to}"), "printpose": ("印刷の向きでは {s} mm（print_{n}.stl を使う）",
                                                     "printed as {s} mm (use print_{n}.stl)"),
    "origin": ("原点 (0,0,0): {o}", "origin (0,0,0): {o}"),
    "noorigin": ("原点 (0,0,0): スクリプトに説明なし", "origin (0,0,0): not described"),
    "exp": ("予定 {e}", "plan {e}"), "nomeasure": ("測れない", "not measurable"),
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


def _view(ax, mesh, axes, color, title, labels, marks=(), ctx=(), fits=()):
    a, b = axes
    for cm in ctx:  # surroundings in light grey behind the part (clipped to the frame)
        ax.add_collection(PolyCollection(cm.triangles[:, :, [a, b]], facecolors=[(0.80, 0.82, 0.86)],
                                         edgecolors="none", alpha=0.6, zorder=0))
    tri = mesh.triangles[:, :, [a, b]]
    ax.add_collection(PolyCollection(tri, facecolors=[color], edgecolors=[color], linewidths=0.4, zorder=1))
    lo, hi = mesh.bounds[0][[a, b]], mesh.bounds[1][[a, b]]
    span = max(hi - lo)
    pad = span * 0.32 + 6
    _dim(ax, (lo[0], lo[1]), (hi[0], lo[1]), labels[0], span * 0.12 + 3, True)
    _dim(ax, (lo[0], lo[1]), (lo[0], hi[1]), labels[1], span * 0.12 + 3, False)
    for (u0, v0), (u1, v1), txt in fits:  # measured fit dimensions, drawn where they really are
        ax.annotate("", xy=(u1, v1), xytext=(u0, v0),
                    arrowprops=dict(arrowstyle="<->", color="#1f4fe0", lw=1.3, shrinkA=0, shrinkB=0), zorder=5)
        ax.text((u0 + u1) / 2, (v0 + v1) / 2, txt, ha="center", va="center", fontsize=8.5, fontweight="bold",
                color="#1f4fe0", zorder=6, bbox=dict(facecolor="white", edgecolor="#1f4fe0", pad=1.2, lw=0.6))
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
        plt.rcParams["font.family"] = [FONT, "DejaVu Sans"]  # fallback for ≥ ± ° etc.
    n = len(files)
    warnings = res.get("warnings", [])
    infos = [res.get("parts", {}).get(f.stem[5:], {}) for f in files]
    MAXPOS = 10
    ctx_meshes = [trimesh.load(f) for f in sorted(vdir.glob("ctx_*.stl"))]
    dims_all = res.get("dims") or []
    clear_all = res.get("clearance") or []

    def hole_label(h):
        if h.get("kind") == "slot":
            txt = f"{t('slot')} {fmt(h['d'])}×{fmt(h['length'])}"
        else:
            txt = f"Ø{fmt(h['d'])}" + (f" {t('half')}" if h["half"] else "")
        if h.get("counterbore"):
            cb = h["counterbore"]
            txt += f" ＋{t('cbore')}Ø{fmt(cb['d'])} {t('depth')}{fmt(cb['depth'])}"
        if h.get("countersink"):
            txt += f" ＋{t('csk')}Ø{fmt(h['countersink']['d'])}"
        return txt

    def part_lines(name, info):
        """[(text, fontsize, colour, bold, indent)] for the left column of one part."""
        L = []
        own = [d for d in dims_all if d.get("part") == name]
        if own:
            L.append((t("fit"), 10, "#1f4fe0", True, 0))
            for d in own:
                tag = f"{d['_tag']} " if d.get("_tag") else "   "
                if d.get("value") is None:
                    L += [(ln, 10.5, "#c0392b", True, 1) for ln in wrap(f"{tag}{d['label']}: {t('nomeasure')}", 22)]
                    continue
                v = f"{fmt(d['value'])} {d.get('unit', 'mm')}"
                tail = ""
                if "expect" in d:
                    tail = "  ✓" if d.get("ok") else f"  ✗ {t('exp', e=fmt(d['expect']))}"
                L.append((f"{tag}{d['label']}  {v}{tail}", 11.5, "#1f4fe0" if d.get("ok", True) else "#c0392b", True, 1))
        size = info.get("bbox_mm", {}).get("size") or [0, 0, 0]
        L.append((f"{size_text(size)} mm   W×D×H (X×Y×Z)", 11, "0.15", False, 0))
        if info.get("print_size_mm"):
            L.append((t("printpose", s=size_text(info["print_size_mm"]), n=name), 9, "0.35", False, 0))
        for sp in info.get("hole_spacing") or []:
            along = " / ".join(f"{ax} {'・'.join(fmt(v) for v in vals)}" for ax, vals in sp["along"].items())
            L.append((f"{t('spacing')} Ø{fmt(sp['d'])}: {along} mm", 10, "0.15", True, 0))
        hl = info.get("hole_list") or []
        if hl:
            L.append((t("pos"), 8.5, "0.45", False, 0))
            for k, h in enumerate(hl[:MAXPOS], 1):
                x0, y0, z0 = h["at"]
                head = f"{k}. {hole_label(h)}"
                xyz = f"({fmt(x0)}, {fmt(y0)}, {fmt(z0)})"
                if len(head) + len(xyz) <= 30:
                    L.append((f"{head}  {xyz}", 9, "0.15", False, 1))
                else:  # never break inside a number
                    L += [(head, 9, "0.15", False, 1), (xyz, 9, "0.15", False, 3)]
            if len(hl) > MAXPOS:
                L.append((t("more", n=len(hl) - MAXPOS), 9, "0.45", False, 1))
        else:
            L.append((f"{t('holes')}: {t('none')}", 10, "0.15", False, 0))
        for c in clear_all:
            if c.get("part") == name and c.get("mm") is not None:
                L.append(((t("touch", to=c["to"]) if c["mm"] == 0 else t("clear", to=c["to"], mm=fmt(c["mm"]))),
                          9.5, "0.25", False, 0))
        if "fits_bed" in info:
            bed = res.get("bed_mm") or []
            ok = info["fits_bed"]
            L.append(((t("bed_ok") if ok else t("bed_ng")) + f"  ({size_text(bed)})", 9.5,
                      "0.25" if ok else "#c0392b", False, 0))
        for w in warnings:
            if w.startswith(f"{name}:"):
                L += [(ln, 9.5, "#c0392b", False, 0) for ln in wrap(t("mark") + w[len(name) + 1:].strip())]
        return L

    for f, info in zip(files, infos):
        info["_name"] = f.stem[5:]
        k = 0
        for d in dims_all:  # letters tie a drawn dimension to its line in the list
            if d.get("part") == info["_name"] and d.get("p") and d.get("value") is not None:
                d["_tag"] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[k % 26]
                k += 1
    LINE = 0.27
    plines = [part_lines(info["_name"], info) for info in infos]
    rows = [max(2.9, 0.75 + LINE * len(pl) + 0.3) for pl in plines]
    glob_w = [ln for w in warnings if not any(w.startswith(f"{i['_name']}:") for i in infos)
              for ln in wrap(w, 52)]
    head_h = 1.85 + (0.3 + 0.27 * len(glob_w) if glob_w else 0)
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
    fig.text(0.04, y(1.58), t("origin", o=res["origin"]) if res.get("origin") else t("noorigin"),
             fontsize=9.5, color="0.15" if res.get("origin") else "0.5")
    if glob_w:
        fig.text(0.04, y(2.02), t("warn"), fontsize=12, fontweight="bold", color="#c0392b")
        for k, w in enumerate(glob_w):
            fig.text(0.07, y(2.29 + 0.27 * k), w, fontsize=10, color="#c0392b")

    VIEWS = (((0, 1), "top", 2), ((0, 2), "front", 1), ((1, 2), "side", 0))  # (plane axes, label, normal axis)
    top = head_h
    for i, (f, info, row_h, pl) in enumerate(zip(files, infos, rows, plines)):
        name = info["_name"]
        mesh = trimesh.load(f)
        size = info.get("bbox_mm", {}).get("size") or list(mesh.extents)
        fig.add_artist(plt.Line2D([0.03, 0.97], [y(top + 0.05)] * 2, color="0.85", lw=1))
        c = part_color(i)
        fig.add_artist(plt.Rectangle((0.04, y(top + 0.55)), 0.03, 0.18 / H * 2, color=c, transform=fig.transFigure))
        fig.text(0.085, y(top + 0.45), name, fontsize=14, fontweight="bold")
        yy = top + 0.75
        for text, fs, col, bold, ind in pl:
            yy += LINE
            fig.text(0.04 + 0.015 * ind, y(yy), text, fontsize=fs, color=col, fontweight="bold" if bold else "normal")
        marks = {"Z": [], "Y": [], "X": []}
        for k, h in enumerate(info.get("hole_list") or [], 1):
            x0, y0, z0 = h["at"]
            if h["axis"] in marks:
                marks[h["axis"]].append((k, {"Z": (x0, y0), "Y": (x0, z0), "X": (y0, z0)}[h["axis"]]))
        fits = {0: [], 1: [], 2: []}
        for d in dims_all:
            if d.get("part") != name or not d.get("p") or d.get("value") is None:
                continue
            pa, pb = d["p"]
            dv = [abs(pb[k] - pa[k]) for k in range(3)]
            length = max(1e-9, sum(x * x for x in dv) ** 0.5)
            # views whose plane holds the segment; of those, the one where the part looks biggest
            cands = [k for k in range(3) if dv[k] <= 0.05 * length] or [min(range(3), key=lambda k: dv[k])]
            ext = [size[0], size[1], size[2]]
            nrm = max(cands, key=lambda k: ext[(k + 1) % 3] * ext[(k + 2) % 3])
            fits[nrm].append(((pa, pb), f"{d['_tag']} {fmt(d['value'])}"))
        vh = (row_h - 0.35) / H
        for col, (axes, key, nrm) in enumerate(VIEWS):
            a_, b_ = axes
            seg = [((pa[a_], pa[b_]), (pb[a_], pb[b_]), txt) for (pa, pb), txt in fits[nrm]]
            mk = marks[{2: "Z", 1: "Y", 0: "X"}[nrm]]
            ax = fig.add_axes((0.37 + col * 0.21, y(top + row_h - 0.1), 0.2, vh))
            _view(ax, mesh, axes, c, t(key), (fmt(size[a_]), fmt(size[b_])), mk, ctx_meshes, seg)
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
