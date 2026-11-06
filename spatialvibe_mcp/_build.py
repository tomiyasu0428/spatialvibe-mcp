"""Build in private scratch and only admit bounded geometry to the retained version."""
import json
from ._scratch import scratch_directory, unchanged_directory
from pathlib import Path

from . import printing
from ._artifacts import FILE_LIMIT, TOTAL_LIMIT, atomic_bytes, copy_artifacts, safe_bytes, safe_text
from ._isolation import configured_bed, run_isolated


def build_in_scratch(vdir, code, package_root, timeout):
    # The model never has write access to a persistent version or a subsequent tool's inputs.
    with scratch_directory("sv-model-") as scratch:
        script = scratch / "model.py"
        script.write_text(code, encoding="utf-8")
        stage = scratch / "_build"
        stage.mkdir()
        result_file = stage / "_result.json"
        with unchanged_directory(stage):
            p = run_isolated(scratch, package_root, "_runner", [script, stage, result_file], timeout)
        if p.returncode:
            return {"ok": False, "error": f"build process exited with code {p.returncode}: {p.stderr[-2500:]}"}
        res = json.loads(safe_text(result_file))
        if not isinstance(res, dict):
            raise ValueError("Malformed runner result")
        if res.get("ok") is True:
            for key in ("parts", "context"):
                names = res.get(key, {})
                if not isinstance(names, dict) or len(names) > 128 or any(not printing.NAME.fullmatch(n) for n in names):
                    raise ValueError("Unsafe runner part names")
                if len({n.casefold() for n in names}) != len(names):
                    raise ValueError("Conflicting runner part names")
            if not res.get("parts") or (res.get("plate") or {}).get("file") not in (None, "print_plate.3mf"):
                raise ValueError("Invalid print artifact")
            copy_artifacts(stage, vdir)
            if any(not (vdir / f"part_{n}.stl").is_file() for n in res["parts"]):
                raise ValueError("Missing part STL")
        return res


def prepare_plate(vdir, result, package_root, timeout):
    """Build a geometry-only plate from the admitted STL, independently of model.py.

    In particular, never return slicer settings, scripts or other ZIP members from
    an archive planted by generated code or stored by an older server.
    """
    with scratch_directory("sv-plate-") as scratch:
        parts = result["parts"]
        budget = TOTAL_LIMIT
        for name in parts:
            if not printing.NAME.fullmatch(name):
                raise ValueError("Invalid plate part name")
            src = vdir / f"print_{name}.stl"
            if not src.exists():
                src = vdir / f"part_{name}.stl"
            data = safe_bytes(src, min(budget, FILE_LIMIT))
            budget -= len(data)
            (scratch / src.name).write_bytes(data)
        printer = printing.resolve_printer("", result.get("printer"))
        bed = printer["build_volume_mm"] if printer else configured_bed()
        result["bed_mm"] = list(bed)
        spec = {"parts": list(parts), "labels": result.get("labels") or {},
                "bed_mm": bed}
        (scratch / "inputs.json").write_text(json.dumps(spec))
        p = run_isolated(scratch, package_root, "_geometry_plate", [scratch], timeout)
        if p.returncode:
            raise ValueError("Could not generate a geometry-only print plate")
        plate = json.loads(safe_text(scratch / "plate.json"))
        atomic_bytes(vdir / "print_plate.3mf", safe_bytes(scratch / "print_plate.3mf", FILE_LIMIT))
        return plate
