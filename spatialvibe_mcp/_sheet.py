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
    "overall_n": ("組み立てた全体 {s} mm（部品ごとの大きさは各部品の欄）", "assembled {s} mm (each part below)"),
    "same": ("{a} と同じ形です（{n} 個目）。寸法も同じなので、図は {a} の欄を見てください。",
             "same shape as {a} (copy {n}); see {a} for the drawings."),
    "assembled": ("取り付けたところ（正面から・灰色は周りの物）", "Installed (front view; grey = surroundings)"),
    "assembled_side": ("横から", "from the side"),
    "keyfit": ("合わせる寸法（大事なもの）", "Key fit dimensions"),
    "more_pg": ("細かい図と全部の寸法は 2 枚目（sheet_detail.png）。印刷する人や、詳しく確かめたいときに。",
                "All drawings and dimensions: page 2 (sheet_detail.png)."),
    "detail_title": ("{p}  {v}  詳しい寸法図（2 枚目）", "{p}  {v}  detailed sheet (page 2)"),
    "same_many": ("{l} は {a} と同じ形です（全部で {n} 個）。寸法は {a} の欄を見てください。",
                  "{l}: same shape as {a} ({n} in total)."),
    "mirror": ("{a} の左右反転（鏡写し）の形です。寸法は {a} の欄と同じ。print_{a}.stl と print_{b}.stl を 1 個ずつ印刷（同じ方を 2 個にしない）。",
               "mirror image of {a}; print print_{a}.stl and print_{b}.stl once each."),
    "ptime": ("印刷の目安：全部で約 {t}（部品ごと: {each}）", "print time, rough: {t} in total ({each})"),
    "motion": ("動かしたとき（灰色は周り。赤は当たるところ）", "When it moves (grey: surroundings; red: collides)"),
    "pose0": ("取り付けたところ", "installed"),
    "details": ("詳しい情報（印刷する人・CAD 用。現場では見なくてよい）", "Details (for whoever prints or edits it)"),
    "holes": ("穴", "holes"), "half": ("円弧", "arc"), "none": ("なし", "none"), "slot": ("長穴", "slot"),
    "bed_ok": ("ベッドに入る ✓", "fits bed ✓"), "bed_ng": ("ベッドに入らない ✗", "too big for bed ✗"),
    "top": ("上から", "top"), "front": ("正面から", "front"),
    "side": ("右横から", "right side"),
    "conv": ("「正面」は、使う人が立つ側から見た向きです（右手側が右）", "\"Front\" is what the user sees from where they stand"),
    "conv_v": ("「正面」は、{v}の向きです（右手側が右）", "\"Front\" is the view {v}"),
    "ptime_re": ("今回刷るもの：約 {t}（{each}）。{keep} はそのまま使う", "to print now: {t} ({each}); keep {keep}"),
    "axes": ("座標: 使う人は −Y 側に立って +Y を見る（右手が +X、上が +Z）", "axes: user at −Y looking +Y (+X right, +Z up)"),
    "warn": ("注意", "Warnings"), "mark": ("注意: ", "! "), "pos": ("穴の中心 (X, Y, Z mm)", "hole centres (X, Y, Z mm)"),
    "more": ("ほか {n} 個", "{n} more"),
    "fit": ("合わせる寸法（形から測った値）", "Fit dimensions (measured on the shape)"),
    "spacing": ("穴の間隔", "hole spacing"), "cbore": ("座ぐり", "c-bore"), "csk": ("皿", "csk"),
    "depth": ("深さ", "depth"), "blind": ("（止まり穴）", "(blind)"), "clear": ("{to} とのすき間 {mm} mm", "gap to {to}: {mm} mm"),
    "touch": ("{to} に接する", "touches {to}"), "printpose": ("印刷の向きでは {s} mm（print_{n}.stl を使う）",
                                                     "printed as {s} mm (use print_{n}.stl)"),
    "origin": ("原点 (0,0,0): {o}", "origin (0,0,0): {o}"),
    "noorigin": ("原点 (0,0,0): スクリプトに説明なし", "origin (0,0,0): not described"),
    "exp": ("予定 {e}", "plan {e}"), "nomeasure": ("測れない", "not measurable"),
    "typed": ("（座標で指定・形からは測っていない）", "(typed coordinates, not measured)"),
    "vs": ("{l} {v} → {d}", "{l} {v} → {d}"), "detail": ("{t}  {l}", "{t}  {l}"),
    "seen": ("{v}から見た断面", "section, seen from {v}"), "overview": ("全体（記号の場所）", "overview (where each letter is)"),
    "touchmany": ("接する: {l}", "touches: {l}"),
    "touchmeant": ("接する（意図どおり・測らなくてよい）: {l}", "touches as intended: {l}"),
    "caliper2": ("ノギスで: 穴の縁から縁 {i} mm（内側）／ {o} mm（外側）", "caliper: hole edge to edge {i} (inside) / {o} (outside)"),
    "caliper1": ("ノギスで: {f} から穴の縁まで {e} mm（中心までは +{r}）", "caliper: {f} to hole edge {e} (+{r} to centre)"),
    "level": ("取り付けた向きで 水平から {v}°（スマホの水準器で）", "{v}° from level (phone level app)"),
    "plumb": ("垂直から {v}°", "{v}° from vertical"),
    "atleast": ("{a} 以上なら OK", "OK if {a} or more"),
    "atmost": ("{b} 以下なら OK", "OK if {b} or less"),
    "twoface": ("太線の片方の面を机に置き、もう片方の面にスマホの水準器を当てると {v}°",
                "put one thick-line face on the desk; a phone level on the other reads {v}°"),
    "range": ("この範囲なら OK: {a}〜{b}", "OK if {a}–{b}"),
    "intended": ("意図したすき間（測らなくてよい）: {l}", "intended gaps (no need to measure): {l}"),
    "zoom": ("拡大", "zoom"),
    "installed": ("取り付けた向きの外形", "as installed"), "dirs": {"X": "右横", "Y": "正面", "Z": "上"},
    "buy": ("買うもの", "Hardware"), "check": ("印刷前に確認", "Check before printing"),
    "missing": ("（スクリプトに書かれていません）", "(not given in the script)"),
}


