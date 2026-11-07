"""Trusted-parent reads and atomic writes for model artifacts."""
import json
import os
import re
import secrets
import stat
from pathlib import Path

from mcp.server.mcpserver.exceptions import ToolError


class SpatialVibeError(ToolError, ValueError):
    """An expected failure whose message must reach the client.

    The MCP SDK hides the text of any other exception (the model only sees "Error executing tool
    X"), so every guard below raises this. It is also a ValueError for direct Python callers.
    """


TEXT_LIMIT = 8 << 20
FILE_LIMIT = 64 << 20
TOTAL_LIMIT = 128 << 20
ARTIFACT = re.compile(r"(?:(?:part|print)_[A-Za-z0-9_-]{1,40}\.(?:step|stl)|ctx_[A-Za-z0-9_-]{1,40}\.stl|pose[0-9]+_(?:part|ctx)_[A-Za-z0-9_-]{1,40}\.stl)")


def safe_bytes(path: Path, limit: int) -> bytes:
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > limit:
                raise SpatialVibeError("Unsafe or oversized project file")
            data = stream.read(st.st_size + 1)
            if len(data) != st.st_size:
                raise SpatialVibeError("Project file changed during read")
            return data
    finally:
        os.close(directory)


def safe_text(path: Path) -> str:
    return safe_bytes(path, TEXT_LIMIT).decode("utf-8")


def copy_artifacts(src: Path, dest: Path, *, render=False, allowed=None):
    """Copy model files; `allowed` (a set of names) limits a build to the files its result names."""
    total = count = 0
    if src.is_symlink():
        raise SpatialVibeError("Linked artifact folder")
    for path in src.iterdir():
        if (not ARTIFACT.fullmatch(path.name) or (render and path.suffix != ".stl")
                or (allowed is not None and path.name not in allowed)):
            continue
        count += 1
        if count > 1024:
            raise SpatialVibeError("Too many model files")
        data = safe_bytes(path, min(FILE_LIMIT, TOTAL_LIMIT - total))
        total += len(data)
        atomic_bytes(dest / path.name, data)


def atomic_bytes(path: Path, body: bytes) -> None:
    """Replace a destination entry instead of following its possibly hostile symlink."""
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    name = ".parent-write-" + secrets.token_hex(16)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
        os.replace(name, path.name, src_dir_fd=directory, dst_dir_fd=directory)
    finally:
        try:
            os.unlink(name, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def write_json(path: Path, value) -> None:
    atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"))
