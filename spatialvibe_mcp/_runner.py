"""Runs one model script in a child process and exports its parts.

Usage: python -m spatialvibe_mcp._runner <code.py> <out_dir>
The script must define `parts` (dict name -> build123d Shape, the things to print) and may
define `context` (dict name -> Shape, surroundings shown translucent, never printed).
Prints one JSON object on the last line of stdout.
"""
import json
import os
import re
import runpy
import sys
import traceback
from pathlib import Path

NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def fail(msg):
    print(json.dumps({"ok": False, "error": msg}, ensure_ascii=False))
    sys.exit(0)


def as_dict(obj, label):
    if obj is None:
        return {}
    if not isinstance(obj, dict):
        obj = {label: obj}
    for k, v in obj.items():
        if not isinstance(k, str) or not NAME.match(k):
            fail(f"{label}: name {k!r} must match {NAME.pattern}")
        if not hasattr(v, "wrapped"):
            fail(f"{label}[{k!r}] is {type(v).__name__}, not a build123d Shape")
    return obj


def bbox(shape):
    b = shape.bounding_box()
    return {"size": [round(b.size.X, 2), round(b.size.Y, 2), round(b.size.Z, 2)],
            "min": [round(b.min.X, 2), round(b.min.Y, 2), round(b.min.Z, 2)],
            "max": [round(b.max.X, 2), round(b.max.Y, 2), round(b.max.Z, 2)]}


def holes(shape):
    """Round holes in a part: [{"d": mm, "n": count, "half": bool}], from cylindrical faces whose normal
    points toward their axis (bores, bolt holes). half=True marks half-round cut-outs (split-clamp
    bores, slot ends). Bosses and smaller arcs (fillets) are ignored."""
    from build123d import GeomType
    counts = {}
    for f in shape.faces().filter_by(GeomType.CYLINDER):
        try:
            r = f.radius
            ax = f.axis_of_rotation
            c = f.center()
            o, d = ax.position, ax.direction
            radial = (c - o) - d * (c - o).dot(d)
            if f.normal_at(c).dot(radial) >= 0:
                continue  # outer surface (boss, round bar)
            ts = [(v - o).dot(d) for v in (vt.center() for vt in f.vertices())]
            length = (max(ts) - min(ts)) if ts else 0
            cover = f.area / (2 * 3.141592653589793 * r * length) if length > 0 else 0
            if cover < 0.45:
                continue  # fillet or small arc
        except Exception:
            continue
        key = (round(2 * r, 1), cover < 0.95)
        counts[key] = counts.get(key, 0) + 1
    return [{"d": d, "n": n, "half": half} for (d, half), n in sorted(counts.items())]


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
    code_path, out = Path(sys.argv[1]), Path(sys.argv[2])
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
    result = {"ok": True, "parts": {}, "context": {}, "interference": [],
              "hardware": text_list(ns.get("hardware"), "hardware"),
              "checks": text_list(ns.get("checks"), "checks"), "bed_mm": bed}
    for name, shp in parts.items():
        export_stl(shp, str(out / f"part_{name}.stl"))
        export_step(shp, str(out / f"part_{name}.step"))
        result["parts"][name] = {
            "valid": bool(shp.is_valid),
            "solids": len(shp.solids()),
            "volume_cm3": round(shp.volume / 1000, 2),
            "bbox_mm": bbox(shp),
            "holes": holes(shp),
        }
        result["parts"][name]["fits_bed"] = fits_bed(result["parts"][name]["bbox_mm"]["size"], bed)
    for name, shp in context.items():
        export_stl(shp, str(out / f"ctx_{name}.stl"))
        result["context"][name] = {"bbox_mm": bbox(shp)}
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
        except Exception:
            continue
        if v > 1.0:  # mm^3
            result["interference"].append({"a": a, "b": b, "overlap_cm3": round(v / 1000, 3)})
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
