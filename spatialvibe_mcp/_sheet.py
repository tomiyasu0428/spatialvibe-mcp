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
from matplotlib.collections import LineCollection, PolyCollection  # noqa: E402

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
    "typed": ("（座標で指定・形からは測っていない）", "(typed coordinates, not measured)"),
    "vs": ("{l} {v} → {d}", "{l} {v} → {d}"), "detail": ("{t}  {l}", "{t}  {l}"),
    "seen": ("{v}から見た断面", "section, seen from {v}"), "overview": ("全体（記号の場所）", "overview (where each letter is)"),
    "touchmany": ("接する: {l}", "touches: {l}"), "dirs": {"X": "+X側", "Y": "−Y側（正面）", "Z": "上"},
    "buy": ("買うもの", "Hardware"), "check": ("印刷前に確認", "Check before printing"),
    "missing": ("（スクリプトに書かれていません）", "(not given in the script)"),
}


def wrap(text, width=26):
    """Split into lines that fit the left column (Japanese has no spaces to break on)."""
    return [text[i:i + width] for i in range(0, len(text), width)] or [""]


def t(key, **kw):
    v = T[key]
    if isinstance(v, dict):
        return v
    return v[0 if JA else 1].format(**kw)


def fmt(v):
    txt = (f"{v:.2f}" if abs(v) < 10 else f"{v:.1f}").rstrip("0").rstrip(".")
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


def _section(mesh, normal, origin):
    """Cut lines of a mesh with a plane: (n, 2, 3) segments (no extra packages needed)."""
    try:
        return trimesh.intersections.mesh_plane(mesh, plane_normal=normal, plane_origin=origin)
    except Exception:
        return []


