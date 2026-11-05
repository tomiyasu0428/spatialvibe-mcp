"""Runs one model script in a child process and exports its parts.

Usage: python -m spatialvibe_mcp._runner <code.py> <out_dir> <result.json>
The script must define `parts` (dict name -> build123d Shape, the things to print) and may
define `context` (dict name -> Shape, surroundings shown translucent, never printed).
The result is written to <result.json> (not stdout), so whatever the script prints cannot be
mistaken for it. The server only trusts that file together with a zero exit code.
"""
import json
import math
import os
import re
import runpy
import sys
import traceback
from pathlib import Path

NAME = re.compile(r"[A-Za-z0-9_-]{1,40}")
RESULT = None  # path of the result file, set in main() before the user script runs


def write_result(obj):
    Path(RESULT).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def fail(msg):
    write_result({"ok": False, "error": msg})
    sys.exit(0)


def as_dict(obj, label):
    if obj is None:
        return {}
    if not isinstance(obj, dict):
        obj = {label: obj}
    for k, v in obj.items():
        if not isinstance(k, str) or not NAME.fullmatch(k):
            fail(f"{label}: name {k!r} must be 1-40 ASCII letters, digits, _ or - (e.g. 'spoon_front'); "
                 "Japanese names are not allowed")
        if not hasattr(v, "wrapped") or not hasattr(v, "bounding_box"):
            fail(f"{label}[{k!r}] is a {type(v).__name__}, not a shape (did a comment or a missing "
                 "`*` drop the shape, e.g. `Pos(...)` without `* Box(...)`?)")
    return obj


def bbox(shape):
    b = shape.bounding_box()
    return {"size": [round(b.size.X, 2), round(b.size.Y, 2), round(b.size.Z, 2)],
            "min": [round(b.min.X, 2), round(b.min.Y, 2), round(b.min.Z, 2)],
            "max": [round(b.max.X, 2), round(b.max.Y, 2), round(b.max.Z, 2)]}


def _axis_name(d):
    for name, i in (("X", 0), ("Y", 1), ("Z", 2)):
        if abs(abs(d[i]) - 1) < 1e-6:
            return name
    return "other"


