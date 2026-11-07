"""Check the install and print how to connect Claude. Never edits any Claude/MCP config.

Usage: .venv/bin/python -m spatialvibe_mcp.doctor [--printer a1mini] [--json] [--no-smoke]
"""
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

from . import printing
from ._build import build_in_scratch

REPO = Path(__file__).resolve().parent.parent
PY = REPO / ".venv" / "bin" / "python"
DEFAULT_HOME = REPO / "data" / "mcp_projects"
DESKTOP_CONFIG = Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"


def _env(printer):
    env = {"PYTHONPATH": str(REPO)}
    if printer:
        printing.parse_printer(printer)  # reject unknown printers here, not later in Claude
        env["SPATIALVIBE_PRINTER"] = printer
    return env


def desktop_config(printer: str | None = None) -> dict:
    """Complete claude_desktop_config.json content for this checkout."""
    return {"mcpServers": {"spatialvibe": {"command": str(PY), "args": ["-m", "spatialvibe_mcp"],
                                           "env": _env(printer)}}}


def claude_code_command(printer: str | None = None) -> str:
    envs = " ".join(f"-e {k}={shlex.quote(v)}" for k, v in _env(printer).items())
    return f"claude mcp add --scope user {envs} -- spatialvibe {shlex.quote(str(PY))} -m spatialvibe_mcp"


def _requirements():
    for ln in (REPO / "requirements.txt").read_text().splitlines():
        if "==" in ln:
            name, ver = ln.strip().split("==")
            yield name, ver


def checks(smoke=True, printer=None):
    """Yield (ok, label, detail); ok is True, False or None (information / warning)."""
    v = sys.version_info
    yield v[:2] == (3, 12), "Python 3.12", f"{sys.version.split()[0]} at {sys.executable}"
    yield Path(sys.prefix).resolve() == (REPO / ".venv").resolve(), "repo .venv Python", f"expected {PY}"
    for name, want in _requirements():
        try:
            got = metadata.version(name)
        except metadata.PackageNotFoundError:
            yield False, f"package {name}", "not installed — run scripts/setup.sh"
            continue
        yield got == want, f"package {name}", f"{got} (requirements.txt: {want})"
    if sys.platform == "darwin":
        yield bool(shutil.which("sandbox-exec")), "sandbox-exec", "isolates model scripts (required)"
    else:
        yield False, "sandbox-exec", "not macOS: the server refuses to run model scripts without it"

    home = Path(os.environ.get("SPATIALVIBE_HOME", DEFAULT_HOME)).expanduser().absolute()
    yield _data_folder(home)
    if home.resolve() != DEFAULT_HOME.resolve() and DEFAULT_HOME.is_dir() and any(DEFAULT_HOME.iterdir()):
        yield None, "older projects", f"{DEFAULT_HOME} has projects not visible with SPATIALVIBE_HOME={home}"

    pub = os.environ.get("SPATIALVIBE_PUBLISH", "icloud")
    icloud = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
    if pub == "icloud":
        yield (True if icloud.exists() else None), "AR target", (
            "iCloud Drive/SpatialVibe" if icloud.exists() else "iCloud Drive not found; set SPATIALVIBE_PUBLISH=dir:/path")
    elif pub == "cloudflare":
        yield None, "AR target", "Cloudflare AR Worker (expiring link; see AR_PUBLICATION.md and tools/ar_mcp_launch.py)"
    else:
        yield None, "AR target", pub

    spec = printer or os.environ.get("SPATIALVIBE_PRINTER", "")
    if spec:
        try:
            p = printing.parse_printer(spec)
            yield True, "printer", f"{p['name']} {p['build_volume_mm']} mm" + ("" if printer else " (environment)")
        except ValueError as e:
            yield False, "printer", str(e)
    else:
        yield None, "printer", "not set — Claude will ask (or add --printer to the config below)"

    if smoke:
        yield _smoke()


def _data_folder(home: Path):
    """OK if home is a writable folder, or does not exist yet but can be created (first install)."""
    if home.is_dir():
        n = len([p for p in home.iterdir() if p.is_dir()])
        return os.access(home, os.W_OK | os.X_OK), "data folder", f"{home} ({n} projects)"
    if home.exists() or home.is_symlink():
        return False, "data folder", f"{home} exists but is not a folder"
    anc = home.parent
    while not anc.exists() and not anc.is_symlink() and anc != anc.parent:
        anc = anc.parent
    if not anc.is_dir():
        return False, "data folder", f"cannot create {home}: {anc} is not a folder"
    if not os.access(anc, os.W_OK | os.X_OK):
        return False, "data folder", f"cannot create {home}: {anc} is not writable"
    return True, "data folder", f"{home} (not created yet; made on first server start)"


def _smoke():
    """Check a minimal build through the same isolated path as the MCP tool."""
    code = ("from build123d import Box\nparts = {'block': Box(20, 10, 5)}\n"
            "print_orientation = {'block': (0, 90, 0)}\n")
    with tempfile.TemporaryDirectory(prefix="svdoctor-") as d:
        try:
            r = build_in_scratch(Path(d), code, REPO, 180)
        except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return False, "test build", str(exc)[:300]
        ok = r.get("ok") and (Path(d) / "print_block.stl").is_file()
        size = r.get("parts", {}).get("block", {}).get("print", {}).get("size_mm_exact")
        return bool(ok), "test build", f"20x10x5 block, print size {size}" if ok else str(r.get("error"))[:300]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--printer", help="add SPATIALVIBE_PRINTER to the printed config (e.g. a1mini or 256x256x256)")
    ap.add_argument("--json", action="store_true", help="print only the Claude Desktop JSON")
    ap.add_argument("--no-smoke", action="store_true", help="skip the test build")
    a = ap.parse_args(argv)
    try:
        cfg = desktop_config(a.printer)
    except ValueError as e:
        ap.error(str(e))
    if a.json:
        print(json.dumps(cfg, indent=2, ensure_ascii=False))
        return 0
    failed = 0
    for ok, label, detail in checks(smoke=not a.no_smoke, printer=a.printer):
        mark = {True: "OK  ", False: "NG  ", None: "--  "}[ok]
        failed += ok is False
        print(f"{mark}{label}: {detail}")
    print("\n# Claude Code (run it yourself; this tool does not register anything):")
    print(claude_code_command(a.printer))
    print(f"\n# Claude Desktop: merge into {DESKTOP_CONFIG} (keep your other mcpServers), then restart Desktop:")
    print(json.dumps(cfg, indent=2, ensure_ascii=False))
    print(f"\n{'all checks passed' if not failed else f'{failed} check(s) failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
