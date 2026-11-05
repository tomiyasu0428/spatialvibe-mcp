"""Page 3, sheet_build.png: how to print (the 3MF and its settings) and how to put it together,
one numbered picture per assembly step.

Usage: python -m spatialvibe_mcp._steps <version_dir>   (does nothing without `steps` or a plate)
"""
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import trimesh  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402

from spatialvibe_mcp._render import _clip  # noqa: E402
from spatialvibe_mcp._sheet import wrap  # noqa: E402
from spatialvibe_mcp._style import CONTEXT_COLOR, jp_font, part_color  # noqa: E402

FONT = jp_font()
if FONT:
    plt.rcParams["font.family"] = [FONT, "DejaVu Sans"]
NEW = (0.95, 0.55, 0.12)        # what this step adds
HW = (0.35, 0.37, 0.40)         # screws and bolts
HELD = (0.62, 0.78, 0.62)       # the held object (phone, Pi...) once in place


def _view(az=32.0, el=22.0):
    """Orthographic view from the user's side (−Y), a little from the right and above."""
    a, e = np.radians(az), np.radians(el)
    c = np.array([np.sin(a) * np.cos(e), -np.cos(a) * np.cos(e), np.sin(e)])
    f = -c
    r = np.cross(f, [0, 0, 1.0])
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return f, r, u


def _draw(ax, items, view, light):
    """items: [(mesh, rgb, alpha)] painted far-to-near with simple shading."""
    f, r, u = view
    polys, cols, depth = [], [], []
    for m, rgb, alpha in items:
        n = m.face_normals
        front = n @ f < 0.05 if alpha > 0.9 else np.ones(len(n), bool)   # cull back faces of solids
        tri = m.triangles[front]
        shade = 0.55 + 0.45 * np.abs(n[front] @ light)
        q = np.stack([tri @ r, tri @ u], axis=-1)
        polys += list(q)
        cols += [(*(np.array(rgb) * s), alpha) for s in shade]
        depth += list((tri @ f).mean(axis=1))
    order = np.argsort(-np.array(depth))
    ax.add_collection(PolyCollection([polys[i] for i in order], facecolors=[cols[i] for i in order],
                                     edgecolors="none", antialiased=False))


