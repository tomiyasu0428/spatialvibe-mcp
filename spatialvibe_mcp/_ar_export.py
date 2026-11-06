"""Unintegrated candidate: immutable, isolated export for a future AR uploader.

No credentials, network, server changes or persistent project writes. Import with
the reviewed SpatialVibe checkout on PYTHONPATH. This is an integration candidate,
not a deployed publisher or a replacement for generated-code isolation.
"""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile

from .usdz import build_usdz, usdz_size_m

MESH = re.compile(r"(?:part|ctx)_[A-Za-z0-9_-]+\.stl\Z")
MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class Export:
    body: bytes
    sha256: str
    scene_size_m: tuple[float, float, float]  # USD axes: X, Y-up, Z
    include_context: bool
    ar_floor_mm: float | None


def export_snapshot(version: Path, include_context: bool = True,
                    floor_z: float | None = None, max_bytes: int = MAX_BYTES) -> Export:
    """Snapshot only regular mesh files, export privately, return the exact bytes to upload.

    Each call owns its temporary directory, so context variants never overwrite one
    another. This protects export integrity; callers must separately authorize which
    project/version may be published and retain printable dimensions from result.json.
    """
    if type(include_context) is not bool or type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("Invalid export options")
    if not include_context:
        floor_z = None
    fd = os.open(version, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with tempfile.TemporaryDirectory(prefix="spatialvibe-ar-") as directory:
            work = Path(directory)
            names = sorted(name for name in os.listdir(fd) if MESH.fullmatch(name)
                           and (include_context or name.startswith("part_")))
            if not any(name.startswith("part_") for name in names):
                raise ValueError("No printable meshes")
            total = 0
            for name in names:
                source = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(source, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise ValueError("Only regular mesh files may be exported")
                    with (work / name).open("xb") as destination:
                        while block := stream.read(min(1024 * 1024, max_bytes - total + 1)):
                            total += len(block)
                            if total > max_bytes:
                                raise ValueError("Input meshes exceed export limit")
                            destination.write(block)
            package = build_usdz(work, include_context, floor_z)
            with package.open("rb") as stream:
                body = stream.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError("USDZ exceeds export limit")
            return Export(body, hashlib.sha256(body).hexdigest(),
                          tuple(usdz_size_m(package)), include_context, floor_z)
    finally:
        os.close(fd)
