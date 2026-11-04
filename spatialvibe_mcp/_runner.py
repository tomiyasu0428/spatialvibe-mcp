"""Runs one model script in a child process and exports its parts.

Usage: python -m spatialvibe_mcp._runner <code.py> <out_dir>
The script must define `parts` (dict name -> build123d Shape, the things to print) and may
define `context` (dict name -> Shape, surroundings shown translucent, never printed).
Prints one JSON object on the last line of stdout.
"""
import json
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

    result = {"ok": True, "parts": {}, "context": {}, "interference": []}
    for name, shp in parts.items():
        export_stl(shp, str(out / f"part_{name}.stl"))
        export_step(shp, str(out / f"part_{name}.step"))
        result["parts"][name] = {
            "valid": bool(shp.is_valid),
            "solids": len(shp.solids()),
            "volume_cm3": round(shp.volume / 1000, 2),
            "bbox_mm": bbox(shp),
        }
    for name, shp in context.items():
        export_stl(shp, str(out / f"ctx_{name}.stl"))
        result["context"][name] = {"bbox_mm": bbox(shp)}
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
