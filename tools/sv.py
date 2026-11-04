"""Command-line access to the same functions the MCP server exposes.

Used by the agent test loop (designer / checker subagents) and handy for manual checks.
Each command prints JSON (preview prints the PNG path).

  .venv/bin/python tools/sv.py build <project> <script.py> [note]
  .venv/bin/python tools/sv.py preview <project> [version]
  .venv/bin/python tools/sv.py publish <project> [version] [--no-context]
  .venv/bin/python tools/sv.py list [project]
  .venv/bin/python tools/sv.py code <project> [version]

Set SPATIALVIBE_HOME / SPATIALVIBE_PUBLISH as for the server (e.g. dir:/tmp/pub off macOS).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from spatialvibe_mcp import server  # noqa: E402


def _ver(args, i):
    return int(args[i]) if len(args) > i and args[i].isdigit() else None


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, a = argv[0], argv[1:]
    if cmd == "build":
        out = server.build_model(a[0], Path(a[1]).read_text(encoding="utf-8"), a[2] if len(a) > 2 else "")
    elif cmd == "preview":
        out = server.preview(a[0], _ver(a, 1))[1]
    elif cmd == "publish":
        out = server.publish_ar(a[0], _ver(a, 1), "--no-context" not in a)
    elif cmd == "list":
        out = server.list_projects(a[0] if a else None)
    elif cmd == "code":
        print(server.get_code(a[0], _ver(a, 1)))
        return 0
    else:
        print(f"unknown command {cmd!r}\n{__doc__}")
        return 2
    print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if not isinstance(out, dict) or out.get("ok", True) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