def wrap(text, width=26):
    """Split into lines that fit the left column. Japanese has few spaces, so break at a space, 、 or
    （ near the limit when there is one, never inside a number."""
    out = []
    while len(text) > width:
        cut = max(text.rfind(ch, width // 2, width + 1) for ch in " 、（→")
        if cut <= 0:
            cut = width
            while cut > width // 2 and (text[cut - 1].isdigit() or text[cut - 1] in ".×") and \
                    (text[cut].isdigit() or text[cut] in ".×"):
                cut -= 1
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    out.append(text)
    return [ln for ln in out if ln] or [""]


def t(key, **kw):
    v = T[key]
    if isinstance(v, dict):
        return v
    return v[0 if JA else 1].format(**kw)


def fmt(v):
    txt = (f"{v:.2f}" if abs(v) < 2 else f"{v:.1f}").rstrip("0").rstrip(".")
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


def _arrow(ax, u0, v0, u1, v1, lw=2.2):
    ax.annotate("", xy=(u1, v1), xytext=(u0, v0),
                arrowprops=dict(arrowstyle="<->", color="#1f4fe0", lw=lw, shrinkA=0, shrinkB=0), zorder=5)


def _detail(ax, mesh, ctx, d, color, title):
    """One fit dimension on the whole part: silhouette, the cut through the measured place, one arrow
    (and a zoomed inset when the place is small), so the user sees WHERE to put the caliper."""
    import numpy as np
    pa, pb = (np.array(d["p"][0]), np.array(d["p"][1])) if d.get("p") else (np.array(d["at"]),) * 2
    seg = pb - pa
    L = float(np.linalg.norm(seg))
    mid = (pa + pb) / 2

    def nsec(k):
        nv = np.zeros(3)
        nv[k] = 1
        return len(_section(mesh, nv, mid))
    if d.get("view_normal"):
        k = "XYZ".index(d["view_normal"])
    elif d.get("axis_dir") and (d.get("partial") or (d.get("axial") or 1e9) < 0.6 * L):
        k = int(np.argmax(np.abs(np.array(d["axis_dir"]))))   # a C-shaped seat or a short ring: look down the axis
    elif d.get("axis_dir") and L > 1e-6:   # a diameter: look from the side, square to the arrow and the axis
        cr = np.cross(seg / L, np.array(d["axis_dir"]))
        k = int(np.argmax(np.abs(cr))) if np.linalg.norm(cr) > 0.5 else 1
    else:
        cands = [k for k in range(3) if abs(seg[k]) <= 0.05 * max(L, 1e-9)] or [int(np.argmin(np.abs(seg)))]
        if d.get("ext"):   # keep the extension line visible too (look square to both)
            ev = np.array(d["ext"][1]) - np.array(d["ext"][0])
            both = [k_ for k_ in cands if abs(ev[k_]) <= 0.05 * max(float(np.linalg.norm(ev)), 1e-9)]
            if both:
                cands = both
        ext = mesh.extents

        def area(k_):   # how big the whole part looks from that side; round parts look best from the side
            i, j = [x for x in range(3) if x != k_]
            return ext[i] * ext[j]
        best = max(area(k_) for k_ in cands)
        cands = [k_ for k_ in cands if area(k_) >= 0.6 * best]
        k = max(cands, key=nsec)
    a, b = [i for i in range(3) if i != k]
    nv = np.zeros(3)
    nv[k] = 1

    def draw(axx, zoom):
        axx.add_collection(PolyCollection(mesh.triangles[:, :, [a, b]], facecolors=[tuple(0.7 + 0.3 * c_ for c_ in color[:3])],
                                          edgecolors="none", antialiased=False, zorder=1))
        for cm in ctx:
            axx.add_collection(PolyCollection(cm.triangles[:, :, [a, b]], facecolors=[(0.6, 0.62, 0.66, 0.10)],
                                              edgecolors="none", antialiased=False, zorder=0))
            cs = _section(cm, nv, mid)
            if len(cs):
                axx.add_collection(LineCollection(cs[:, :, [a, b]], colors=["0.5"], linewidths=1.0,
                                                  linestyles="dashed", zorder=2))
        cs = _section(mesh, nv, mid)
        if len(cs):
            axx.add_collection(LineCollection(cs[:, :, [a, b]], colors=["0.1"], linewidths=1.6, zorder=3))
        if d.get("unit") == "°":
            _angle_marks(axx, d, a, b, zoom)
        elif L > 1e-6:
            _arrow(axx, pa[a], pa[b], pb[a], pb[b], 2.4 if zoom else 2.0)
        if d.get("ext"):   # extension line from the arrow to where the end really is (e.g. the rim)
            (e0, e1) = np.array(d["ext"][0]), np.array(d["ext"][1])
            axx.plot([e0[a], e1[a]], [e0[b], e1[b]], color="#1f4fe0", lw=0.9, linestyle="--", zorder=5)
            axx.plot([e0[a]], [e0[b]], "o", color="#1f4fe0", ms=3.5, zorder=6)
        axx.set_aspect("equal")
        axx.set_xticks([])
        axx.set_yticks([])
        for sp_ in axx.spines.values():
            sp_.set_color("0.75")

    draw(ax, False)
    lo, hi = mesh.bounds[0][[a, b]], mesh.bounds[1][[a, b]]
    span = max(hi - lo)
    cx, cy = (lo + hi) / 2
    half = span / 2 * 1.18 + 3
    ax.set_xlim(cx - half, cx + half)
    ax.set_ylim(cy - half, cy + half)
    unit = "°" if d.get("unit") == "°" else ""
    ax.text(0.5, 0.98, f"{d['_tag']} {fmt(d['value'])}{unit}", transform=ax.transAxes, ha="center", va="top",
            fontsize=14, fontweight="bold", color="#1f4fe0", zorder=8,
            bbox=dict(facecolor="white", edgecolor="#1f4fe0", pad=2, lw=0.8))
    small = (L < 0.22 * span) if d.get("unit") != "°" else False
    if small:   # the place is small on this part: show it enlarged in the corner, and mark where it is
        z = max(L * 1.3, 6.0)
        mx, my = mid[a], mid[b]
        ins = ax.inset_axes([0.56, 0.02, 0.43, 0.43])
        draw(ins, True)
        ins.set_xlim(mx - z, mx + z)
        ins.set_ylim(my - z, my + z)
        ins.set_title(t("zoom"), fontsize=7, color="0.4", pad=1)
        ax.add_patch(plt.Rectangle((mx - z, my - z), 2 * z, 2 * z, fill=False, edgecolor="#1f4fe0", lw=0.8,
                                   linestyle=":", zorder=6))
    ax.set_title(title, fontsize=10.5, color="0.1", loc="left")
    ax.text(0.02, 0.02, t("seen", v=t("dirs")["XYZ"[k]]), transform=ax.transAxes, fontsize=7.5, color="0.45")


def _angle_marks(ax, d, a, b, zoom):
    """Highlight the face(s) of an angle and draw the arc; against level, draw the level line."""
    import numpy as np
    at = np.array(d["at"])
    na = np.array(d.get("n_a") or [0, 0, 1])
    span = 25.0
    fa = np.array([-na[b], na[a]])           # face a as a line in this view
    if np.linalg.norm(fa) < 1e-6:
        return
    fa = fa / np.linalg.norm(fa)
    if d.get("ref"):
        ref = np.array([1.0, 0.0])            # level (or plumb) reference line through the point
        if d["ref"] in ("X", "Y"):
            ref = np.array([0.0, 1.0])
        ax.plot([at[a] - span, at[a] + span], [at[b] - span * ref[1], at[b] + span * ref[1]] if ref[1] else
                [at[b], at[b]], color="0.35", lw=1.2, linestyle="--", zorder=4)
        rb = ref
    else:
        nb = np.array(d.get("n_b") or [0, 0, 1])
        rb = np.array([-nb[b], nb[a]])
        rb = rb / (np.linalg.norm(rb) or 1)
        if d.get("at_b"):
            q = np.array(d["at_b"])
            ax.plot([q[a] - span * rb[0], q[a] + span * rb[0]], [q[b] - span * rb[1], q[b] + span * rb[1]],
                    color="#1f4fe0", lw=2.4, zorder=5)
    if np.dot(fa, rb) < 0:
        fa = -fa
    ax.plot([at[a] - span * fa[0], at[a] + span * fa[0]], [at[b] - span * fa[1], at[b] + span * fa[1]],
            color="#1f4fe0", lw=2.4, zorder=5)
    a0, a1 = np.degrees(np.arctan2(rb[1], rb[0])), np.degrees(np.arctan2(fa[1], fa[0]))
    lo_, hi_ = sorted([a0, a1])
    if hi_ - lo_ > 180:
        lo_, hi_ = hi_, lo_ + 360
    from matplotlib.patches import Arc
    ax.add_patch(Arc((at[a], at[b]), span * 0.9, span * 0.9, theta1=lo_, theta2=hi_, color="#1f4fe0", lw=2,
                     zorder=6))


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
        if h.get("through") is False:
            txt += " " + t("blind")
        return txt

    def fit_lines(name):
        L = []
        gaps = []
        for d in [d for d in dims_all if d.get("part") == name]:
            if d.get("kind") == "clearance" and not d.get("panel"):
                if d.get("value") is not None:
                    gaps.append(f"{d['label']} {fmt(d['value'])}")
                continue
            tag = f"{d['_tag']} " if d.get("_tag") else "   "
            if d.get("value") is None:
                L += [(ln, 11, "#c0392b", True, 0) for ln in wrap(f"{tag}{d['label']}: {t('nomeasure')}", 40)]
                continue
            unit = d.get("unit", "mm")
            v = f"{fmt(d['value'])}{'°' if unit == '°' else ' mm'}"
            tail = ""
            if "expect" in d or "min" in d:
                tail = "  ✓" if d.get("ok") else "  ✗"
                if not d.get("ok") and "expect" in d:
                    tail += f" {t('exp', e=fmt(d['expect']))}"
            col = "#1f4fe0" if d.get("ok", True) else "#c0392b"
            if d.get("measured") is False:
                col = "0.45"
                tail = "  " + t("typed")
            L.append((f"{tag}{d['label']}  {v}{tail}", 13, col, True, 0))
            ed = d.get("end_d") or [None, None]
            ends = d.get("ends") or [None, None]
            if d.get("kind") == "distance" and ed[0] and ed[1]:
                r2 = (ed[0] + ed[1]) / 2
                L.append((t("caliper2", i=fmt(d["value"] - r2), o=fmt(d["value"] + r2)), 10, "0.2", False, 1))
            elif d.get("kind") == "distance" and (ed[0] or ed[1]):
                dh = ed[0] or ed[1]
                f_ = ends[1] if ed[0] else ends[0]
                L.append((t("caliper1", f=f_ or "", e=fmt(d["value"] - dh / 2), r=fmt(dh / 2)), 10, "0.2", False, 1))
            if d.get("unit") == "°" and not d.get("ref"):
                L.append((t("twoface", v=fmt(d["value"])), 10, "0.2", False, 1))
            if d.get("unit") == "°" and d.get("ref"):
                L.append((t("level" if d["ref"] == "Z" else "plumb", v=fmt(d["value"])), 10, "0.2", False, 1))
            if "expect" in d and d.get("tol") and d.get("unit") != "°":
                L.append((t("range", a=fmt(d["expect"] - d["tol"]), b=fmt(d["expect"] + d["tol"])),
                          10, "0.2", False, 1))
            elif d.get("min") is not None or d.get("max") is not None:
                if d.get("min") is not None and d.get("max") is not None:
                    txt_ = t("range", a=fmt(d["min"]), b=fmt(d["max"]))
                elif d.get("min") is not None:
                    txt_ = t("atleast", a=fmt(d["min"]))
                else:
                    txt_ = t("atmost", b=fmt(d["max"]))
                L.append((txt_, 10, "0.2", False, 1))
            if "vs" in d:
                diff = d["value"] - d["vs"]
                L.append((t("vs", l=d["vs_label"], v=fmt(d["vs"]), d=f"{d['label']} {fmt(d['value'])}"
                           f"（{'+' if diff >= 0 else ''}{fmt(diff)}）"), 10, "0.25", False, 1))
        if gaps:
            L += [(ln, 9, "0.45", False, 0) for ln in wrap(t("intended", l="、".join(gaps)), 60)]
        return L

    def info_lines(name, info):
        """[(text, fontsize, colour, bold, indent)] under the drawings of one part: what the user needs
        first (printed size, bed, warnings), then small grey details for whoever prints or edits it."""
        L = []
        size = info.get("bbox_mm", {}).get("size") or [0, 0, 0]
        if info.get("print_size_mm"):   # what the user holds on the table: the printed piece lying flat
            L.append((t("printpose", s=size_text(info["print_size_mm"]), n=name), 11, "0.15", True, 0))
        else:
            L.append((f"{size_text(size)} mm", 11, "0.15", True, 0))
        if "fits_bed" in info and not info["fits_bed"]:
            L.append((t("bed_ng") + f"  ({size_text(res.get('bed_mm') or [])})", 10, "#c0392b", False, 0))
        for w in warnings:
            if w.startswith(f"{name}:"):
                L += [(ln, 9.5, "#c0392b", False, 0) for ln in wrap(t("mark") + w[len(name) + 1:].strip(), 46)]
        D = []   # details
        if info.get("print_size_mm"):
            D.append((f"{t('installed')} {size_text(size)} mm", 8.5, "0.45", False, 1))
        for sp in info.get("hole_spacing") or []:
            along = " / ".join(f"{ax} {'・'.join(fmt(v) for v in vals)}" for ax, vals in sp["along"].items())
            D.append((f"{t('spacing')} Ø{fmt(sp['d'])}: {along} mm", 8.5, "0.45", False, 1))
        hl = info.get("hole_list") or []
        if hl:
            D.append((t("pos"), 8, "0.5", False, 1))
            for k, h in enumerate(hl[:MAXPOS], 1):
                where = ", ".join(f"{c} {fmt(h['at'][i])}" for i, c in enumerate("XYZ"))
                D.append((f"{k}. {hole_label(h)}  ({where})", 8.5, "0.45", False, 2))
            if len(hl) > MAXPOS:
                D.append((t("more", n=len(hl) - MAXPOS), 8, "0.5", False, 2))
        if "fits_bed" in info and info["fits_bed"]:
            D.append((t("bed_ok") + f"  ({size_text(res.get('bed_mm') or [])})", 8.5, "0.45", False, 1))
        if D:
            L.append((t("details"), 8.5, "0.5", False, 0))
            L += D
        return L

    def _shape_key(f, flip=None):
        import numpy as np
        v = trimesh.load(f).vertices.copy()
        if flip is not None:
            v[:, flip] *= -1
        v -= v.min(axis=0)
        v = np.round(v / 0.05).astype(np.int64)
        return v[np.lexsort(v.T[::-1])]

    def same_as(k):
        """(index of an earlier part with the same shape, "copy" or "mirror"), or None. Copies are equal
        after a shift; mirrored twins are equal after flipping one axis — they must both be printed."""
        import numpy as np
        a = infos[k]
        for j in range(k):
            b = infos[j]
            va, vb = a.get("volume_cm3"), b.get("volume_cm3")
            sa = (a.get("bbox_mm", {}).get("size") or [])[:3]
            sb = (b.get("bbox_mm", {}).get("size") or [])[:3]
            if not (va and vb and abs(va - vb) <= 0.002 * max(va, vb) + 0.01 and len(sa) == 3 and
                    all(abs(x - y_) < 0.2 for x, y_ in zip(sa, sb))):
                continue
            try:
                ka = _shape_key(files[k])
                if ka.shape == _shape_key(files[j]).shape and np.array_equal(ka, _shape_key(files[j])):
                    return j, "copy"
                for ax in range(3):
                    kb = _shape_key(files[j], ax)
                    if ka.shape == kb.shape and np.array_equal(ka, kb):
                        return j, "mirror"
            except Exception:
                pass
        return None

    labels = res.get("labels") or {}

    def disp(n):   # the word the reply uses (下板), with the file name for whoever prints it
        return f"{labels[n]}（{n}）" if n in labels else n

    for f, info in zip(files, infos):
        info["_name"] = f.stem[5:]
        k = 0
        for d in dims_all:  # letters tie a drawing to its line in the list
            if (d.get("part") == info["_name"] and d.get("value") is not None and (d.get("p") or d.get("at"))
                    and not (d.get("kind") == "clearance" and not d.get("panel"))):
                d["_tag"] = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[k % 26]
                k += 1
    LINE, PANEL, VIEW_H = 0.3, 2.75, 2.6
    def ndims(k_):
        return len([d for d in dims_all if d.get("part") == infos[k_]["_name"] and d.get("_tag")])
    groups = {}
    kinds = {}
    for k in range(len(infos)):   # same-shape groups; the member with the dims is drawn, the rest are one line
        r_ = same_as(k)
        j = None if r_ is None else r_[0]
        if r_ is not None:
            kinds[k] = r_[1]
        root = k if j is None else next(r for r, ms in groups.items() if j in ms)
        groups.setdefault(root, []).append(k)
    copies = {}
    for ms in groups.values():
        keep = max(ms, key=ndims)
        for m in ms:
            if m != keep and ndims(m) == 0:
                copies[m] = keep
                if kinds.get(keep) == "mirror" or kinds.get(m) == "mirror":
                    kinds[m] = "mirror"
    blocks = []
    for k, info in enumerate(infos):
        if k in copies:
            root = copies[k]
            n_ = 1 + sorted(m for m, r in copies.items() if r == root).index(k) + 1
            sibs = sorted(m for m, r in copies.items() if r == root and kinds.get(m) != "mirror")
            if kinds.get(k) != "mirror" and k != sibs[0]:
                blocks.append((None, [], [], 0.0))   # already named on the first copy's line
                continue
            msg = (t("mirror", a=infos[root]["_name"], b=info["_name"]) if kinds.get(k) == "mirror"
                   else t("same", a=infos[root]["_name"], n=n_) if len(sibs) == 1
                   else t("same_many", l="・".join(infos[m]["_name"] for m in sibs), a=infos[root]["_name"],
                          n=len(sibs) + 1))
            ls_ = wrap(msg, 46)
            blocks.append((None, [], [(ln, 11, "0.2", True, 0) for ln in ls_], 0.95 + 0.32 * len(ls_)))
            continue
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
    memo = [(key, [(ln, i_ == 0) for item in (res.get(key2, []) or [t("missing")])
                   for i_, ln in enumerate(wrap(item, 44))])
            for key, key2 in (("buy", "hardware"), ("check", "checks"))]
    memo_h = sum(0.42 + 0.3 * len(items) for _, items in memo) + 0.3
    ASM_H = 3.2   # one picture of the parts in place, before any detail
    axes_h = 0.35
    tagged = [d for d in dims_all if d.get("_tag") and d.get("value") is not None]
    keys = [d for d in tagged if d.get("key")][:5] or tagged[:3]
    key_lines = []
    for d in keys:
        unit = "°" if d.get("unit") == "°" else " mm"
        txt = f"{d['label']}  {fmt(d['value'])}{unit}"
        if "vs" in d:
            diff = d["value"] - d["vs"]
            txt += f"   {d['vs_label']} {fmt(d['vs'])} に対して {'+' if diff >= 0 else ''}{fmt(diff)}"
        key_lines += [(ln, i_ == 0) for i_, ln in enumerate(wrap(txt, 40))]
    KEY_H = (0.45 + 0.34 * len(key_lines)) if key_lines else 0
    pose_names = list((res.get("poses") or {}).keys())
    MOT_H = 3.0 if pose_names else 0.0
    H = head_h + memo_h + KEY_H + ASM_H + MOT_H + 0.6
    fig = plt.figure(figsize=(9, H), dpi=120)

    def y(inch):  # figure fraction from top, in inches
        return 1 - inch / H

    fig.text(0.04, y(0.45), f"{vdir.parent.name}  {vdir.name}", fontsize=20, fontweight="bold")
    overall = res.get("parts_size_mm")
    fig.text(0.04, y(0.95), t("parts", n=n) + ("   " + t("overall" if n == 1 else "overall_n", s=size_text(overall))
                                                if overall else ""), fontsize=13)
    fig.text(0.04, y(1.3), t("conv_v", v=res["user_view"]) if res.get("user_view") else t("conv"),
             fontsize=9.5, color="0.4")
    ch_ = res.get("changes") or {}
    keep = set(ch_.get("unchanged_parts") or []) if ch_.get("vs_printed") else set()
    mins = [(disp(i_["_name"]), i_.get("print_minutes")) for i_ in infos
            if i_.get("print_minutes") and i_["_name"] not in keep]
    if mins:
        def hm(m):
            return f"{m // 60}時間{m % 60:02d}分" if m >= 60 else f"{m}分"
        each = "・".join(f"{n_} {hm(m)}" for n_, m in mins[:4])
        txt = t("ptime_re", t=hm(sum(m for _, m in mins)), each=each, keep="・".join(disp(k) for k in sorted(keep))) \
            if keep else t("ptime", t=hm(sum(m for _, m in mins)), each=each)
        fig.text(0.04, y(1.6), txt, fontsize=10, color="0.25")

    if glob_w:
        fig.text(0.04, y(2.02), t("warn"), fontsize=12, fontweight="bold", color="#c0392b")
        for k, w in enumerate(glob_w):
            fig.text(0.07, y(2.29 + 0.27 * k), w, fontsize=10, color="#c0392b")

    # what to buy and what to check first: the short memo the user takes to the shop
    ym = head_h + 0.05
    fig.add_artist(plt.Line2D([0.03, 0.97], [y(ym)] * 2, color="0.85", lw=1))
    for key, items in memo:
        fig.text(0.04, y(ym + 0.38), t(key), fontsize=13, fontweight="bold")
        ym += 0.42
        for line, first in items:
            fig.text(0.07, y(ym + 0.22), (("・" if JA else "- ") if first else "　") + line, fontsize=11)
            ym += 0.3
    # installed: all parts in colour with the surroundings close to them, from the front and the side
    part_meshes = [trimesh.load(f) for f in files]
    import numpy as np
    plo = np.min([m.bounds[0] for m in part_meshes], axis=0)
    phi = np.max([m.bounds[1] for m in part_meshes], axis=0)
    yk = head_h + memo_h
    if key_lines:
        fig.text(0.04, y(yk + 0.35), t("keyfit"), fontsize=12, fontweight="bold", color="#1f4fe0")
        yk += 0.45
        for line, first in key_lines:
            fig.text(0.06, y(yk + 0.25), (("・" if JA else "- ") if first else "　") + line, fontsize=12,
                     color="#1f4fe0", fontweight="bold" if first else "normal")
            yk += 0.34
    a0 = head_h + memo_h + KEY_H
    fig.text(0.04, y(a0 + 0.3), t("assembled"), fontsize=12, fontweight="bold")
    for col, (a_, b_, ttl) in enumerate(((0, 2, ""), (1, 2, t("assembled_side")))):
        ax = fig.add_axes((0.04 + col * 0.47, y(a0 + ASM_H - 0.1), 0.44, (ASM_H - 0.55) / H))
        cu, cv = (plo[a_] + phi[a_]) / 2, (plo[b_] + phi[b_]) / 2
        half = max(phi[a_] - plo[a_], phi[b_] - plo[b_]) * 0.9 + 25
        for cm in ctx_meshes:
            ax.add_collection(PolyCollection(cm.triangles[:, :, [a_, b_]], facecolors=[(0.84, 0.86, 0.89)],
                                             edgecolors="none", antialiased=False, zorder=0))
        for k_, pm in enumerate(part_meshes):
            ax.add_collection(PolyCollection(pm.triangles[:, :, [a_, b_]], facecolors=[part_color(k_)],
                                             edgecolors=[part_color(k_)], linewidths=0.3, zorder=2))
        ax.set_xlim(cu - half, cu + half)
        ax.set_ylim(cv - half * 0.75, cv + half * 0.75)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        for sp_ in ax.spines.values():
            sp_.set_color("0.8")
        if ttl:
            ax.set_title(ttl, fontsize=9, color="0.4")
    if pose_names:   # one small frame per declared pose: how the moving parts go
        import numpy as np
        m0 = a0 + ASM_H
        fig.text(0.04, y(m0 + 0.3), t("motion"), fontsize=12, fontweight="bold")
        base_p = {f.stem[5:]: trimesh.load(f) for f in files}
        base_c = {f.stem[4:]: trimesh.load(f) for f in sorted(vdir.glob("ctx_*.stl"))}
        shown = [None] + pose_names[:4] if len(pose_names) <= 4 else \
            [None] + [pose_names[int(round(i))] for i in np.linspace(0, len(pose_names) - 1, 4)]
        frames = []
        for pn in shown:
            P_, C_ = dict(base_p), dict(base_c)
            if pn is not None:
                k_ = pose_names.index(pn)
                for f in vdir.glob(f"pose{k_}_part_*.stl"):
                    P_[f.stem.split("_part_", 1)[1]] = trimesh.load(f)
                for f in vdir.glob(f"pose{k_}_ctx_*.stl"):
                    C_[f.stem.split("_ctx_", 1)[1]] = trimesh.load(f)
            frames.append((pn, P_, C_))
        # look along the axis the moving parts move least: the motion shows best across it
        # (a window sash sliding past a fixed stopper moves only context: count that too)
        mv = np.zeros(3)
        moved_c = []
        for pn, P_, C_ in frames[1:]:
            for nm, msh in P_.items():
                mv += np.abs(msh.centroid - base_p[nm].centroid)
            for nm, msh in C_.items():
                if msh is not base_c.get(nm):
                    mv += np.abs(msh.centroid - base_c[nm].centroid)
                    moved_c.append(msh)
        k_ax = int(np.argmin(mv)) if mv.any() else 0
        a_, b_ = [i for i in range(3) if i != k_ax]
        allm = [m for _, P_, C_ in frames for m in list(P_.values())]
        lo_ = np.min([m.bounds[0] for m in allm], axis=0)
        hi_ = np.max([m.bounds[1] for m in allm], axis=0)
        # frame the parts plus the part of any moved surroundings within 150 mm of them, so a
        # small holder on a big door is not a dot and a sliding sash still shows in the frame
        lo0, hi0 = lo_ - 150, hi_ + 150
        for msh in moved_c:
            v_ = msh.vertices[np.all((msh.vertices >= lo0) & (msh.vertices <= hi0), axis=1)]
            if len(v_):
                lo_, hi_ = np.minimum(lo_, v_.min(0)), np.maximum(hi_, v_.max(0))
        cu, cv = (lo_[a_] + hi_[a_]) / 2, (lo_[b_] + hi_[b_]) / 2
        half = max(hi_[a_] - lo_[a_], hi_[b_] - lo_[b_]) * 0.65 + 15
        hits = {pn: {h["a"] for h in (res.get("poses") or {}).get(pn, [])} for pn in pose_names}
        w_ = 0.92 / len(frames)
        for col, (pn, P_, C_) in enumerate(frames):
            ax = fig.add_axes((0.04 + col * w_, y(m0 + MOT_H - 0.1), w_ - 0.02, (MOT_H - 0.75) / H))
            for cm in C_.values():
                ax.add_collection(PolyCollection(cm.triangles[:, :, [a_, b_]], facecolors=[(0.84, 0.86, 0.89)],
                                                 edgecolors="none", antialiased=False, zorder=0))
            for i_, (nm, msh) in enumerate(P_.items()):
                col_ = "#c0392b" if pn is not None and nm in hits.get(pn, set()) else part_color(i_)
                ax.add_collection(PolyCollection(msh.triangles[:, :, [a_, b_]], facecolors=[col_],
                                                 edgecolors=[col_], linewidths=0.3, zorder=2))
            ax.set_xlim(cu - half, cu + half)
            ax.set_ylim(cv - half, cv + half)
            ax.set_aspect("equal")
            ax.set_xticks([])
            ax.set_yticks([])
            for sp_ in ax.spines.values():
                sp_.set_color("0.8")
            ax.set_title(f"{col + 1}. " + (t("pose0") if pn is None else str(pn)), fontsize=9.5, color="0.2")
    fig.text(0.04, y(a0 + ASM_H + MOT_H + 0.35), t("more_pg"), fontsize=9.5, color="0.4")
    fig.savefig(vdir / "sheet.png")
    plt.close(fig)

    # page 2: every part with all its fit dimensions, panels and details
    H = 1.1 + sum(b[3] for b in blocks) + axes_h
    fig = plt.figure(figsize=(9, H), dpi=120)
    fig.text(0.04, y(0.5), t("detail_title", p=vdir.parent.name, v=vdir.name), fontsize=16, fontweight="bold")
    fig.text(0.04, y(0.8), t("origin", o=res["origin"]) if res.get("origin") else t("noorigin"),
             fontsize=9.5, color="0.3")
    VIEWS = (((0, 1), "top", 2), ((0, 2), "front", 1), ((1, 2), "side", 0))  # (plane axes, label, normal axis)
    top = 1.1
    for i, (f, info, (fl, det, il, block_h)) in enumerate(zip(files, infos, blocks)):
        name = info["_name"]
        if fl is None and not il:
            continue
        if fl is None:   # same shape as an earlier part: one line, no drawings
            fig.add_artist(plt.Line2D([0.03, 0.97], [y(top + 0.05)] * 2, color="0.85", lw=1))
            fig.add_artist(plt.Rectangle((0.04, y(top + 0.55)), 0.03, 0.18 / H * 2, color=part_color(i),
                                         transform=fig.transFigure))
            fig.text(0.085, y(top + 0.45), disp(name), fontsize=14, fontweight="bold")
            for q, (ln, *_r) in enumerate(il):
                fig.text(0.05, y(top + 0.9 + 0.32 * q), ln, fontsize=11, color="0.2")
            top += block_h
            continue
        mesh = trimesh.load(f)
        size = info.get("bbox_mm", {}).get("size") or list(mesh.extents)
        c = part_color(i)
        fig.add_artist(plt.Line2D([0.03, 0.97], [y(top + 0.05)] * 2, color="0.85", lw=1))
        fig.add_artist(plt.Rectangle((0.04, y(top + 0.55)), 0.03, 0.18 / H * 2, color=c, transform=fig.transFigure))
        fig.text(0.085, y(top + 0.45), disp(name), fontsize=14, fontweight="bold")
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
            placed = []
            spn = max(size[a_], size[b_], 1.0)
            for d in det:  # small letter at the place of each fit dimension
                pts = d.get("p") or [d.get("at"), d.get("at")]
                mu = (pts[0][a_] + pts[1][a_]) / 2
                mv = (pts[0][b_] + pts[1][b_]) / 2
                while any(abs(mu - pu) < 0.07 * spn and abs(mv - pv) < 0.07 * spn for pu, pv in placed):
                    mu += 0.08 * spn          # do not stack letters on top of each other
                placed.append((mu, mv))
                ax.text(mu, mv, d["_tag"], fontsize=8, fontweight="bold", color="white", ha="center", va="center",
                        zorder=7, bbox=dict(boxstyle="circle,pad=0.2", facecolor="#1f4fe0", edgecolor="none"))
        yy += 0.5 + VIEW_H
        for text, fs, col, bold, ind in il:
            yy += LINE
            fig.text(0.04 + 0.02 * ind, y(yy), text, fontsize=fs, color=col, fontweight="bold" if bold else "normal")
        top += block_h

    fig.add_artist(plt.Line2D([0.03, 0.97], [y(top + 0.05)] * 2, color="0.85", lw=1))
    fig.text(0.04, y(top + 0.3), t("axes"), fontsize=8.5, color="0.5")
    fig.savefig(vdir / "sheet_detail.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