def hole_list(shape):
    """Round holes and cut-outs, one entry per axis line:
    [{"d": mm, "axis": "X|Y|Z|other", "at": [x, y, z], "half": bool}].

    Built from cylindrical faces whose normal points toward their axis (bores, bolt holes). Faces
    on the same axis with the same diameter are one hole even when a nut pocket splits it. `at` is
    the middle of the hole along its axis. half=True: the cut-out does not go all the way round
    (split-clamp bore, slot end). Bosses and small arcs (fillets) are left out. The radius and axis
    come from the OCCT surface, so trimmed cylinders are not dropped.
    """
    from build123d import GeomType
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools

    groups = {}
    for f in shape.faces().filter_by(GeomType.CYLINDER):
        try:
            cyl = BRepAdaptor_Surface(f.wrapped).Cylinder()
            r = cyl.Radius()
            loc, dr = cyl.Axis().Location(), cyl.Axis().Direction()
            o = (loc.X(), loc.Y(), loc.Z())
            d = [dr.X(), dr.Y(), dr.Z()]
            k = next(i for i in range(3) if abs(d[i]) > 1e-9)
            flip = d[k] < 0
            if flip:
                d = [-x for x in d]
            c = f.center()
            oc = (c.X - o[0], c.Y - o[1], c.Z - o[2])
            t = sum(a * b for a, b in zip(oc, d))
            radial = [oc[i] - d[i] * t for i in range(3)]
            n = f.normal_at(c)
            if n.X * radial[0] + n.Y * radial[1] + n.Z * radial[2] >= 0:
                continue  # outer surface: boss, round bar
            # u = angle around the axis, v = position along it (on the surface's own axis)
            umin, umax, vmin, vmax = BRepTools.UVBounds_s(f.wrapped)
            ts = [-vmax, -vmin] if flip else [vmin, vmax]
            # how far round it goes: a nut slot cutting a window into a bolt hole does not make
            # it "half", but a split-clamp bore (180°) or a slot end does
            cover = min(1.0, (umax - umin) / (2 * math.pi))
            if ts[1] - ts[0] <= 0:
                continue
        except Exception:
            continue
        # the axis line: the point on it closest to the origin, plus the direction
        t0 = sum(a * b for a, b in zip(o, d))
        foot = tuple(round(o[i] - d[i] * t0, 1) for i in range(3))
        key = (round(2 * r, 1), foot, tuple(round(x, 3) for x in d))
        base = sum(o[i] * d[i] for i in range(3))
        rn = math.sqrt(sum(x * x for x in radial)) or 1.0
        closed = tuple(x / rn * cover for x in radial)  # toward the solid side of an arc, weighted
        groups.setdefault(key, []).append((base + min(ts), base + max(ts), cover, closed))
    out = []
    for (dia, foot, d), segs in groups.items():
        # segments on one axis are one hole only when they are close (a nut pocket or counterbore
        # splitting a bolt hole); two clamps far apart on the same pipe axis stay two holes.
        # Faces side by side around the axis (a bore split at its seam) add up their angle.
        segs.sort()
        gap_max = max(1.5 * dia, 6.0)
        runs = []
        for lo, hi, cover, closed in segs:
            if runs and lo - runs[-1]["hi"] <= gap_max:
                r_ = runs[-1]
                if lo < r_["hi"] - 1e-6:            # overlaps along the axis: side by side → angles add
                    r_["stack"] += cover
                else:
                    r_["stack"] = cover
                r_["cover"] = max(r_["cover"], r_["stack"])
                r_["hi"] = max(r_["hi"], hi)
                r_["closed"] = [a + b for a, b in zip(r_["closed"], closed)]
            else:
                runs.append({"lo": lo, "hi": hi, "cover": cover, "stack": cover, "closed": list(closed)})
        for r_ in runs:
            cover = min(1.0, r_["cover"])
            if cover < 0.45:
                continue  # fillet or small arc
            mid = (r_["lo"] + r_["hi"]) / 2
            at = [round(foot[i] + d[i] * mid, 1) for i in range(3)]
            cn = math.sqrt(sum(x * x for x in r_["closed"])) or 1.0
            out.append({"d": dia, "axis": _axis_name(d), "at": at, "half": cover < 0.95,
                        "_closed": tuple(x / cn for x in r_["closed"]), "_dir": d, "_foot": foot,
                        "_lo": r_["lo"], "_hi": r_["hi"]})
    out = _merge_counterbores(out, _countersinks(shape))
    out = _pair_slots(out)
    for h in out:
        for k in ("_closed", "_dir", "_foot", "_lo", "_hi"):
            h.pop(k, None)
    out.sort(key=lambda h: (h.get("kind", "hole"), h["d"], h["axis"], h["at"]))
    return out


def _countersinks(shape):
    """Cone faces (countersinks): [(foot, dir, max diameter, lo, hi)] on their axis line."""
    from build123d import GeomType
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    out = []
    for f in shape.faces().filter_by(GeomType.CONE):
        try:
            ax = BRepAdaptor_Surface(f.wrapped).Cone().Axis()
            o = (ax.Location().X(), ax.Location().Y(), ax.Location().Z())
            d = [ax.Direction().X(), ax.Direction().Y(), ax.Direction().Z()]
            k = next(i for i in range(3) if abs(d[i]) > 1e-9)
            if d[k] < 0:
                d = [-x for x in d]
            t0 = sum(a * b for a, b in zip(o, d))
            foot = tuple(round(o[i] - d[i] * t0, 1) for i in range(3))
            rmax, ts = 0.0, []
            for v in f.vertices():
                c = v.center()
                q = (c.X - foot[0], c.Y - foot[1], c.Z - foot[2])
                t = sum(q[i] * d[i] for i in range(3))
                ts.append(t)
                rmax = max(rmax, math.sqrt(max(0.0, sum(x * x for x in q) - t * t)))
            if ts:
                out.append((foot, tuple(round(x, 3) for x in d), round(2 * rmax, 1), min(ts), max(ts)))
        except Exception:
            continue
    return out