def main():
    vdir = Path(sys.argv[1])
    res = json.loads((vdir / "result.json").read_text(encoding="utf-8"))
    steps, plate, ps = res.get("steps") or [], res.get("plate"), res.get("print_settings") or {}
    if not steps and not ps:   # page 3 only when the script describes printing or assembly
        return
    labels = res.get("labels") or {}

    def disp(n):
        return labels.get(n, n)

    parts = {f.stem[5:]: trimesh.load(f) for f in sorted(vdir.glob("part_*.stl"))}
    ctx = {f.stem[4:]: trimesh.load(f) for f in sorted(vdir.glob("ctx_*.stl"))}
    order = list(parts)
    named = {n for st in steps for n in st["add"]}
    always = [n for n in ctx if n not in named and not n.startswith("hw_")]

    # header: printing
    lines = [("印刷：印刷を担当する AI に「print_job.json を読んで印刷を準備して」と頼む"
              "（ファイル・向き・設定・合わせる寸法が全部入っています）。始める前に確認が来ます", 10.5, "0.1")]
    if plate and not plate.get("fits_one_bed", True):
        lines.append(("  ※ 1枚に入りきらないので、はみ出した部品は別に刷る", 10, "#c0392b"))
    mins = [(disp(n), (res["parts"].get(n) or {}).get("print_minutes")) for n in order]
    mins = [(n, m) for n, m in mins if m]
    if ps or mins:
        def hm(m):
            return f"{m // 60}時間{m % 60:02d}分" if m >= 60 else f"{m}分"
        s_ = "手で刷るとき："
        if ps:
            s_ += f"{plate['file'] if plate else 'STL'} を開く・{ps.get('material', 'PETG')}"
            if ps.get("infill") is not None:
                s_ += f"・充填 {ps['infill']}%"
            sup = ps.get("supports") or []
            s_ += "・サポート " + ("「" + "」「".join(disp(n) for n in sup) + "」だけ" if sup else "なし")
        if mins:
            s_ += f"・目安 約 {hm(sum(m for _, m in mins))}"
        lines.append((s_, 10, "0.35"))
    wrapped = [(ln, fs, c) for txt, fs, c in lines for ln in wrap(txt, 44)]

    cols_n = 2
    rows = (len(steps) + cols_n - 1) // cols_n
    PANEL_H = 3.9
    head = 1.0 + 0.32 * len(wrapped) + (0.6 if steps else 0)
    H = head + rows * PANEL_H + 0.4
    fig = plt.figure(figsize=(9, H), dpi=120)

    def y(inch):
        return 1 - inch / H

    fig.text(0.04, y(0.5), f"{vdir.parent.name}  {vdir.name}  印刷と取り付け（3 枚目）", fontsize=16, fontweight="bold")
    for k, (ln, fs, c) in enumerate(wrapped):
        fig.text(0.05, y(0.95 + 0.32 * k), ln, fontsize=fs, color=c)
    if not steps:
        fig.savefig(vdir / "sheet_build.png")
        return
    fig.text(0.04, y(head - 0.2), "取り付けの手順（オレンジ＝その手順で付けるもの）", fontsize=12, fontweight="bold")

    view = _view()
    light = -view[0] + np.array([0.3, 0.0, 0.6])
    light /= np.linalg.norm(light)
    # frame: everything the steps use (parts, bolts, held object) and where they come from
    pts = []
    for st in steps:
        for n in set(st["add"]) | set(st["from"]) | set(st.get("at") or {}):
            m = parts.get(n) or ctx.get(n)
            a_ = np.array((st.get("at") or {}).get(n, (0, 0, 0)))
            f_ = np.array(st["from"].get(n, (0, 0, 0)))
            for off in (a_, a_ + f_):
                pts += [m.bounds[0] + off, m.bounds[1] + off]
    pts = np.array(pts) if pts else np.array([m.bounds[i] for m in parts.values() for i in (0, 1)])
    lo, hi = pts.min(0), pts.max(0)
    pad = max((hi - lo).max() * 0.25, 15.0)
    clipped = {n: _clip(ctx[n], lo - pad, hi + pad) for n in always}
    corners = np.array([[a, b, c] for a in (lo[0], hi[0]) for b in (lo[1], hi[1]) for c in (lo[2], hi[2])])
    q_ = np.stack([corners @ view[1], corners @ view[2]], -1)
    (x0, y0), (x1, y1) = q_.min(0), q_.max(0)
    half = max(x1 - x0, y1 - y0) / 2 * 1.12 + 8
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2

    shown = []
    for k, st in enumerate(steps):
        r_, c_ = divmod(k, cols_n)
        top = head + r_ * PANEL_H
        ax = fig.add_axes((0.04 + c_ * 0.47, y(top + PANEL_H - 0.15), 0.44, (PANEL_H - 0.95) / H))
        items = [(m, CONTEXT_COLOR, 0.35) for m in clipped.values() if m is not None]
        at = st.get("at") or {}
        active = list(dict.fromkeys(list(st["add"]) + list(st["from"]) + list(at)))
        arrows = []
        for n in list(dict.fromkeys(shown + active)):
            m = (parts.get(n) or ctx.get(n)).copy()
            a_ = np.array(at.get(n, (0, 0, 0)))
            d = np.array(st["from"].get(n, (0, 0, 0)))
            if d.any() and not any(np.allclose(d, d_) for *_, d_ in arrows):   # one arrow per motion
                arrows.append((m.centroid + a_ + d, m.centroid + a_, d))
            m.apply_translation(a_ + d)
            if n in active:
                col = HW if n.startswith("hw_") else NEW if n in st["add"] or n in parts else HELD
            else:
                base_ = part_color(order.index(n)) if n in parts else HW if n.startswith("hw_") else HELD
                col = tuple(0.55 + 0.45 * np.array(base_))
            items.append((m, col, 1.0))
        _draw(ax, items, view, light)
        for a, b, _ in arrows:
            pa = (a @ view[1], a @ view[2])
            pb = (b @ view[1], b @ view[2])
            ax.annotate("", xy=pb, xytext=pa, arrowprops=dict(arrowstyle="-|>", color="#c0392b", lw=2.2))
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        for sp_ in ax.spines.values():
            sp_.set_color("0.85")
        txt = wrap(f"{k + 1}. {st['text']}", 24)
        for j, ln in enumerate(txt[:3]):
            fig.text(0.04 + c_ * 0.47, y(top + 0.25 + 0.27 * j), ln, fontsize=11,
                     fontweight="bold" if j == 0 else "normal")
        shown += [n for n in st["add"] if n not in shown]
    fig.savefig(vdir / "sheet_build.png")
    plt.close(fig)


if __name__ == "__main__":
    main()
