"""SpatialVibe MCP server (stdio, or Streamable HTTP behind the gateway: see _remote.py).

Tools: build_model, preview, publish_ar, export_print, get_print_job, list_projects, get_code.
Data lives in $SPATIALVIBE_HOME (default: <repo>/data/mcp_projects), one folder per
project and one numbered folder per version (v001, v002, ...).
"""
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import secrets
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import printing
from ._ar_export import export_snapshot
from ._ar_publish import PublicationError, publish as cloud_publish, settings as cloud_settings
from ._isolation import child_environment, sandbox_command

REPO = Path(__file__).resolve().parent.parent
HOME = Path(os.environ.get("SPATIALVIBE_HOME", REPO / "data" / "mcp_projects")).expanduser()
ICLOUD = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
PUBLISH = os.environ.get("SPATIALVIBE_PUBLISH", "icloud")   # icloud | dir:/path | cloudflare
KEEP = os.environ.get("SPATIALVIBE_AR_KEEP", "")           # with cloudflare: also keep a copy: icloud | dir:/path
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
        r = json.loads(_safe_text(vdir / "result.json"))
    except (OSError, ValueError):
        return {}
    if not isinstance(r, dict):
        return {}
    if r.get("ok") is True and "parts_size_mm" not in r:
        size = _overall_size(r.get("parts"))
        if size is not None:   # versions built by older servers; in memory only, the file is not rewritten
            r["parts_size_mm"] = size
    return r


def _overall_size(parts) -> list | None:
    """Overall size of all parts from their bbox min/max (the runner's own formula), or None."""
    if not isinstance(parts, dict) or not parts:
        return None
    boxes = []
    for info in parts.values():
        box = info.get("bbox_mm") if isinstance(info, dict) else None
        lo, hi = (box or {}).get("min"), (box or {}).get("max")
        if not all(isinstance(v, list) and len(v) == 3 and all(
                isinstance(c, (int, float)) and not isinstance(c, bool) and math.isfinite(c) for c in v)
                for v in (lo, hi)) or any(h < l for l, h in zip(lo, hi)):
            return None
        boxes.append((lo, hi))
    return [round(max(h[i] for _, h in boxes) - min(l[i] for l, _ in boxes), 1) for i in range(3)]


def _safe_text(path: Path) -> str:
    """Never let a generated symlink redirect a trusted-parent file read."""
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise SpatialVibeError("Project file is not a regular file")
            text = stream.read(8 * 1024 * 1024 + 1)
            if len(text) > 8 * 1024 * 1024:
                raise SpatialVibeError("Project file is too large")
            return text.decode("utf-8")
    finally:
        os.close(directory)


def _atomic_bytes(path: Path, body: bytes) -> None:
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


def _write_json(path: Path, value) -> None:
    _atomic_bytes(path, json.dumps(value, ensure_ascii=False, indent=1).encode("utf-8"))


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
    """Fail closed; generated code cannot read uploader credentials or other projects."""
    try:
        return sandbox_command(out, REPO, argv)
    except (RuntimeError, ValueError) as exc:
        raise SpatialVibeError(str(exc)) from None


def _child_env(runtime: Path):
    env = child_environment(runtime, REPO)
    # The build's only nonsecret user setting; never inherit arbitrary parent env.
    raw = os.environ.get("SPATIALVIBE_BED", "256,256,256")
    try:
        dimensions = [float(value) for value in raw.split(",")]
        if len(dimensions) == 3 and all(0 < value <= 10000 for value in dimensions):
            env["SPATIALVIBE_BED"] = ",".join(map(str, dimensions))
    except ValueError:
        pass
    return env


def _run_isolated(vdir: Path, argv):
    command = _sandbox_cmd(vdir, argv)
    with tempfile.TemporaryDirectory(prefix=".runtime-", dir=vdir) as runtime:
        return subprocess.run(command, capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              timeout=TIMEOUT, cwd=vdir, env=_child_env(Path(runtime)), close_fds=True)