def _merge_counterbores(hl, csks):
    """A bigger coaxial bore right next to a hole is its counterbore; a cone is its countersink.
    The hole keeps the smaller diameter and its own centre; the extra feature is described on it."""
    def same_axis(a, b):
        return a["_dir"] == b["_dir"] and all(abs(x - y) < 0.15 for x, y in zip(a["_foot"], b["_foot"]))
    full = sorted([h for h in hl if not h["half"]], key=lambda h: h["d"])
    absorbed = set()
    for i, h in enumerate(full):
        if id(h) in absorbed:
            continue
        for big in full[i + 1:]:
            if id(big) in absorbed or big["d"] <= h["d"] or not same_axis(h, big):
                continue
            if big["_lo"] > h["_hi"] + 0.5 or big["_hi"] < h["_lo"] - 0.5:
                continue  # not touching: a separate hole on the same line
            h["counterbore"] = {"d": big["d"], "depth": round(big["_hi"] - big["_lo"], 1)}
            absorbed.add(id(big))
            break
        for foot, d, dmax, lo, hi in csks:
            if d == tuple(h["_dir"]) and all(abs(x - y) < 0.15 for x, y in zip(foot, h["_foot"])):
                h["countersink"] = {"d": dmax}
                break
    return [h for h in hl if id(h) not in absorbed]


def _pair_slots(hl):
    """Two half-round ends that face each other on parallel axes are one slot (長穴)."""
    arcs = [h for h in hl if h["half"]]
    used, slots = set(), []
    for i, a in enumerate(arcs):
        if i in used:
            continue
        best = None
        for j in range(i + 1, len(arcs)):
            b = arcs[j]
            if j in used or b["d"] != a["d"] or b["_dir"] != a["_dir"]:
                continue
            v = [b["at"][k] - a["at"][k] for k in range(3)]
            along = sum(v[k] * a["_dir"][k] for k in range(3))
            perp = [v[k] - a["_dir"][k] * along for k in range(3)]
            dist = math.sqrt(sum(x * x for x in perp))
            if dist < 1e-6 or abs(along) > a["d"]:
                continue
            u = [x / dist for x in perp]
            # a's solid side points away from b, and b's away from a
            if sum(a["_closed"][k] * u[k] for k in range(3)) < -0.7 and sum(b["_closed"][k] * u[k] for k in range(3)) > 0.7:
                if best is None or dist < best[1]:
                    best = (j, dist)
        if best:
            j, dist = best
            b = arcs[j]
            used.update((i, j))
            mid = [round((a["at"][k] + b["at"][k]) / 2, 1) for k in range(3)]
            slots.append({"d": a["d"], "axis": a["axis"], "at": mid, "half": False, "kind": "slot",
                          "length": round(dist + a["d"], 1)})
    keep = [h for h in hl if not h["half"]] + [a for k, a in enumerate(arcs) if k not in used]
    return keep + slots


# ---------------------------------------------------------------- measured dimensions
AXES = {"X": (1.0, 0.0, 0.0), "Y": (0.0, 1.0, 0.0), "Z": (0.0, 0.0, 1.0)}


def hole_spacing(hl):
    """Centre-to-centre spacing of holes with the same diameter and axis, along each other axis.
    [{"d": 3.5, "axis": "Y", "along": {"X": [98.0], "Z": [62.0]}}] — the numbers a tape checks."""
    groups = {}
    for h in hl:
        if h["axis"] in AXES:
            kind = h.get("kind") or ("arc" if h.get("half") else "hole")
            groups.setdefault((h["d"], h["axis"], kind), []).append(h["at"])
    out = []
    for (d, axis, kind), pts in sorted(groups.items()):
        if len(pts) < 2:
            continue
        along = {}
        for name, i in (("X", 0), ("Y", 1), ("Z", 2)):
            if name == axis:
                continue
            vals = sorted({round(p[i], 1) for p in pts})
            steps = [round(b - a, 1) for a, b in zip(vals, vals[1:]) if b - a > 0.05]
            if steps:
                along[name] = steps
        if along:
            out.append({"d": d, "axis": axis, "kind": kind, "along": along})
    return out


def _vec(p, label):
    if not isinstance(p, (list, tuple)) or len(p) != 3 or not all(isinstance(x, (int, float)) for x in p):
        raise ValueError(f"{label} must be a point (x, y, z) in mm")
    return tuple(float(x) for x in p)


