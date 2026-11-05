"""SpatialVibe MCP server (stdio).

Tools: build_model, preview, publish_ar, export_print, list_projects, get_code.
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

from . import printing
from .usdz import build_usdz, usdz_size_m

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SPATIALVIBE_HOME", REPO / "data" / "mcp_projects")).expanduser()
ICLOUD = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
PUBLISH = os.environ.get("SPATIALVIBE_PUBLISH", "icloud")   # "icloud" | "dir:/some/path"
TIMEOUT = int(os.environ.get("SPATIALVIBE_TIMEOUT", "180"))
PROJECT = re.compile(r"^[A-Za-z0-9_-]{1,60}$")

INSTRUCTIONS = (Path(__file__).parent / "WORKFLOW.md").read_text(encoding="utf-8")
mcp = MCPServer("spatialvibe", instructions=INSTRUCTIONS)


def _project_dir(project: str) -> Path:
    if not isinstance(project, str) or not PROJECT.fullmatch(project):
        raise ValueError(f"project must match {PROJECT.pattern} (ASCII, e.g. 'aio-mount')")
    return HOME / project


def _versions(pdir: Path):
    return sorted(p for p in pdir.glob("v[0-9][0-9][0-9]") if p.is_dir())


def _version_dir(project: str, version) -> Path:
    pdir = _project_dir(project)
    vs = _versions(pdir)
    if not vs:
        raise ValueError(f"project {project!r} has no versions yet; call build_model first")
    if version is None:
        return vs[-1]
    v = pdir / f"v{int(version):03d}"
    if not v.exists():
        raise ValueError(f"{project} has no version {version}; latest is {vs[-1].name}")
    return v


def _result(vdir: Path) -> dict:
    try:
        r = json.loads((vdir / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return r if isinstance(r, dict) else {}


def _built_version_dir(project: str, version) -> Path:
    """Like _version_dir, but the version must have built successfully (not failed or half-exported)."""
    v = _version_dir(project, version)
    if _result(v).get("ok") is not True or not any(v.glob("part_*.stl")):
        raise ValueError(f"{project} {v.name} did not build (see build_model's error); fix the script and rebuild")
    return v


def _write_atomic(path: Path, text: str):
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.unlink(missing_ok=True)
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


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
def build_model(project: str, code: str, note: str = "", printer: str = "") -> dict:
    """Run a build123d script and save it as a new version of the project.

    `code` is a complete Python script using build123d (units: mm, Z up). It must define
    `parts = {"name": shape, ...}` — the things to print — and may define
    `context = {"name": shape, ...}` — surroundings (pipe, box, wall...) shown translucent
    in previews and AR but never printed. Names: ASCII letters, digits, _ or -.
    Optionally `print_orientation = {"part": (rx, ry, rz)}` (degrees, like build123d Rot)
    turns a part from its assembled pose to its print pose; preview/AR stay assembled.
    `printer`: "a1mini" (Bambu Lab A1 mini, 180x180x180) or a build volume "WxDxH" in mm;
    empty uses $SPATIALVIBE_PRINTER, else the size check is reported as printer_not_set.
    Returns per-part validity, solid count, volume, bounding box, `print` (pose, size and
    fit: fits / exceeds / printer_not_set — exceeds is about that pose only), any overlap
    between parts and context (usually a design error), and the paths of the files.
    Always call `preview` afterwards and look at the image before showing the user.
    """
    pr = printing.resolve_printer(printer)  # bad printer spec fails before anything runs
    pdir = _project_dir(project)
    pdir.mkdir(parents=True, exist_ok=True)
    vs = _versions(pdir)
    vdir = pdir / f"v{(int(vs[-1].name[1:]) + 1 if vs else 1):03d}"
    vdir.mkdir()
    (vdir / "model.py").write_text(code, encoding="utf-8")
    (vdir / "note.txt").write_text(note, encoding="utf-8")
    argv = [sys.executable, "-m", "spatialvibe_mcp._runner", str(vdir / "model.py"), str(vdir)]
    try:
        p = subprocess.run(_sandbox_cmd(vdir, argv), capture_output=True, text=True,
                           timeout=TIMEOUT, cwd=vdir, env=_child_env())
    except subprocess.TimeoutExpired:
        res = {"ok": False, "error": f"timed out after {TIMEOUT}s"}
    else:
        lines = [ln for ln in p.stdout.splitlines() if ln.startswith("{")]
        try:
            res = json.loads(lines[-1]) if lines else None
        except ValueError:
            res = None
        if not isinstance(res, dict) or (res.get("ok") and p.returncode != 0):
            res = {"ok": False, "error": (p.stderr or p.stdout)[-3000:] or f"runner exited {p.returncode}"}
    # the script may have touched its folder; keep the source exactly as submitted
    _write_atomic(vdir / "model.py", code)
    _write_atomic(vdir / "note.txt", note)
    if res.get("ok"):
        try:
            res["printer"] = pr
            for info in res["parts"].values():
                info["print"].update(printing.fit(info["print"], pr))
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            res = {"ok": False, "error": f"runner result malformed: {e!r}"}
    if not res.get("ok"):  # never leave a half-exported build that looks usable
        for f in [*vdir.glob("part_*"), *vdir.glob("print_*"), *vdir.glob("ctx_*")]:
            if f.is_symlink() or not f.is_dir():
                f.unlink(missing_ok=True)
    _write_atomic(vdir / "result.json", json.dumps(res, ensure_ascii=False, indent=1))
    res.update(project=project, version=int(vdir.name[1:]), folder=str(vdir))
    if res.get("ok"):
        res["files"] = sorted(str(f) for f in vdir.glob("part_*.*"))
        res["print_files"] = sorted(str(f) for f in vdir.glob("print_*.stl"))
        if pr is None:
            res["printer_note"] = "printer not set: ask the user which printer (model or build volume) before export"
    return res


@mcp.tool()
def preview(project: str, version: int | None = None) -> list:
    """Render four views (front-oblique, rear-oblique, right side, below) of a version.

    Parts are opaque orange/red/blue, context is translucent grey. Inspect the image
    yourself: check that parts sit where intended relative to the context, nothing floats,
    and features (holes, slots, walls) exist. Defaults to the latest version.
    """
    vdir = _built_version_dir(project, version)
    argv = [sys.executable, "-m", "spatialvibe_mcp._render", str(vdir)]
    p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, env=_child_env())
    png = vdir / "preview.png"
    if p.returncode != 0 or not png.exists():
        raise RuntimeError(p.stderr[-2000:])
    return [Image(path=str(png)), f"{project} {vdir.name}: {png}"]


@mcp.tool()
def publish_ar(project: str, version: int | None = None, include_context: bool = True) -> dict:
    """Make a real-scale USDZ of a version and put it where the user's iPhone can open it in AR.

    With include_context the surroundings are included translucent, so the user can line the
    model up with the real object (e.g. the pipe). Default target is iCloud Drive
    (Files app → iCloud Drive → SpatialVibe), which works on any network.
    """
    vdir = _built_version_dir(project, version)
    usdz = build_usdz(vdir, include_context)
    fname = f"{project}_{vdir.name}.usdz"
    if PUBLISH == "icloud":
        if not ICLOUD.exists():
            raise RuntimeError("iCloud Drive not found on this Mac; set SPATIALVIBE_PUBLISH=dir:/path")
        dest_dir = ICLOUD / "SpatialVibe"
        how = f"iPhone の「ファイル」→ iCloud Drive → SpatialVibe → {fname} をタップ（100% 表示で実寸）"
    elif PUBLISH.startswith("dir:"):
        dest_dir = Path(PUBLISH[4:]).expanduser()
        how = f"{dest_dir / fname} を iPhone で開く"
    else:
        raise RuntimeError(f"unknown SPATIALVIBE_PUBLISH={PUBLISH!r}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(usdz, dest_dir / fname)
    return {"usdz": str(usdz), "published": str(dest_dir / fname), "how_to_open": how,
            "size_m": usdz_size_m(usdz), "include_context": include_context}


@mcp.tool()
def export_print(project: str, version: int | None = None, printer: str = "",
                 quantities: dict[str, int] | None = None, material: str = "",
                 hardware: list[str] | None = None, notes: list[str] | None = None,
                 part_notes: dict[str, str] | None = None) -> dict:
    """Collect everything needed to print a version into one local folder and a ZIP.

    Contents: stl/ (each part turned to its print pose, resting on z=0, mm), step/ (assembled
    pose, for editing), source/model.py, manifest.json and PRINT_GUIDE_ja.txt. Context is never
    included. Pass only what is actually known — quantities per part, material, hardware
    (bolts, nuts…; [] means none), notes, part_notes; anything omitted is listed as unconfirmed.
    `printer` overrides the one used at build time. Refuses failed builds, invalid solids and
    parts that exceed the build volume in their print pose (returns ok=false with details).
    Files stay on this Mac; nothing is sent to a slicer, printer or iCloud.
    """
    vdir = _built_version_dir(project, version)
    res = _result(vdir)
    pr = printing.resolve_printer(printer, res.get("printer"))
    return printing.make_bundle(project, vdir, res, pr, quantities=quantities, material=material,
                                hardware=hardware, notes=notes, part_notes=part_notes)


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
        r = _result(v)
        out.append({"version": int(v.name[1:]), "note": (v / "note.txt").read_text(encoding="utf-8"),
                    "ok": r.get("ok"), "parts": {k: x.get("bbox_mm", {}).get("size") for k, x in r.get("parts", {}).items()}})
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
