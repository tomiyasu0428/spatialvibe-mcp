"""SpatialVibe MCP server (stdio).

Tools: build_model, preview, publish_ar, list_projects, get_code.
Data lives in $SPATIALVIBE_HOME (default: <repo>/data/mcp_projects), one folder per
project and one numbered folder per version (v001, v002, ...).
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .usdz import build_usdz, usdz_size_m

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SPATIALVIBE_HOME", REPO / "data" / "mcp_projects")).expanduser()
ICLOUD = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
PUBLISH = os.environ.get("SPATIALVIBE_PUBLISH", "icloud")   # "icloud" | "dir:/some/path"
TIMEOUT = int(os.environ.get("SPATIALVIBE_TIMEOUT", "180"))
PROJECT = re.compile(r"[A-Za-z0-9_-]{1,60}")


class SpatialVibeError(ToolError, ValueError):
    """An expected failure whose message must reach the client.

    The MCP SDK hides the text of any other exception (the model only sees "Error executing tool
    X"), so every guard below raises this. It is also a ValueError for direct Python callers.
    """

INSTRUCTIONS = (Path(__file__).parent / "WORKFLOW.md").read_text(encoding="utf-8")
mcp = MCPServer("spatialvibe", instructions=INSTRUCTIONS)


def _project_dir(project: str) -> Path:
    if not isinstance(project, str) or not PROJECT.fullmatch(project):
        raise SpatialVibeError(f"project must be 1-60 ASCII letters, digits, _ or - (e.g. 'aio-mount'); got {project!r}")
    return HOME / project


def _versions(pdir: Path):
    return sorted(p for p in pdir.glob("v[0-9][0-9][0-9]") if p.is_dir())


def _version_dir(project: str, version) -> Path:
    pdir = _project_dir(project)
    vs = _versions(pdir)
    if not vs:
        raise SpatialVibeError(f"project {project!r} has no versions yet; call build_model first")
    if version is None:
        return vs[-1]
    if not isinstance(version, int) or version < 1:
        raise SpatialVibeError(f"version must be a positive number like 1 or 2; got {version!r}")
    v = pdir / f"v{version:03d}"
    if not v.exists():
        raise SpatialVibeError(f"{project} has no version {version}; latest is {vs[-1].name}")
    return v


def _built_version_dir(project: str, version) -> Path:
    """Like _version_dir, but the version must have built successfully (result.json ok is True).

    A failed or interrupted build is never previewed or published, even if some files exist.
    """
    v = _version_dir(project, version)
    res = _read_result(v)
    if res.get("ok") is not True or not any(v.glob("part_*.stl")):
        why = res.get("error", "no result")[:300] if isinstance(res.get("error"), str) else "no result"
        raise SpatialVibeError(f"{project} {v.name} did not build, so it cannot be previewed or published. "
                               f"Fix the script and call build_model again. Error: {why}")
    return v


def _read_result(vdir: Path) -> dict:
    try:
        r = json.loads((vdir / "result.json").read_text(encoding="utf-8"))
        return r if isinstance(r, dict) else {}
    except (OSError, ValueError):
        return {}


def _new_version_dir(pdir: Path) -> Path:
    """Claim the next free vNNN atomically (parallel calls each get their own folder)."""
    pdir.mkdir(parents=True, exist_ok=True)
    vs = _versions(pdir)
    n = int(vs[-1].name[1:]) + 1 if vs else 1
    while True:
        vdir = pdir / f"v{n:03d}"
        try:
            vdir.mkdir()
            return vdir
        except FileExistsError:
            n += 1


def _sandbox_cmd(out: Path, argv):
    """Deny network and writes outside the version folder / temp (macOS sandbox-exec)."""
    if sys.platform != "darwin" or not shutil.which("sandbox-exec"):
        return argv
    profile = (
        "(version 1)(allow default)(deny network*)(deny file-write*)"
        f'(allow file-write* (subpath "{out.resolve()}") (subpath "/private/var/folders")'
        ' (subpath "/private/tmp") (literal "/dev/null"))'
    )
    return ["sandbox-exec", "-p", profile, *argv]


def _child_env():
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg")
    env["MPLCONFIGDIR"] = "/private/tmp/spatialvibe-mpl"
    return env


@mcp.tool()
def build_model(project: str, code: str, note: str = "") -> dict:
    """Run a build123d script and save it as a new version of the project.

    `code` is a complete Python script using build123d (units: mm, Z up). It must define
    `parts = {"name": shape, ...}` — the things to print — and may define
    `context = {"name": shape, ...}` — surroundings (pipe, box, wall...) shown translucent
    in previews and AR but never printed. Names: ASCII letters, digits, _ or -.
    Optional `hardware = ["M5×30 ボルト・ナット 6組", ...]` (what to buy) and
    `checks = ["パイプの周長 7.0 cm（Ø22.2）", ...]` (what to measure before printing) are echoed
    in the result and printed on the dimension sheet.
    Returns per-part validity, solid count, volume, bounding box, round holes (`holes` summary and
    `hole_list` with each hole's diameter, axis and centre), whether the exported STL is closed
    (`watertight`), whether it fits the print bed ($SPATIALVIBE_BED, default 256×256×256 mm), the
    overall size of the printed parts, overlaps between parts and context (`interference`; faces
    that only touch are not overlaps, tiny ones are in `near_contact`; pairs that could not be
    computed are in `interference_unchecked` = 未判定), and `warnings` you must fix or explain.
    A build that fails leaves no part files behind and cannot be previewed or published.
    Always call `preview` afterwards and look at both images before showing the user.
    """
    vdir = _new_version_dir(_project_dir(project))
    (vdir / "model.py").write_text(code, encoding="utf-8")
    (vdir / "note.txt").write_text(note, encoding="utf-8")
    stage = vdir / "_build"           # the runner writes here; files move up only on success
    stage.mkdir()
    result_file = stage / "_result.json"
    argv = [sys.executable, "-m", "spatialvibe_mcp._runner", str(vdir / "model.py"), str(stage), str(result_file)]
    try:
        p = subprocess.run(_sandbox_cmd(vdir, argv), capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           timeout=TIMEOUT, cwd=vdir, env=_child_env())
    except subprocess.TimeoutExpired:
        res = {"ok": False, "error": f"timed out after {TIMEOUT}s; nothing was kept"}
    else:
        try:
            res = json.loads(result_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            res = None
        if p.returncode != 0 or not isinstance(res, dict):
            tail = (p.stderr or "").strip()[-2500:] or "no output"
            res = {"ok": False, "error": f"the build process exited with code {p.returncode} before finishing. {tail}"}
    if res.get("ok") is True:
        for f in stage.iterdir():
            if f.name.startswith(("part_", "ctx_", "print_")):
                f.replace(vdir / f.name)
    shutil.rmtree(stage, ignore_errors=True)
    (vdir / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    res.update(project=project, version=int(vdir.name[1:]), folder=str(vdir))
    if res.get("ok") is True:
        res["files"] = sorted(str(f) for f in vdir.glob("part_*.*"))
    return res


@mcp.tool()
def preview(project: str, version: int | None = None) -> list:
    """Render the 4-view picture and the dimension sheet of a version (latest by default).

    1) Four views (front-oblique, rear-oblique, right side, below), framed on the printed parts;
       parts in distinct opaque colours, context translucent grey and cut to the frame.
    2) Dimension sheet for the user's phone: part count, overall size, and per part the size
       W×D×H mm, round holes, whether it fits the print bed, top/front views with dimension lines,
       then the script's `hardware` and `checks` lists.
    Look at both yourself before replying; send the user the sheet (sheet.png) with your reply.
    """
    vdir = _built_version_dir(project, version)
    out = []
    for mod, name in (("_render", "preview.png"), ("_sheet", "sheet.png")):
        argv = [sys.executable, "-m", f"spatialvibe_mcp.{mod}", str(vdir)]
        p = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=TIMEOUT, env=_child_env())
        png = vdir / name
        if p.returncode != 0 or not png.exists():
            raise SpatialVibeError(f"drawing the {name} failed: {p.stderr.strip()[-1500:] or 'no output'}")
        out.append(png)
    return [Image(path=str(out[0])), Image(path=str(out[1])),
            f"{project} {vdir.name}: views {out[0]} / dimension sheet {out[1]}"]


@mcp.tool()
def publish_ar(project: str, version: int | None = None, include_context: bool = True) -> dict:
    """Make a real-scale USDZ of a version and put it where the user's iPhone can open it in AR.

    With include_context the surroundings are included translucent, so the user can line the
    model up with the real object (e.g. the pipe). Default target is iCloud Drive
    (Files app → iCloud Drive → SpatialVibe), which works on any network.
    """
    vdir = _built_version_dir(project, version)
    usdz = build_usdz(vdir, include_context)
    fname = f"{project}_{vdir.name}{'' if include_context else '_parts-only'}.usdz"
    if PUBLISH == "icloud":
        if not ICLOUD.exists():
            raise SpatialVibeError("iCloud Drive not found on this Mac; set SPATIALVIBE_PUBLISH=dir:/path")
        dest_dir = ICLOUD / "SpatialVibe"
        how = f"iPhone の「ファイル」→ iCloud Drive → SpatialVibe → {fname} をタップ（100% 表示で実寸）"
    elif PUBLISH.startswith("dir:"):
        dest_dir = Path(PUBLISH[4:]).expanduser()
        how = f"{dest_dir / fname} を iPhone で開く"
    else:
        raise SpatialVibeError(f"unknown SPATIALVIBE_PUBLISH={PUBLISH!r}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(usdz, dest_dir / fname)
    res = _read_result(vdir)
    pm = [round(v / 1000, 4) for v in res.get("parts_size_mm", [0, 0, 0])]
    sx, sy_up, sz = usdz_size_m(usdz)
    return {"usdz": str(usdz), "published": str(dest_dir / fname), "how_to_open": how,
            "parts_size_m": {"x_width": pm[0], "y_depth": pm[1], "z_height": pm[2]},
            "scene_size_m": {"x_width": sx, "y_depth": sz, "z_height": sy_up},
            "include_context": include_context,
            "note": "quote parts_size_m (what is printed); scene_size_m also contains the context. "
                    "Both use the script's axes: x = width, y = depth, z = height."}


@mcp.tool()
def list_projects(project: str | None = None) -> dict:
    """List projects, or the versions of one project with their notes and part summaries."""
    if project is None:
        if not HOME.exists():
            return {"projects": []}
        return {"projects": [{"project": p.name, "versions": len(_versions(p))}
                             for p in sorted(HOME.iterdir()) if p.is_dir()]}
    out = []
    for v in _versions(_project_dir(project)):
        r = _read_result(v)
        ok = r.get("ok") is True
        note = (v / "note.txt").read_text(encoding="utf-8") if (v / "note.txt").exists() else ""
        out.append({"version": int(v.name[1:]), "note": note,
                    "ok": ok, "status": "built" if ok else ("failed" if r else "building or unknown"),
                    "warnings": len(r.get("warnings", [])) if ok else None,
                    "parts": {k: {"size_mm": x.get("bbox_mm", {}).get("size"), "holes": x.get("holes"),
                                  "fits_bed": x.get("fits_bed"), "watertight": x.get("watertight")}
                              for k, x in r.get("parts", {}).items()}})
    return {"project": project, "versions": out}


@mcp.tool()
def get_code(project: str, version: int | None = None) -> str:
    """Return the build123d script of a version (latest by default), to modify and rebuild."""
    return (_version_dir(project, version) / "model.py").read_text(encoding="utf-8")


@mcp.prompt()
def design_session(goal: str = "") -> str:
    """Start a fit-for-purpose design session (photos of the space + the thing to place)."""
    return INSTRUCTIONS + (f"\n\nユーザーの目的: {goal}" if goal else "")


def main():
    HOME.mkdir(parents=True, exist_ok=True)
    mcp.run()


if __name__ == "__main__":
    main()