def _detail(ax, mesh, ctx, d, color, title):
    """Zoomed view of one fit dimension: light silhouette, bold section through it, the arrow."""
    import numpy as np
    pa, pb = (np.array(d["p"][0]), np.array(d["p"][1])) if d.get("p") else (np.array(d["at"]),) * 2
    seg = pb - pa
    L = float(np.linalg.norm(seg))
    if d.get("view_normal"):
        cands = ["XYZ".index(d["view_normal"])]
    else:
        cands = [k for k in range(3) if abs(seg[k]) <= 0.05 * max(L, 1e-9)] or [int(np.argmin(np.abs(seg)))]
    mid = (pa + pb) / 2

    def nsec(k):
        nv = np.zeros(3)
        nv[k] = 1
        return len(_section(mesh, nv, mid))
    k = max(cands, key=nsec)  # the view whose cut shows the most shape there
    a, b = [i for i in range(3) if i != k]
    if k == 1:   # front view is drawn from -Y with +X to the right (same as the overview)
        a, b = 0, 2
    nv = np.zeros(3)
    nv[k] = 1
    half = max(L * 0.9, 9.0)
    ax.add_collection(PolyCollection(mesh.triangles[:, :, [a, b]], facecolors=[(*color[:3], 0.18)],
                                     edgecolors="none", zorder=1))
    for cm in ctx:
        cs = _section(cm, nv, mid)
        if len(cs):
            ax.add_collection(LineCollection(cs[:, :, [a, b]], colors=["0.55"], linewidths=1.2,
                                             linestyles="dashed", zorder=2))
    cs = _section(mesh, nv, mid)
    if len(cs):
        ax.add_collection(LineCollection(cs[:, :, [a, b]], colors=["0.1"], linewidths=1.8, zorder=3))
    u0, v0, u1, v1 = pa[a], pa[b], pb[a], pb[b]
    txt = f"{d['_tag']} {fmt(d['value'])}{'°' if d.get('unit') == '°' else ''}"
    if L > 1e-6:
        ax.annotate("", xy=(u1, v1), xytext=(u0, v0),
                    arrowprops=dict(arrowstyle="<->", color="#1f4fe0", lw=2.2, shrinkA=0, shrinkB=0), zorder=5)
    ax.text((u0 + u1) / 2, (v0 + v1) / 2 + half * 0.16, txt, ha="center", va="bottom", fontsize=13,
            fontweight="bold", color="#1f4fe0", zorder=6,
            bbox=dict(facecolor="white", edgecolor="#1f4fe0", pad=2, lw=0.8))
    cx, cy = (u0 + u1) / 2, (v0 + v1) / 2
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy - half, cy + half)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    for sp_ in ax.spines.values():
        sp_.set_color("0.8")
    ax.set_title(title, fontsize=10.5, color="0.1", loc="left")
    ax.text(0.02, 0.02, t("seen", v=t("dirs")["XYZ"[k]]), transform=ax.transAxes, fontsize=7.5, color="0.45")


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

    def fit_lines(name):
        L = []
        for d in [d for d in dims_all if d.get("part") == name]:
            tag = f"{d['_tag']} " if d.get("_tag") else "   "
            if d.get("value") is None:
                L += [(ln, 11, "#c0392b", True, 0) for ln in wrap(f"{tag}{d['label']}: {t('nomeasure')}", 40)]
                continue
            unit = d.get("unit", "mm")
            v = f"{fmt(d['value'])}{'°' if unit == '°' else ' mm'}"
            tail = ""
            if "expect" in d:
                tail = "  ✓" if d.get("ok") else f"  ✗ {t('exp', e=fmt(d['expect']))}"
            col = "#1f4fe0" if d.get("ok", True) else "#c0392b"
            if d.get("measured") is False:
                col = "0.45"
                tail = "  " + t("typed")
            L.append((f"{tag}{d['label']}  {v}{tail}", 13, col, True, 0))
            if "vs" in d:
                diff = d["value"] - d["vs"]
                L.append((t("vs", l=d["vs_label"], v=fmt(d["vs"]), d=f"{d['label']} {fmt(d['value'])}"
                           f"（{'+' if diff >= 0 else ''}{fmt(diff)}）"), 10, "0.25", False, 1))
        return L

    def info_lines(name, info):
        """[(text, fontsize, colour, bold, indent)] under the drawings of one part."""
        L = []
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
                ax_ = h["axis"]
                where = ", ".join(f"{c} {fmt(h['at'][i])}" for i, c in enumerate("XYZ") if c != ax_)
                L.append((f"{k}. {hole_label(h)}  ({where})", 9.5, "0.15", False, 1))
            if len(hl) > MAXPOS:
                L.append((t("more", n=len(hl) - MAXPOS), 9, "0.45", False, 1))
        else:
            L.append((f"{t('holes')}: {t('none')}", 10, "0.15", False, 0))
        touching = [c["to"] for c in clear_all if c.get("part") == name and c.get("mm") == 0]
        if touching:
            L.append((t("touchmany", l=", ".join(touching)), 9.5, "0.25", False, 0))
        for c in clear_all:
            if c.get("part") == name and c.get("mm"):
                L.append((t("clear", to=c["to"], mm=fmt(c["mm"])), 9.5, "0.25", False, 0))
        if "fits_bed" in info:
            bed = res.get("bed_mm") or []
            ok = info["fits_bed"]
            L.append(((t("bed_ok") if ok else t("bed_ng")) + f"  ({size_text(bed)})", 9.5,
                      "0.25" if ok else "#c0392b", False, 0))
        for w in warnings:
            if w.startswith(f"{name}:"):
                L += [(ln, 9.5, "#c0392b", False, 0) for ln in wrap(t("mark") + w[len(name) + 1:].strip(), 46)]
        return L

    for f, info in zip(files, infos):
        info["_name"] = f.stem[5:]
        k = 0
        for d in dims_all:  # letters tie a drawing to its line in the list
            if d.get("part") == info["_name"] and d.get("value") is not None and (d.get("p") or d.get("at")):
                d["_tag"] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[k % 26]
                k += 1
    LINE, PANEL, VIEW_H = 0.3, 2.75, 2.6
    blocks = []
    for info in infos:
        name = info["_name"]
        fl = fit_lines(name)
        det = [d for d in dims_all if d.get("part") == name and d.get("_tag")]
        il = info_lines(name, info)
        h = 0.75 + (0.35 + LINE * len(fl) if fl else 0) + PANEL * ((len(det) + 2) // 3) \
            + (0.35 if det else 0) + VIEW_H + 0.5 + LINE * len(il) + 0.3
        blocks.append((fl, det, il, h))
    glob_w = [ln for w in warnings if not any(w.startswith(f"{i['_name']}:") for i in infos)
              for ln in wrap(w, 52)]
    head_h = 1.85 + (0.3 + 0.27 * len(glob_w) if glob_w else 0)
    lines = max(len(res.get("hardware", [])), 1) + max(len(res.get("checks", [])), 1) + 2
    foot_h = 0.32 * lines + 0.4
    H = head_h + sum(b[3] for b in blocks) + foot_h
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
    for i, (f, info, (fl, det, il, block_h)) in enumerate(zip(files, infos, blocks)):
        name = info["_name"]
        mesh = trimesh.load(f)
        size = info.get("bbox_mm", {}).get("size") or list(mesh.extents)
        c = part_color(i)
        fig.add_artist(plt.Line2D([0.03, 0.97], [y(top + 0.05)] * 2, color="0.85", lw=1))
        fig.add_artist(plt.Rectangle((0.04, y(top + 0.55)), 0.03, 0.18 / H * 2, color=c, transform=fig.transFigure))
        fig.text(0.085, y(top + 0.45), name, fontsize=14, fontweight="bold")
        yy = top + 0.75
        if fl:
            yy += 0.3
            fig.text(0.04, y(yy), t("fit"), fontsize=11, color="#1f4fe0", fontweight="bold")
            for text, fs, col, bold, ind in fl:
                yy += LINE
                fig.text(0.05 + 0.02 * ind, y(yy), text, fontsize=fs, color=col, fontweight="bold" if bold else "normal")
        # one zoomed panel per fit dimension: where to put the caliper
        for j, d in enumerate(det):
            r_, c_ = divmod(j, 3)
            ax = fig.add_axes((0.04 + c_ * 0.315, y(yy + 0.25 + PANEL * (r_ + 1) - 0.15), 0.29, (PANEL - 0.55) / H))
            _detail(ax, mesh, ctx_meshes, d, c, t("detail", t=d["_tag"], l=d["label"]))
        yy += (0.35 + PANEL * ((len(det) + 2) // 3)) if det else 0
        # overview: whole part, hole numbers, and a letter where each fit dimension is
        marks = {"Z": [], "Y": [], "X": []}
        for k, h in enumerate(info.get("hole_list") or [], 1):
            x0, y0, z0 = h["at"]
            if h["axis"] in marks:
                marks[h["axis"]].append((k, {"Z": (x0, y0), "Y": (x0, z0), "X": (y0, z0)}[h["axis"]]))
        fig.text(0.04, y(yy + 0.3), t("overview"), fontsize=9, color="0.4")
        for col, (axes, key, nrm) in enumerate(VIEWS):
            a_, b_ = axes
            ax = fig.add_axes((0.04 + col * 0.315, y(yy + 0.35 + VIEW_H), 0.29, (VIEW_H - 0.35) / H))
            _view(ax, mesh, axes, c, t(key), (fmt(size[a_]), fmt(size[b_])), marks[{2: "Z", 1: "Y", 0: "X"}[nrm]],
                  ctx_meshes, ())
            for d in det:  # small letter at the place of each fit dimension
                pts = d.get("p") or [d.get("at"), d.get("at")]
                mu = (pts[0][a_] + pts[1][a_]) / 2
                mv = (pts[0][b_] + pts[1][b_]) / 2
                ax.text(mu, mv, d["_tag"], fontsize=8, fontweight="bold", color="white", ha="center", va="center",
                        zorder=7, bbox=dict(boxstyle="circle,pad=0.2", facecolor="#1f4fe0", edgecolor="none"))
        yy += 0.5 + VIEW_H
        for text, fs, col, bold, ind in il:
            yy += LINE
            fig.text(0.04 + 0.02 * ind, y(yy), text, fontsize=fs, color=col, fontweight="bold" if bold else "normal")
        top += block_h

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
