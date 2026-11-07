"""Prepare an immutable AR snapshot. Only the trusted parent handles publication credentials."""
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from ._scratch import scratch_directory

from ._artifacts import safe_bytes
from ._isolation import run_isolated
from ._result import clean_text

MESH = re.compile(r"(?:part|ctx)_[A-Za-z0-9_-]{1,40}\.stl")
MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Export:
    body: bytes
    sha256: str
    scene_size_m: tuple[float, float, float]  # USD axes: X, Y-up, Z
    include_context: bool
    ar_floor_mm: float | None


def export_snapshot(version: Path, include_context: bool = True, floor_z: float | None = None,
                    max_bytes: int = MAX_BYTES, *, timeout: int = 180) -> Export:
    """Parse untrusted mesh data in a separate sandbox; upload the bytes we actually checked."""
    if type(include_context) is not bool or type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
        raise ValueError("Invalid export options")
    floor_z = floor_z if include_context else None
    if floor_z is not None and (type(floor_z) not in (int, float) or not math.isfinite(floor_z)):
        raise ValueError("ar_floor must be a finite number")
    with scratch_directory("spatialvibe-ar-") as work:
        total = count = 0
        has_parts = False
        for f in version.iterdir():
            if MESH.fullmatch(f.name) and (include_context or f.name.startswith("part_")):
                count += 1
                if count > 1024:
                    raise ValueError("Too many mesh files")
                data = safe_bytes(f, max_bytes - total)
                total += len(data)
                (work / f.name).write_bytes(data)
                has_parts |= f.name.startswith("part_")
        if not has_parts:
            raise ValueError("No printable meshes")
        try:
            r = run_isolated(work, Path(__file__).resolve().parent.parent, "usdz",
                             [work, int(include_context), json.dumps(floor_z)], timeout)
        except subprocess.TimeoutExpired:
            raise ValueError("AR export timed out") from None
        if r.returncode:
            # Forward only the placement error that the user can fix.
            errors = [s for s in r.stderr.splitlines() if s.startswith("ar_floor ")]
            raise ValueError(clean_text(errors[-1], 300) if errors else "AR export failed")
        body = safe_bytes(work / "model.usdz", max_bytes)
        size = json.loads(safe_bytes(work / "size.json", 1024))
        if not isinstance(size, list) or len(size) != 3 or not all(
                type(n) in (int, float) and math.isfinite(n) and n >= 0 for n in size):
            raise ValueError("AR export produced invalid extents")
        return Export(body, hashlib.sha256(body).hexdigest(), tuple(size), include_context, floor_z)
