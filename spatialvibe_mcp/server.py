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
    if not PROJECT.match(project):
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


def _built_version_dir(project: str, version) -> Path:
    """Like _version_dir, but the version must have built successfully."""
    v = _version_dir(project, version)
    if not any(v.glob("part_*.stl")):
        raise ValueError(f"{project} {v.name} did not build (see build_model's error); fix the script and rebuild")
    return v


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
    Returns per-part validity, solid count, volume, bounding box, round holes, whether it fits
    the print bed ($SPATIALVIBE_BED, default 256×256×256 mm), the overall size of the printed
    parts, any overlap between parts and context (usually a design error; faces that only touch
    are not reported), and the paths of the STL/STEP files.
    Always call `preview` afterwards and look at the image before showing the user.
    """
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
        res = json.loads(lines[-1]) if lines else {"ok": False, "error": (p.stderr or p.stdout)[-3000:]}
    (vdir / "result.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    res.update(project=project, version=int(vdir.name[1:]), folder=str(vdir))
    if res.get("ok"):
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
        p = subprocess.run(argv, capture_output=True, text=True, timeout=TIMEOUT, env=_child_env())
        png = vdir / name
        if p.returncode != 0 or not png.exists():
            raise RuntimeError(f"{mod}: {p.stderr[-2000:]}")
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
    res = json.loads((vdir / "result.json").read_text(encoding="utf-8"))
    parts_m = [round(v / 1000, 4) for v in res.get("parts_size_mm", [])]
    return {"usdz": str(usdz), "published": str(dest_dir / fname), "how_to_open": how,
            "size_m": usdz_size_m(usdz), "parts_size_m": parts_m, "include_context": include_context,
            "note": "size_m includes context; quote parts_size_m as the size of what is printed"}


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
        r = json.loads((v / "result.json").read_text()) if (v / "result.json").exists() else {}
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