@mcp.tool()
def build_model(project: str, code: str, note: str = "", compare_to: int | None = None,
                printer: str = "") -> dict:
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
    `changes` compares with the previous good version, or with `compare_to` (e.g. the version the
    user already printed, after some drafts) and is saved in result.json.
    Optionally `print_orientation = {"part": (rx, ry, rz)}` (degrees, like build123d Rot) or
    `print_pose = {"part": "-X" | Rot(...)}` turns a part to its print pose; preview/AR stay assembled.
    `printer`: "a1mini" (Bambu Lab A1 mini, 180x180x180) or a build volume "WxDxH" in mm; empty uses
    $SPATIALVIBE_PRINTER, else each part's `print.fit` is printer_not_set (ask the user, never guess).
    Each part's `print` has the pose, size and fit: fits / exceeds / printer_not_set (exceeds is about
    that pose only).
    A build that fails leaves no part files behind and cannot be previewed or published.
    Always call `preview` afterwards and look at both images before showing the user.
    """
    try:
        pr = printing.resolve_printer(printer)  # a bad printer spec fails before anything runs
    except ValueError as exc:
        raise SpatialVibeError(str(exc)) from None
    vdir = _new_version_dir(_project_dir(project))
    (vdir / "model.py").write_text(code, encoding="utf-8")
    (vdir / "note.txt").write_text(note, encoding="utf-8")
    stage = vdir / "_build"           # the runner writes here; files move up only on success
    stage.mkdir()
    result_file = stage / "_result.json"
    argv = [sys.executable, "-m", "spatialvibe_mcp._runner", str(vdir / "model.py"), str(stage), str(result_file)]
    try:
        p = _run_isolated(vdir, argv)
    except subprocess.TimeoutExpired:
        res = {"ok": False, "error": f"timed out after {TIMEOUT}s; nothing was kept"}
    else:
        try:
            res = json.loads(_safe_text(result_file))
        except (OSError, ValueError):
            res = None
        if p.returncode != 0 or not isinstance(res, dict):
            tail = (p.stderr or "").strip()[-2500:] or "no output"
            res = {"ok": False, "error": f"the build process exited with code {p.returncode} before finishing. {tail}"}
    if res.get("ok") is True:
        candidates = [] if stage.is_symlink() else [f for f in stage.iterdir()
                        if f.name.startswith(("part_", "ctx_", "print_", "pose"))]
        if not candidates or any(not stat.S_ISREG(f.lstat().st_mode) for f in candidates):
            res = {"ok": False, "error": "Unsafe or missing generated output; nothing was kept"}
        else:
            for f in candidates:
                f.replace(vdir / f.name)
    shutil.rmtree(stage, ignore_errors=True)
    if res.get("ok") is True:
        try:
            res["printer"] = pr
            for info in res["parts"].values():
                info["print"].update(printing.fit(info["print"], pr))
        except (KeyError, TypeError, AttributeError, ValueError) as exc:
            res = {"ok": False, "error": f"runner result malformed: {type(exc).__name__}"}
            for f in vdir.iterdir():
                if f.name.startswith(("part_", "ctx_", "print_", "pose")) and (f.is_symlink() or not f.is_dir()):
                    f.unlink()
    _write_json(vdir / "result.json", res)
    res.update(project=project, version=int(vdir.name[1:]), folder=str(vdir))
    if res.get("ok") is True:
        _write_print_job(project, vdir, res)
        res["files"] = sorted(str(f) for f in vdir.iterdir() if f.name.startswith(("part_", "print_", "ctx_")))
        res["print_files"] = sorted(str(f) for f in vdir.glob("print_*.stl"))
        if pr is None:
            res["printer_note"] = "printer not set: ask the user which printer (model or build volume) before export"
        if compare_to is not None:   # e.g. the version the user actually printed, not the last draft
            prev = _built_version_dir(project, compare_to)
        else:
            prev = next((v for v in reversed(_versions(vdir.parent)) if v.name < vdir.name
                         and _read_result(v).get("ok") is True), None)
        if prev is not None:
            res["changes"] = _diff(_read_result(prev), res, int(prev.name[1:]))
            res["changes"]["vs_printed"] = compare_to is not None   # only then may the sheet say "keep"
            saved = _read_result(vdir)
            saved["changes"] = res["changes"]
            _write_json(vdir / "result.json", saved)
    return res


PRINT_JOB_SCHEMA = "spatialvibe.print_job/1"


def _write_print_job(project: str, vdir: Path, res: dict) -> None:
    """print_job.json: everything an AI (or a person) needs to slice and print this version
    without reading the sheets — files, pose, settings, the fits that must hold, what to buy."""
    labels = res.get("labels") or {}
    ps = res.get("print_settings") or {}
    sup = set(ps.get("supports") or [])
    parts = []
    for name, info in (res.get("parts") or {}).items():
        stl = f"print_{name}.stl" if (vdir / f"print_{name}.stl").exists() else f"part_{name}.stl"
        fits = [{k: d[k] for k in ("label", "kind", "value", "unit", "expect", "tol", "min", "max", "vs", "vs_label")
                 if d.get(k) is not None}
                for d in res.get("dims") or [] if d.get("part") == name and d.get("value") is not None]
        parts.append({
            "name": name, "label": labels.get(name, name), "quantity": 1,
            "stl": stl, "step": f"part_{name}.step",
            "down_face": info.get("print_down", "as modelled"),
            "size_mm": info.get("print_size_mm") or (info.get("bbox_mm") or {}).get("size"),
            "volume_cm3": info.get("volume_cm3"),
            "supports": (name in sup) if ps else None,
            "estimated_minutes": info.get("print_minutes"),
            "holes": [{"d": h["d"], "through": h.get("through")} for h in info.get("hole_list") or []],
            "fits": fits,
        })
    job = {
        "schema": PRINT_JOB_SCHEMA, "project": project, "version": int(vdir.name[1:]),
        "plate": dict(res.get("plate") or {}, bed_mm=res.get("bed_mm")),
        "settings": {"material": ps.get("material"), "infill_percent": ps.get("infill"),
                     "layer_mm": ps.get("layer"), "walls": ps.get("walls"), "note": ps.get("note")} if ps else None,
        "parts": parts,
        "keep_already_printed": ((res.get("changes") or {}).get("unchanged_parts")
                                 if (res.get("changes") or {}).get("vs_printed") else []),
        "hardware": res.get("hardware") or [], "checks_before_print": res.get("checks") or [],
        "assembly_steps": [st["text"] for st in res.get("steps") or []],
        "notes_for_ai": [
            "Units mm. Each STL/3MF is already in print pose: do not rotate or scale.",
            "settings null = not decided yet: ask the user (material for sun/heat, printer).",
            "estimated_minutes is a rough volume formula; quote the slicer's time instead once sliced.",
            "fits are what must hold after printing (hole Ø, slot widths). Do not scale the model to "
            "fix them; use the slicer's hole/XY compensation if this printer is known to print tight.",
            "Start a print only after the user confirms. Parts in keep_already_printed are not reprinted.",
        ],
    }
    _write_json(vdir / "print_job.json", job)
    res["print_job"] = str(vdir / "print_job.json")


def _diff(old: dict, new: dict, old_version: int) -> dict:
    """What changed since the previous good version: parts, sizes, holes and fit dims, so an edit
    ("幅だけ10mm", a corrected number) can be checked and the user told which parts to reprint."""
    lines, same = [], []
    op, np_ = old.get("parts", {}), new.get("parts", {})
    for n in sorted(set(op) | set(np_)):
        if n not in np_:
            lines.append(f"{n}: removed")
            continue
        if n not in op:
            lines.append(f"{n}: new part")
            continue
        a, b = op[n], np_[n]
        sa, sb = a.get("bbox_mm", {}).get("size"), b.get("bbox_mm", {}).get("size")
        ch = []
        if sa and sb and any(abs(x - y) > 0.05 for x, y in zip(sa, sb)):
            ch.append("size " + " × ".join(f"{x:g}" for x in sa) + " → " + " × ".join(f"{y:g}" for y in sb))
        if abs((a.get("volume_cm3") or 0) - (b.get("volume_cm3") or 0)) > 0.01 and not ch:
            ch.append("shape changed (same outer size)")
        ha, hb = list(a.get("hole_list") or []), list(b.get("hole_list") or [])
        moved, gone = [], []
        for h in ha:
            same_d = [g for g in hb if abs(g["d"] - h["d"]) < 0.05 and g["axis"] == h["axis"]]
            if not same_d:
                gone.append(h)
                continue
            g = min(same_d, key=lambda g: sum((g["at"][i] - h["at"][i]) ** 2 for i in range(3)))
            hb.remove(g)
            if any(abs(g["at"][i] - h["at"][i]) > 0.05 for i in range(3)):
                moved.append(f"Ø{h['d']:g} {tuple(h['at'])} → {tuple(g['at'])}")
        if moved:
            ch.append("holes moved: " + "; ".join(moved[:6]))
        if gone:
            ch.append("holes removed: " + ", ".join(f"Ø{h['d']:g} {tuple(h['at'])}" for h in gone[:6]))
        if hb:
            ch.append("holes added: " + ", ".join(f"Ø{h['d']:g} {tuple(h['at'])}" for h in hb[:6])
                      + (f" (+{len(hb) - 6} more)" if len(hb) > 6 else ""))
        kept = len(ha) - len(gone) - len(moved)
        if ch and kept:   # say plainly what did NOT move: screw holes already drilled in a wall
            ch.append(f"{kept} hole(s) unchanged")
        if ch:
            lines.append(f"{n}: " + " / ".join(ch) + " → reprint")
        else:
            same.append(n)
    od = {(d.get("part"), d.get("label")): d.get("value") for d in old.get("dims") or []}
    for d in new.get("dims") or []:
        k = (d.get("part"), d.get("label"))
        if k in od and od[k] is not None and d.get("value") is not None and abs(od[k] - d["value"]) > 0.05:
            lines.append(f"dim {d.get('label')}: {od[k]:g} → {d['value']:g}")
    return {"since_version": old_version, "changed": lines,
            "unchanged_parts": same, "note": "unchanged parts need not be reprinted if already printed"}


@mcp.tool()
def preview(project: str, version: int | None = None) -> list:
    """Render the 4-view picture and the dimension sheet of a version (latest by default).

    1) Four views (front-oblique, rear-oblique, right side, below), framed on the printed parts;
       parts in distinct opaque colours, context translucent grey and cut to the frame.
    2) Dimension sheet for the user's phone: part count, overall size, and per part the size
       W×D×H mm, round holes, whether it fits the print bed, top/front views with dimension lines,
       then the script's `hardware` and `checks` lists.
    3) sheet.png is one summary page (what to buy, what to check, the key fit dimensions — `"key": True`
       on a dim, else the first three — and the parts in place); sheet_detail.png has every part's
       fit dimensions with zoomed panels. Look at all of them; send the user sheet.png (and
       sheet_detail.png for whoever prints or wants detail).
    4) When the script sets `print_settings` or `steps`, also sheet_build.png: how to print
       (print_plate.3mf + settings + time) and one numbered picture per assembly step.
    """
    vdir = _built_version_dir(project, version)
    out = []
    for mod, name in (("_render", "preview.png"), ("_sheet", "sheet.png")):
        argv = [sys.executable, "-m", f"spatialvibe_mcp.{mod}", str(vdir)]
        p = _run_isolated(vdir, argv)
        png = vdir / name
        if p.returncode != 0 or not png.exists():
            raise SpatialVibeError(f"drawing the {name} failed: {p.stderr.strip()[-1500:] or 'no output'}")
        out.append(png)
    detail = vdir / "sheet_detail.png"
    imgs = [Image(path=str(out[0])), Image(path=str(out[1])), Image(path=str(detail))]
    text = f"{project} {vdir.name}: views {out[0]} / summary sheet {out[1]} / detailed sheet {detail}"
    build = vdir / "sheet_build.png"   # page 3 (print plate + assembly steps), when the script has them
    build.unlink(missing_ok=True)
    argv = [sys.executable, "-m", "spatialvibe_mcp._steps", str(vdir)]
    p = _run_isolated(vdir, argv)
    if p.returncode != 0:
        raise SpatialVibeError(f"drawing sheet_build.png failed: {p.stderr.strip()[-1500:] or 'no output'}")
    if build.exists():
        imgs.append(Image(path=str(build)))
        text += f" / print and assembly {build}"
    return imgs + [text]


@mcp.tool()
def publish_ar(project: str, version: int | None = None, include_context: bool = True) -> dict:
    """Make a real-scale USDZ of a version and put it where the user's iPhone can open it in AR.

    With include_context the surroundings are included translucent, so the user can line the
    model up with the real object (e.g. the pipe). Default target is iCloud Drive
    (Files app → iCloud Drive → SpatialVibe), which works on any network.
    SPATIALVIBE_PUBLISH=cloudflare uses the dedicated AR Worker and returns an expiring
    HTTPS link; with SPATIALVIBE_AR_KEEP=icloud (or dir:/path) the same USDZ is also kept there
    (`kept` in the result), so every version stays on the phone after the link expires.
    HTTPS link. It requires trusted-parent upload configuration and supported isolation.
    If the script set ar_floor, the model gets a floor plate at that height: tell the user to aim
    the phone at that floor before tapping AR, then slide it until the grey context lines up.
    """
    vdir = _built_version_dir(project, version)
    res = _read_result(vdir)
    floor_z = res.get("ar_floor_z") if include_context else None
    config = None
    if PUBLISH == "cloudflare":
        # Validate the supported isolation boundary before accessing runtime auth.
        _sandbox_cmd(vdir, [sys.executable, "-c", "pass"])
        try:
            config = cloud_settings()
        except PublicationError as exc:
            raise SpatialVibeError(str(exc)) from None
    elif PUBLISH != "icloud" and not PUBLISH.startswith("dir:"):
        raise SpatialVibeError(f"unknown SPATIALVIBE_PUBLISH={PUBLISH!r}")
    try:
        snapshot = export_snapshot(vdir, include_context, floor_z,
                                   **({"max_bytes": config.max_bytes} if config else {}))
    except ValueError as exc:
        if str(exc).startswith("ar_floor "):
            raise SpatialVibeError(str(exc)) from None
        raise SpatialVibeError("AR export failed; check the model files and configured upload limit") from None
    except OSError:
        raise SpatialVibeError("AR export failed; check the model files and configured upload limit") from None
    usdz = vdir / "model.usdz"
    _atomic_bytes(usdz, snapshot.body)
    pm = [round(v / 1000, 4) for v in res.get("parts_size_mm", [0, 0, 0])]
    sx, sy_up, sz = snapshot.scene_size_m
    metadata = {"parts_size_m": {"x_width": pm[0], "y_depth": pm[1], "z_height": pm[2]},
                "scene_size_m": {"x_width": sx, "y_depth": sz, "z_height": sy_up},
                "include_context": include_context, "ar_floor_mm": floor_z}
    fname = f"{project}_{vdir.name}{'' if include_context else '_parts-only'}.usdz"
    if PUBLISH == "icloud":
        if not ICLOUD.exists():
            raise SpatialVibeError("iCloud Drive not found on this Mac; set SPATIALVIBE_PUBLISH=dir:/path")
        dest_dir = ICLOUD / "SpatialVibe"
        how = f"iPhone の「ファイル」→ iCloud Drive → SpatialVibe → {fname} をタップ（100% 表示で実寸）"
    elif PUBLISH.startswith("dir:"):
        dest_dir = Path(PUBLISH[4:]).expanduser()
        how = f"{dest_dir / fname} を iPhone で開く"
    else:  # cloudflare; local destinations retain their existing behavior above
        try:
            public = cloud_publish(snapshot.body, metadata, config)
        except PublicationError as exc:
            raise SpatialVibeError(str(exc)) from None
        how = "iPhone の Safari で published のリンクを開き、画像をタップして AR を開く"
    where = f"（{res['origin']}）" if res.get("origin") else ""
    moves = ("1本指でずらす・2本指でひねって回すのは OK。縮尺変更を制限する設定だが実機では未検証。上下には動かせない"
             if config else "1本指でずらす・2本指でひねって回すのは OK、つまんで広げる/縮めるのは NG（100% が実物大）。上下には動かせない")
    if floor_z is not None and floor_z < -5:
        how += (f"。取付け場所の手前の床にスマホを向けてから AR。黄色い板が床に出て、細い柱の先＝取付け点{where}が"
                f"床から {abs(floor_z) / 10:g} cm の高さに出る。灰色の周囲が本物に重なるまで動かす（{moves}）")
    else:
        how += f"。置きたい床や台にスマホを向けてから AR。灰色の周囲が本物に重なるまで動かす（{moves}）"
    if config:
        published = public["url"]
        how += "。リンクを知っている人は期限内に閲覧でき、保存したコピーは期限後も残る"
        extra = {"expires_at": public["expires_at"], "sha256": public["sha256"]}
        keep_dir = _keep_dir()
        if keep_dir is not None:
            keep_dir.mkdir(parents=True, exist_ok=True)
            _atomic_bytes(keep_dir / fname, snapshot.body)
            extra["kept"] = str(keep_dir / fname)
            how += f"。同じファイルを {keep_dir.name}/ にも残した（iPhone の「ファイル」から期限後も開ける）"
    else:
        dest_dir.mkdir(parents=True, exist_ok=True)
        _atomic_bytes(dest_dir / fname, snapshot.body)
        published = str(dest_dir / fname)
        extra = {}
    # size_m: the USDZ's own extent in metres, USD axes (x, y-up, z), kept for older callers.
    return {"usdz": str(usdz), "published": published, "how_to_open": how, "size_m": [sx, sy_up, sz],
            **metadata, **extra,
            "note": "quote parts_size_m (what is printed); scene_size_m also contains the context. "
                    "Both use the script's axes: x = width, y = depth, z = height."}


def _keep_dir() -> Path | None:
    """Where a Cloudflare publication is also kept (SPATIALVIBE_AR_KEEP), or None."""
    if not KEEP:
        return None
    if KEEP == "icloud":
        if not ICLOUD.exists():
            raise SpatialVibeError("SPATIALVIBE_AR_KEEP=icloud but iCloud Drive not found on this Mac")
        return ICLOUD / "SpatialVibe"
    if KEEP.startswith("dir:"):
        return Path(KEEP[4:]).expanduser()
    raise SpatialVibeError(f"unknown SPATIALVIBE_AR_KEEP={KEEP!r} (icloud | dir:/path)")


@mcp.tool()
def export_print(project: str, version: int | None = None, printer: str = "",
                 quantities: dict[str, int] | None = None, material: str = "",
                 hardware: list[str] | None = None, notes: list[str] | None = None,
                 part_notes: dict[str, str] | None = None, include_zip: bool = False) -> dict:
    """Hand a finished version over to print preparation: one local folder of files + conditions.

    Folder: stl/ (each part turned to its print pose, resting on z=0, mm), step/ (assembled
    pose, for editing), source/model.py, manifest.json (the conditions: printer, material,
    per-part quantity/pose/size/fit, hardware, notes, unconfirmed), PRINT_GUIDE_ja.txt (the
    same for the user) and AI_HANDOFF.txt (short text for another AI). Context is never
    included. Pass only what is actually known — quantities per part, material, hardware
    (bolts, nuts…; [] means none), notes, part_notes; anything omitted is listed as unconfirmed.
    `printer` overrides the one used at build time. Refuses failed builds, invalid solids and
    parts that exceed the build volume in their print pose (returns ok=false with details).
    The result has absolute paths to every file, the manifest itself, `handoff` and
    `next_steps`. This MCP does not slice or print; continue with a slicer/printer integration
    if you have one and show the user what was actually set and estimated.
    A ZIP is made only with include_zip=true (for sharing); otherwise a ZIP left by an earlier
    export of this version is removed so it is never mistaken for the current files.
    """
    vdir = _built_version_dir(project, version)
    res = _read_result(vdir)
    try:
        pr = printing.resolve_printer(printer, res.get("printer"))
        return printing.make_bundle(project, vdir, res, pr, quantities=quantities, material=material,
                                    hardware=hardware, notes=notes, part_notes=part_notes,
                                    include_zip=bool(include_zip))
    except ValueError as exc:
        raise SpatialVibeError(str(exc)) from None


@mcp.tool()
def get_print_job(project: str, version: int | None = None) -> dict:
    """The print job of a version (latest by default), for whoever prints it — usually an AI with
    a slicer or printer tool. Contains absolute file paths (print_plate.3mf, each part's STL and
    STEP in print pose), settings, the fit dimensions that must hold, hardware, checks and the
    assembly steps. Never start a print without the user's go-ahead."""
    vdir = _built_version_dir(project, version)
    f = vdir / "print_job.json"
    if not f.exists():
        _write_print_job(project, vdir, _read_result(vdir))
    job = json.loads(_safe_text(f))
    job["folder"] = str(vdir)
    if job.get("plate", {}).get("file"):
        job["plate"]["path"] = str(vdir / job["plate"]["file"])
    for p_ in job["parts"]:
        p_["stl_path"], p_["step_path"] = str(vdir / p_["stl"]), str(vdir / p_["step"])
    return job


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
        note = _safe_text(v / "note.txt") if (v / "note.txt").exists() else ""
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
    return _safe_text(_version_dir(project, version) / "model.py")


@mcp.prompt()
def design_session(goal: str = "") -> str:
    """Start a fit-for-purpose design session (photos of the space + the thing to place)."""
    return INSTRUCTIONS + (f"\n\nユーザーの目的: {goal}" if goal else "")


def main():
    HOME.mkdir(parents=True, exist_ok=True)
    transport = os.environ.get("SPATIALVIBE_TRANSPORT", "stdio")
    if transport == "stdio":
        mcp.run()
    elif transport == "http":
        from ._remote import RemoteError, serve, settings as remote_settings
        try:
            config = remote_settings()
        except RemoteError as exc:
            raise SystemExit(f"spatialvibe http mode refused: {exc}") from None
        serve(mcp, config)
    else:
        raise SystemExit("SPATIALVIBE_TRANSPORT must be stdio or http")


if __name__ == "__main__":
    main()