def _crossings(shape, p, axis):
    """Material intervals [(t0, t1)] along the line p + t*axis (t in mm)."""
    from build123d import Vector
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt
    it = IntCurvesFace_ShapeIntersector()
    it.Load(shape.wrapped, 1e-6)
    it.Perform(gp_Lin(gp_Pnt(*p), gp_Dir(*axis)), -1e5, 1e5)
    ws = sorted({round(it.WParameter(i), 6) for i in range(1, it.NbPnt() + 1)})
    spans = []
    for a, b in zip(ws, ws[1:]):
        m = (a + b) / 2
        if shape.is_inside(Vector(*(p[i] + axis[i] * m for i in range(3)))):
            spans.append((a, b))
    return spans


def _axis(v, label="axis"):
    """'X' / 'Y' / 'Z' or a direction (x, y, z) -> unit vector."""
    if isinstance(v, str) and v in AXES:
        return AXES[v]
    if isinstance(v, (list, tuple)) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v):
        n = math.sqrt(sum(x * x for x in v))
        if n > 1e-9:
            return tuple(x / n for x in v)
    raise ValueError(f'{label} must be "X", "Y", "Z" or a direction (x, y, z)')


def _snap_hole(p, hl):
    """The point on the nearest hole's axis line, level with p (so a point typed on a face snaps to
    the hole centre in that face). Returns (point, index in the hole list, hole)."""
    best = None
    for k, h in enumerate(hl):
        ax = AXES.get(h["axis"])
        c = h["at"]
        if ax:
            t = sum((p[i] - c[i]) * ax[i] for i in range(3))
            foot = tuple(c[i] + ax[i] * t for i in range(3))
        else:
            foot = tuple(c)
        d2 = sum((p[i] - foot[i]) ** 2 for i in range(3))
        if best is None or d2 < best[0]:
            best = (d2, foot, k, h)
    if best is None or best[0] > 12.0 ** 2:
        raise ValueError(f"no hole axis within 12 mm of {p}")
    return best[1], best[2], best[3]


def _snap_face(p, shp):
    """The nearest point on the part's surface (a wall, the floor, a rim)."""
    from build123d import Vector, Vertex
    q = Vector(*p)
    f = min(shp.faces(), key=lambda f_: f_.distance_to(q))
    a, _ = f.closest_points(Vertex(*p))
    if math.dist((a.X, a.Y, a.Z), p) > 10.0:
        raise ValueError(f"no surface within 10 mm of {p}")
    return (a.X, a.Y, a.Z)


def _end(d, key, shp, hl, ctx_shapes):
    """One end of a distance: a typed point, snapped to a hole centre or to a surface."""
    p = _vec(d.get(key), key)
    how = d.get(f"snap_{key}", d.get("snap"))
    if how == "hole":
        q, k, h = _snap_hole(p, hl)
        return q, f"穴{k + 1}"
    if how == "face":
        return _snap_face(p, shp), "面"
    if isinstance(how, str) and how.startswith("context:"):
        c = how.split(":", 1)[1]
        if c not in ctx_shapes:
            raise ValueError(f"context {c!r} not found")
        return _snap_face(p, ctx_shapes[c]), c
    if how not in (None, "point"):
        raise ValueError('snap must be "hole", "face", "context:<name>" or "point"')
    return p, None   # typed coordinate: not measured on the shape


