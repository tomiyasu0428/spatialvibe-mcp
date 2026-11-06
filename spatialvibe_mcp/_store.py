"""Where projects and versions live, and how the server opens them.

$SPATIALVIBE_HOME/<project>/vNNN/ holds model.py, note.txt, result.json and the admitted mesh
files. Folders are opened by descriptor from HOME downwards without following symlinks, so a
planted project or version link is invisible, and files are read with the plain-file rules of
`_files`. result.json is parent-written, but its part/context names are re-validated before they
are used in paths (an older server may have written one without validation).

Errors are ValueError with a message meant for the client; the server turns them into tool errors.
"""
import json
import os
import re
from pathlib import Path

from . import _files as files
from ._isolation import MAX_TEXT_BYTES, REPO

HOME = Path(os.environ.get("SPATIALVIBE_HOME", REPO / "data" / "mcp_projects")).expanduser()
PROJECT = re.compile(r"^[A-Za-z0-9_-]{1,60}$")
VERSION = re.compile(r"^v[0-9]{3}$")
NAME = re.compile(r"^[A-Za-z0-9_-]{1,40}$")            # part / context names
MAX_NAMES = 50                                          # parts and context entries per version, each


class Dir:
    """An open directory descriptor plus the path it was reached by (for messages and results)."""

    def __init__(self, fd: int, path: Path):
        self.fd, self.path = fd, path

    @property
    def name(self):
        return self.path.name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Built(Dir):
    """A version that built successfully, with its stored result and validated names."""
    result: dict
    parts: dict
    context: dict


def project_dir(project: str) -> Path:
    if not isinstance(project, str) or not PROJECT.fullmatch(project):
        raise ValueError(f"project must match {PROJECT.pattern} (ASCII, e.g. 'aio-mount')")
    return HOME / project


def open_home(create: bool = False) -> Dir:
    if create:
        HOME.mkdir(parents=True, exist_ok=True)
    return Dir(files.open_dir(HOME, follow=True), HOME)   # HOME is the user's own setting


def open_project(project: str, create: bool = False) -> Dir:
    pdir = project_dir(project)
    with open_home(create) as home:
        try:
            return Dir(files.open_dir(project, home.fd), pdir)
        except FileNotFoundError:
            if not create:
                raise ValueError(f"project {project!r} has no versions yet; call build_model first") from None
            try:
                os.mkdir(project, 0o755, dir_fd=home.fd)
            except FileExistsError:
                pass
            return Dir(files.open_dir(project, home.fd), pdir)
        except NotADirectoryError:
            raise ValueError(f"{pdir} is not a folder; refusing it") from None


def projects() -> list[str]:
    """Project names in HOME (plain folders with valid names only)."""
    if not HOME.is_dir():
        return []
    with open_home() as home:
        return sorted(n for n in os.listdir(home.fd) if PROJECT.fullmatch(n) and files.is_plain_dir(n, home.fd))


def versions(pfd: int) -> list[str]:
    return sorted(n for n in os.listdir(pfd) if VERSION.fullmatch(n) and files.is_plain_dir(n, pfd))


def open_version_in(p: Dir, vname: str) -> Dir:
    return Dir(files.open_dir(vname, p.fd), p.path / vname)


def open_version(project: str, version) -> Dir:
    with open_project(project) as p:
        vs = versions(p.fd)
        if not vs:
            raise ValueError(f"project {project!r} has no versions yet; call build_model first")
        if version is None:
            return open_version_in(p, vs[-1])
        if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 999:
            raise ValueError(f"version must be a number from 1 to 999, got {version!r}")
        vname = f"v{version:03d}"
        if vname not in vs:
            raise ValueError(f"{project} has no version {version}; latest is {vs[-1]}")
        return open_version_in(p, vname)


def new_version(p: Dir) -> Dir:
    """Claim the next free vNNN atomically (parallel calls each get their own folder)."""
    vs = versions(p.fd)
    n = int(vs[-1][1:]) + 1 if vs else 1
    while True:
        if n > 999:
            raise ValueError(f"{p.name} already has 999 versions; start a new project")
        vname = f"v{n:03d}"
        try:
            os.mkdir(vname, 0o755, dir_fd=p.fd)
        except FileExistsError:
            n += 1
            continue
        return open_version_in(p, vname)


def read_result(vfd: int) -> dict:
    """The stored result, {} if missing or not JSON. Refuses a non-plain result.json."""
    try:
        r = json.loads(files.read_file("result.json", vfd, MAX_TEXT_BYTES))
    except (FileNotFoundError, ValueError):
        return {}
    return r if isinstance(r, dict) else {}


def read_text(name: str, vfd: int) -> str:
    return files.read_text(name, vfd, MAX_TEXT_BYTES)


def names(d, label: str) -> dict:
    """A parts/context dict whose keys are safe to use in file names, else ValueError."""
    if d is None:
        return {}
    if not isinstance(d, dict):
        raise ValueError(f"result.json: {label} is not a dict; rebuild this version")
    if len(d) > MAX_NAMES:
        raise ValueError(f"result.json: more than {MAX_NAMES} {label} entries; refusing this version")
    seen = set()
    for k, v in d.items():
        if not isinstance(k, str) or not NAME.fullmatch(k) or k.casefold() in seen or not isinstance(v, dict):
            raise ValueError(f"result.json: invalid {label} entry; refusing this version — rebuild it")
        seen.add(k.casefold())
    return d


def built(project: str, version) -> Built:
    """The version folder, which must have built successfully and still hold plain part files."""
    v = open_version(project, version)
    try:
        res = read_result(v.fd)
        if res.get("ok") is not True:
            raise ValueError(f"{project} {v.name} did not build (see build_model's error); "
                             "fix the script and rebuild")
        parts, context = names(res.get("parts"), "parts"), names(res.get("context"), "context")
        if not parts or not all(files.is_plain_file(f"part_{n}.stl", v.fd) for n in parts):
            raise ValueError(f"{project} {v.name} has no usable part files (missing or not plain files); "
                             "rebuild it with build_model")
    except BaseException:
        v.close()
        raise
    b = Built(v.fd, v.path)
    v.fd = None
    b.result, b.parts, b.context = res, parts, context
    return b


def mpl_cache() -> Path:
    """The renderer's persistent font cache (building it fresh costs ~8 s per preview). Only the
    renderer and the AR exporter, which never run the model script, may write here."""
    return files.plain_cache_dir(HOME, ".cache", "matplotlib")
