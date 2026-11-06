"""Runs one model script in a child process and exports its parts.

Usage: python -m spatialvibe_mcp._runner <code.py> <out_dir> <result.json>
The script must define `parts` (dict name -> build123d Shape, the things to print) and may
define `context` (dict name -> Shape, surroundings shown translucent, never printed) and
`print_orientation` (dict part name -> (rx, ry, rz) degrees, applied like build123d Rot).
part_*.stl/step keep the assembled pose (preview, AR); print_*.stl holds each part turned to
its print pose (as modelled if not given), centred on X/Y and resting on z=0.
Writes one JSON object to <result.json>.

This process runs untrusted code: the server starts it inside the sandbox (see _isolation.py)
with a scratch folder, and treats everything it writes — files and this JSON — as hostile until
validated. The script can monkeypatch anything here; nothing below is a security boundary.
"""
import json
import math
import re
import runpy
import sys
import traceback
from pathlib import Path

from spatialvibe_mcp._isolation import apply_child_limits

NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
RESULT = None


def fail(msg):
    Path(RESULT).write_text(json.dumps({"ok": False, "error": msg}, ensure_ascii=False), encoding="utf-8")
    sys.exit(0)


def as_dict(obj, label):
    if obj is None:
        return {}
    if not isinstance(obj, dict):
        obj = {label: obj}
    seen = {}
    for k, v in obj.items():
        if not isinstance(k, str) or not NAME.fullmatch(k):
            fail(f"{label}: name {k!r} must match {NAME.pattern}")
        if k.casefold() in seen:  # file names would collide on a case-insensitive disk (macOS)
            fail(f"{label}: names {seen[k.casefold()]!r} and {k!r} differ only in case")
        seen[k.casefold()] = k
        if not hasattr(v, "wrapped"):
            fail(f"{label}[{k!r}] is {type(v).__name__}, not a build123d Shape")
    return obj


def orientations(obj, parts):
    if obj is None:
        return {}
    if not isinstance(obj, dict):
        fail("print_orientation must be a dict {part_name: (rx, ry, rz)} in degrees")
    out = {}
    for k, v in obj.items():
        if k not in parts:
            fail(f"print_orientation: {k!r} is not one of parts {sorted(parts)} (context is never printed)")
        if not isinstance(v, (tuple, list)) or len(v) != 3 or not all(
                isinstance(a, (int, float)) and not isinstance(a, bool) and math.isfinite(a) for a in v):
            fail(f"print_orientation[{k!r}] must be three finite numbers (rx, ry, rz) in degrees, got {v!r}")
        out[k] = [float(a) for a in v]
    return out


def print_pose(shape, rot):
    """Turn a part to its print pose, centre it on X/Y and rest it on z=0."""
    from build123d import Pos, Rot
    if rot is not None:
        shape = Rot(*rot) * shape
    b = shape.bounding_box()
    return Pos(-(b.min.X + b.max.X) / 2, -(b.min.Y + b.max.Y) / 2, -b.min.Z) * shape


def bbox(shape):
    b = shape.bounding_box()
    return {"size": [round(b.size.X, 2), round(b.size.Y, 2), round(b.size.Z, 2)],
            "min": [round(b.min.X, 2), round(b.min.Y, 2), round(b.min.Z, 2)],
            "max": [round(b.max.X, 2), round(b.max.Y, 2), round(b.max.Z, 2)]}


def main():
    global RESULT
    code_path, out, RESULT = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    sys.argv = [str(code_path)]  # the script must not see the runner's arguments
    apply_child_limits()         # before any untrusted code
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
    rots = orientations(ns.get("print_orientation"), parts)

    result = {"ok": True, "parts": {}, "context": {}, "interference": []}
    try:
        for name, shp in parts.items():
            export_stl(shp, str(out / f"part_{name}.stl"))
            export_step(shp, str(out / f"part_{name}.step"))
            posed = print_pose(shp, rots.get(name))
            export_stl(posed, str(out / f"print_{name}.stl"))
            pb = posed.bounding_box()
            result["parts"][name] = {
                "valid": bool(shp.is_valid),
                "solids": len(shp.solids()),
                "volume_cm3": round(shp.volume / 1000, 2),
                "bbox_mm": bbox(shp),
                # unrounded on purpose: the build-volume check must not be fooled by rounding
                "print": {"rotate_xyz_deg": rots.get(name), "size_mm_exact": [pb.size.X, pb.size.Y, pb.size.Z]},
            }
        for name, shp in context.items():
            export_stl(shp, str(out / f"ctx_{name}.stl"))
            result["context"][name] = {"bbox_mm": bbox(shp)}
    except Exception:
        fail("export failed: " + traceback.format_exc(limit=4))
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
    Path(RESULT).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