def measure_dims(spec, parts, context, holes_by_part):
    """Measure the fit dimensions the script asks for, on the real shapes.

    Each entry: {"label": str, "part": name, "kind": ..., "expect"?: number, "tol"?: number}
      distance : ends "a", "b"; snap each with "snap_a"/"snap_b" (or "snap" for both):
                 "hole" = that hole's centre, "face" = the part's nearest surface,
                 "context:<name>" = that context item's nearest surface; "axis" ("X"/"Y"/"Z"
                 or a direction) measures only along it. Unsnapped ends are typed coordinates and
                 are marked as such.
      gap      : "at" a point in the empty space, "axis": the empty width there (slot mouth,
                 inner size). Add "narrowest": [dx, dy, dz] to slide the line that far and keep the
                 smallest width (finds a snap-fit mouth without exact coordinates).
      thickness: "at" a point inside the material, "axis": the material thickness there
      diameter : "at" a point near a hole: that hole's diameter
      size     : "axis": the part's overall size along it
      overhang : "to": context name, "axis", "side": "+" or "-": how far the part sticks out past it
      angle    : "a", "b" points on two faces (angle between them); or "a" and "ref": "Z" (tilt
                 from level; "X"/"Y": from a vertical plane)
      clearance: "to": context name: the smallest distance between the part and it. With
                 "expect" it also says the gap is intended, so no "すき間が … しかない" warning.
    Any entry may add "vs": the real object's size and "vs_label": its name (e.g. vs 25.4,
    vs_label "パイプ"), shown next to the part's value with the difference.
    Returns ([measured...], [warnings...]). Values come from the geometry, never from the script.
    """
    out, warns = [], []
    if not spec:
        return out, warns
    if not isinstance(spec, (list, tuple)):
        raise ValueError("dims must be a list of dicts")
    for k, d in enumerate(spec[:30]):
        label = str(d.get("label", f"dim{k + 1}")) if isinstance(d, dict) else f"dim{k + 1}"
        try:
            if not isinstance(d, dict):
                raise ValueError("each dims entry must be a dict")
            name, kind = d.get("part"), d.get("kind")
            if name not in parts:
                raise ValueError(f"part {name!r} not in parts")
            shp, hl = parts[name], holes_by_part[name]
            m = {"label": label, "part": name, "kind": kind, "measured": True}
            if kind == "distance":
                (a, fa), (b, fb) = _end(d, "a", shp, hl, context), _end(d, "b", shp, hl, context)
                if d.get("axis") is not None:
                    ax = _axis(d["axis"])
                    t = sum((b[i] - a[i]) * ax[i] for i in range(3))
                    val, b = abs(t), tuple(a[i] + ax[i] * t for i in range(3))
                else:
                    val = math.dist(a, b)
                m.update(value=round(val, 2), unit="mm", p=[list(a), list(b)], ends=[fa, fb],
                         measured=fa is not None and fb is not None)
            elif kind in ("gap", "thickness"):
                at = _vec(d.get("at"), "at")
                ax = _axis(d.get("axis"))
                probes = [at]
                if kind == "gap" and d.get("narrowest") is not None:
                    span = _vec(d["narrowest"], "narrowest")
                    probes = [tuple(at[i] + span[i] * j / 20 for i in range(3)) for j in range(21)]
                best = None
                for q in probes:
                    spans = _crossings(shp, q, ax)
                    if kind == "thickness":
                        hit = [s_ for s_ in spans if s_[0] - 1e-6 <= 0 <= s_[1] + 1e-6]
                        if not hit:
                            raise ValueError(f"{q} is not inside the material of {name}")
                        t0, t1 = hit[0]
                    else:
                        if any(s_[0] < 0 < s_[1] for s_ in spans):
                            if len(probes) > 1:
                                continue
                            raise ValueError(f"{q} is inside the material of {name}: there is no gap there "
                                             "(was the cut made where you intended?)")
                        before = [s_[1] for s_ in spans if s_[1] <= 1e-6]
                        after = [s_[0] for s_ in spans if s_[0] >= -1e-6]
                        if not before or not after:
                            if len(probes) > 1:
                                continue
                            raise ValueError(f"the gap at {q} is open on one side "
                                             "(for a depth use distance with snap 'face' on both ends)")
                        t0, t1 = max(before), min(after)
                    if best is None or t1 - t0 < best[0]:
                        best = (t1 - t0, q, t0, t1)
                if best is None:
                    raise ValueError(f"no closed gap found along the 'narrowest' sweep from {at}")
                _, q, t0, t1 = best
                pa = [q[i] + ax[i] * t0 for i in range(3)]
                pb = [q[i] + ax[i] * t1 for i in range(3)]
                m.update(value=round(t1 - t0, 2), unit="mm", p=[pa, pb])
            elif kind == "diameter":
                _, idx, h = _snap_hole(_vec(d.get("at"), "at"), hl)
                c, ax = h["at"], AXES.get(h["axis"], (0.0, 0.0, 1.0))
                u = next(v for v in AXES.values() if v != ax)
                r = h["d"] / 2
                m.update(value=h["d"], unit="mm", ends=[f"穴{idx + 1}", f"穴{idx + 1}"], at=c,
                         p=[[c[i] - u[i] * r for i in range(3)], [c[i] + u[i] * r for i in range(3)]])
            elif kind == "size":
                ax = _axis(d.get("axis"))
                bb = shp.bounding_box()
                lo = (bb.min.X, bb.min.Y, bb.min.Z)
                hi = (bb.max.X, bb.max.Y, bb.max.Z)
                if ax not in AXES.values():
                    raise ValueError('size needs "axis": "X", "Y" or "Z"')
                i = list(AXES.values()).index(ax)
                pa, pb = list(lo), list(lo)
                pb[i] = hi[i]
                m.update(value=round(hi[i] - lo[i], 2), unit="mm", p=[pa, pb])
            elif kind == "overhang":
                to, ax = d.get("to"), _axis(d.get("axis"))
                if to not in context:
                    raise ValueError(f"context {to!r} not found")
                if ax not in AXES.values():
                    raise ValueError('overhang needs "axis": "X", "Y" or "Z"')
                i = list(AXES.values()).index(ax)
                pb_, cb_ = shp.bounding_box(), context[to].bounding_box()
                pmin, pmax = (pb_.min.X, pb_.min.Y, pb_.min.Z)[i], (pb_.max.X, pb_.max.Y, pb_.max.Z)[i]
                cmin, cmax = (cb_.min.X, cb_.min.Y, cb_.min.Z)[i], (cb_.max.X, cb_.max.Y, cb_.max.Z)[i]
                side = d.get("side", "+")
                val = (pmax - cmax) if side == "+" else (cmin - pmin)
                c = pb_.center()
                pa, pb = [c.X, c.Y, c.Z], [c.X, c.Y, c.Z]
                pa[i], pb[i] = (cmax, pmax) if side == "+" else (cmin, pmin)
                m.update(value=round(val, 2), unit="mm", p=[pa, pb])
            elif kind == "angle":
                from build123d import Vector
                ns, pts = [], []
                keys = ("a",) if d.get("ref") is not None else ("a", "b")
                for key in keys:
                    q = Vector(*_vec(d.get(key), key))
                    f = min(shp.faces(), key=lambda f_: f_.distance_to(q))
                    ns.append(f.normal_at(q))
                    pts.append([q.X, q.Y, q.Z])
                if d.get("ref") is not None:  # tilt of face a from the plane square to that axis
                    ns.append(Vector(*_axis(d["ref"], "ref")))
                cosv = abs(ns[0].dot(ns[1])) / (ns[0].length * ns[1].length)
                n = ns[0].cross(ns[1])
                if n.length > 1e-3:   # look along the line where the two faces meet
                    view = max(range(3), key=lambda i: abs((n.X, n.Y, n.Z)[i]))
                else:                 # parallel faces: look from the side so the face is seen edge-on
                    f0 = (ns[0].X, ns[0].Y, ns[0].Z)
                    view = min(range(3), key=lambda i: abs(f0[i]))
                m.update(value=round(math.degrees(math.acos(min(1.0, cosv))), 2), unit="°", at=pts[0],
                         view_normal="XYZ"[view])
            elif kind == "clearance":
                to = d.get("to")
                if to not in context:
                    raise ValueError(f"context {to!r} not found")
                dist, pa, pb = shp.distance_to_with_closest_points(context[to])
                m.update(value=round(dist, 2), unit="mm", to=to,
                         p=[[pa.X, pa.Y, pa.Z], [pb.X, pb.Y, pb.Z]] if dist > 1e-6 else None)
            else:
                raise ValueError('kind must be distance, gap, thickness, diameter, size, overhang, angle or clearance')
            if isinstance(d.get("vs"), (int, float)):  # the real object's size, shown next to the part's
                m["vs"] = float(d["vs"])
                m["vs_label"] = str(d.get("vs_label", "実物"))[:20]
            exp = d.get("expect")
            if isinstance(exp, (int, float)):
                tol = float(d.get("tol", 0.3))
                m["expect"], m["ok"] = float(exp), abs(m["value"] - float(exp)) <= tol
                if not m["ok"]:
                    warns.append(f"{name}: 「{label}」を測ると {m['value']} {m['unit']}（予定 {exp}）")
            if not m["measured"]:
                m["note"] = "typed coordinates"
            out.append(m)
        except Exception as e:
            out.append({"label": label, "part": d.get("part") if isinstance(d, dict) else None,
                        "kind": d.get("kind") if isinstance(d, dict) else None, "value": None, "error": str(e)[:200]})
            warns.append(f"「{label}」を測れない: {str(e)[:120]}")
    return out, warns


