"""One build: run the model script in a job, validate what it reported, admit its files.

The runner's JSON is rebuilt here field by field (the script can monkeypatch the runner and write
anything), and only then are the expected mesh files copied into the version folder. The doctor's
test build goes through `run_script` too, so it exercises exactly the server's path.
"""
import json
import math
import re

from . import _files as files
from . import _isolation as iso
from . import printing
from ._store import Dir, names

ERROR_CHARS = 3000


def clip(s, n: int) -> str:
    """Child-produced text, control characters removed, bounded."""
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", str(s))[:n]


def num(x, label, nonneg=False) -> float:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) or (nonneg and x < 0):
        raise ValueError(f"{label} is not a finite number")
    return float(x)


def vec3(x, label, nonneg=False) -> list[float]:
    if not isinstance(x, list) or len(x) != 3:
        raise ValueError(f"{label} is not three numbers")
    return [num(c, label, nonneg) for c in x]


def _bbox(box, label) -> dict:
    if not isinstance(box, dict):
        raise ValueError(label)
    return {k: vec3(box.get(k), f"{label}.{k}", k == "size") for k in ("size", "min", "max")}


def clean_result(raw) -> dict:
    """The child's JSON rebuilt from validated fields only; ValueError when it is not usable."""
    if not isinstance(raw, dict):
        raise ValueError("not an object")
    if raw.get("ok") is not True:
        err = raw.get("error")
        return {"ok": False, "error": clip(err, ERROR_CHARS) if isinstance(err, str) and err else "build failed"}
    parts, context = names(raw.get("parts"), "parts"), names(raw.get("context"), "context")
    if not parts:
        raise ValueError("no parts")
    clean = {"ok": True, "parts": {}, "context": {}, "interference": []}
    for name, info in parts.items():
        solids = info.get("solids")
        if isinstance(solids, bool) or not isinstance(solids, int) or solids < 0:
            raise ValueError(f"parts[{name}].solids")
        pr = info.get("print")
        if not isinstance(pr, dict):
            raise ValueError(f"parts[{name}].print")
        rot = pr.get("rotate_xyz_deg")
        clean["parts"][name] = {
            "valid": info.get("valid") is True,
            "solids": solids,
            "volume_cm3": num(info.get("volume_cm3"), f"parts[{name}].volume_cm3"),
            "bbox_mm": _bbox(info.get("bbox_mm"), f"parts[{name}].bbox_mm"),
            "print": {"rotate_xyz_deg": None if rot is None else vec3(rot, f"parts[{name}].print.rotate_xyz_deg"),
                      "size_mm_exact": vec3(pr.get("size_mm_exact"), f"parts[{name}].print.size_mm_exact", True)},
        }
    for name, info in context.items():
        clean["context"][name] = {"bbox_mm": _bbox(info.get("bbox_mm"), f"context[{name}].bbox_mm")}
    hits = raw.get("interference")
    if not isinstance(hits, list):
        raise ValueError("interference")
    for h in hits[:200]:
        if not isinstance(h, dict):
            raise ValueError("interference entry")
        clean["interference"].append({"a": clip(h.get("a"), 60), "b": clip(h.get("b"), 80),
                                      "overlap_cm3": num(h.get("overlap_cm3"), "interference.overlap_cm3", True)})
    return clean


def run_script(job: iso.Job, code: str) -> iso.Run:
    """Run one model script through the runner inside the job's sandbox."""
    job.put_text("model.py", code)
    return job.run("spatialvibe_mcp._runner", [job.work / "model.py", job.out, job.out / "result.json"])


def result_of(job: iso.Job, run: iso.Run, printer) -> dict:
    """The build's outcome as the server stores it: cleaned, with the printer fit per part."""
    if run.timed_out:
        return {"ok": False, "error": f"timed out after {job.timeout}s; nothing was kept"}
    try:
        raw = job.read_output("result.json", iso.MAX_TEXT_BYTES)
        parsed = json.loads(raw) if raw is not None else None
    except (files.BoundaryError, ValueError):
        parsed = None
    if run.returncode != 0 or parsed is None:
        tail = run.stderr_tail or "no output"
        return {"ok": False, "error": f"the build process exited with code {run.returncode} before finishing. {tail}"}
    try:
        res = clean_result(parsed)
        if res["ok"]:
            res["printer"] = printer
            for info in res["parts"].values():
                info["print"].update(printing.fit(info["print"], printer))
    except (ValueError, KeyError, TypeError) as e:
        return {"ok": False, "error": f"runner result malformed: {clip(e, 300)}"}
    return res


def build_files(parts, context) -> list[str]:
    return [*(f"part_{n}.stl" for n in parts), *(f"part_{n}.step" for n in parts),
            *(f"print_{n}.stl" for n in parts), *(f"ctx_{n}.stl" for n in context)]


def admit(job: iso.Job, v: Dir, res: dict) -> dict:
    """Copy the expected mesh files into the fresh version folder; on any doubt keep nothing."""
    done = []
    try:
        for name in build_files(res["parts"], res["context"]):
            job.admit(name, v.fd, name, iso.MAX_MESH_BYTES)
            done.append(name)
    except files.BoundaryError as e:
        for name in done:
            files.remove_entry(name, v.fd)
        return {"ok": False, "error": f"unsafe or missing build output ({e}); nothing was kept"}
    return res