def clearances(parts, context):
    """Smallest distance from each part to each context item (0 = touching or overlapping)."""
    out = []
    for a, shp in parts.items():
        for c, ctx in context.items():
            try:
                out.append({"part": a, "to": c, "mm": round(shp.distance_to(ctx), 2)})
            except Exception:
                out.append({"part": a, "to": c, "mm": None})
    return out


def summarize(hl):
    counts = {}
    for h in hl:
        key = (h["d"], h["half"], h.get("length"))
        counts[key] = counts.get(key, 0) + 1
    out = []
    for (d, half, length), n in sorted(counts.items(), key=lambda kv: (kv[0][2] is not None, kv[0][0], kv[0][1])):
        e = {"d": d, "n": n, "half": half}
        if length is not None:
            e["slot_length"] = length
        out.append(e)
    return out


def mesh_check(stl_path):
    """Is the exported STL closed? Returns (watertight, open_edges)."""
    import trimesh
    from trimesh.grouping import group_rows
    m = trimesh.load(str(stl_path), force="mesh")
    m.merge_vertices()
    open_edges = len(group_rows(m.edges_sorted, require_count=1))
    return bool(m.is_watertight), open_edges


DOWN = {"-Z": (0, 0, 0), "+Z": (180, 0, 0), "Z": (180, 0, 0), "-X": (0, -90, 0), "+X": (0, 90, 0),
        "X": (0, 90, 0), "-Y": (90, 0, 0), "+Y": (-90, 0, 0), "Y": (-90, 0, 0)}


def pose_of(spec):
    """print_pose value -> a Location: a build123d Rot/Location, or "-X" = the face looking toward -X
    goes on the bed (also "+Y", "-Z", ...)."""
    from build123d import Rot
    if isinstance(spec, str):
        if spec.strip() not in DOWN:
            raise ValueError(f'print_pose {spec!r}: use "-X", "+X", "-Y", "+Y", "-Z" or "+Z" (the face that goes down)')
        return Rot(*DOWN[spec.strip()])
    return spec


def down_face(loc):
    """Which side of the part (as modelled) faces the bed in the print pose."""
    from build123d import Vertex
    o = (loc * Vertex(0, 0, 0)).center()
    for name, n in (("-X", (-1, 0, 0)), ("+X", (1, 0, 0)), ("-Y", (0, -1, 0)), ("+Y", (0, 1, 0)),
                    ("-Z", (0, 0, -1)), ("+Z", (0, 0, 1))):
        v = (loc * Vertex(*n)).center() - o
        if v.Z < -0.99:
            return name
    return "tilted"


def bed_size():
    raw = os.environ.get("SPATIALVIBE_BED", "256,256,256")
    try:
        b = [float(x) for x in raw.split(",")]
        return b if len(b) == 3 else [256.0] * 3
    except ValueError:
        return [256.0] * 3


def fits_bed(size, bed):
    """Fits in some axis-aligned orientation (largest side against the largest bed side)."""
    return all(a <= b for a, b in zip(sorted(size), sorted(bed)))


def text_list(obj, label):
    if obj is None:
        return []
    if isinstance(obj, str) or not isinstance(obj, (list, tuple)):
        fail(f"{label} must be a list of short strings, e.g. ['M5×30 ボルト・ナット 6組']")
    return [str(x) for x in obj][:20]


def main():
    global RESULT
    code_path, out, RESULT = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    sys.argv = [str(code_path)]  # the script must not see the runner's arguments
    try:
        ns = runpy.run_path(str(code_path), run_name="__main__")
    except SystemExit:
        fail("script called exit()")
    except Exception:
        fail(traceback.format_exc(limit=6))

    from build123d import export_step, export_stl

    parts = as_dict(ns.get("parts"), "parts")
    context = as_dict(ns.get("context"), "context")
    if not parts:
        fail("define `parts = {'name': shape, ...}` (the things to print)")

    bed = bed_size()
    origin = ns.get("origin")
    print_pose = ns.get("print_pose") or {}
    if not isinstance(print_pose, dict):
        fail("print_pose must be a dict: {'part name': Rot(...) or Location(...)} (how to lay it on the bed)")
    result = {"ok": True, "parts": {}, "context": {}, "interference": [], "interference_unchecked": [],
              "near_contact": [], "warnings": [], "origin": str(origin)[:120] if origin else None,
              "hardware": text_list(ns.get("hardware"), "hardware"),
              "checks": text_list(ns.get("checks"), "checks"), "bed_mm": bed}
    warn = result["warnings"]
    for name, shp in parts.items():
        stl = out / f"part_{name}.stl"
        export_stl(shp, str(stl))
        export_step(shp, str(out / f"part_{name}.step"))
        hl = hole_list(shp)
        info = {
            "valid": bool(shp.is_valid),
            "solids": len(shp.solids()),
            "volume_cm3": round(shp.volume / 1000, 2),
            "bbox_mm": bbox(shp),
            "holes": summarize(hl),
            "hole_list": hl,
        }
        info["hole_spacing"] = hole_spacing(hl)
        info["fits_bed"] = fits_bed(info["bbox_mm"]["size"], bed)
        if name in print_pose:
            try:
                pose = pose_of(print_pose[name])
                pp = pose * shp
                info["print_down"] = down_face(pose)
                pb = pp.bounding_box()
                export_stl(pp, str(out / f"print_{name}.stl"))
                info["print_size_mm"] = [round(pb.size.X, 2), round(pb.size.Y, 2), round(pb.size.Z, 2)]
                info["fits_bed"] = fits_bed(info["print_size_mm"], bed)
            except Exception as e:
                warn.append(f"{name}: print_pose を使えない: {type(e).__name__}: {str(e)[:80]}")
        try:
            info["watertight"], info["open_edges"] = mesh_check(stl)
        except Exception as e:  # never report "closed" when the check itself failed
            info["watertight"], info["open_edges"] = None, None
            warn.append(f"{name}: STL の閉じ具合を確認できない（未判定）: {type(e).__name__}")
        if not info["valid"]:
            warn.append(f"{name}: 形が壊れている（valid=false）")
        if info["solids"] != 1:
            warn.append(f"{name}: {info['solids']} 個の塊に分かれている（つながっていない部分がある）")
        if info["watertight"] is False:
            warn.append(f"{name}: STL が閉じていない（開いた辺 {info['open_edges']} 本、線や点だけで接する所がないか見直す）")
        if not info["fits_bed"]:
            warn.append(f"{name}: プリンタのベッド {bed} mm に入らない")
        result["parts"][name] = info
    for name, shp in context.items():
        export_stl(shp, str(out / f"ctx_{name}.stl"))
        result["context"][name] = {"bbox_mm": bbox(shp)}
    holes_by_part = {n: result["parts"][n]["hole_list"] for n in parts}
    result["dims"], dim_warns = measure_dims(ns.get("dims"), parts, context, holes_by_part)
    warn.extend(dim_warns)
    result["clearance"] = clearances(parts, context)
    intended = {(m["part"], m.get("to")) for m in result["dims"] if m.get("kind") == "clearance" and m.get("ok")}
    for c in result["clearance"]:
        if c["mm"] is not None and 0 < c["mm"] < 1.0 and (c["part"], c["to"]) not in intended:
            warn.append(f"{c['part']}: {c['to']} とのすき間が {c['mm']} mm しかない"
                        "（わざとなら dims に clearance と expect を書く）")
    lo = [min(p["bbox_mm"]["min"][i] for p in result["parts"].values()) for i in range(3)]
    hi = [max(p["bbox_mm"]["max"][i] for p in result["parts"].values()) for i in range(3)]
    result["parts_size_mm"] = [round(hi[i] - lo[i], 1) for i in range(3)]
    # parts overlapping their surroundings (or each other) are almost always a design error
    names = list(parts)
    pairs = [(a, b, parts[b]) for i, a in enumerate(names) for b in names[i + 1:]]
    pairs += [(a, f"context:{c}", context[c]) for a in names for c in context]
    for a, b, other in pairs:
        try:
            v = (parts[a] & other).volume
        except Exception as e:  # not knowing is not the same as "no overlap"
            result["interference_unchecked"].append({"a": a, "b": b, "error": f"{type(e).__name__}: {e}"[:200]})
            warn.append(f"{a} と {b} の重なりを計算できなかった（干渉 未判定）")
            continue
        if v > 1.0:  # mm^3
            result["interference"].append({"a": a, "b": b, "overlap_cm3": round(v / 1000, 3)})
        elif v > 1e-6:
            result["near_contact"].append({"a": a, "b": b, "overlap_mm3": round(v, 3)})
    write_result(result)


if __name__ == "__main__":
    main()
