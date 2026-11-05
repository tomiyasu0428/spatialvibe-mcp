#!/usr/bin/env bash
# Safe to re-run: creates .venv (Python 3.12) if missing, installs requirements, runs the doctor.
# Does not touch Claude Code / Claude Desktop settings — the doctor only prints what to add.
# Usage: scripts/setup.sh [--printer a1mini]   (extra arguments go to the doctor)
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python

if [ -x "$PY" ]; then
  ver=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
  if [ "$ver" != "3.12" ]; then
    echo "NG: .venv uses Python $ver; 3.12 is needed. Move it aside (mv .venv .venv.old) and re-run." >&2
    exit 1
  fi
  echo "OK: .venv (Python 3.12) already exists"
elif command -v uv >/dev/null 2>&1; then
  uv venv --python 3.12 .venv
elif command -v python3.12 >/dev/null 2>&1; then
  python3.12 -m venv .venv
else
  echo "NG: need uv (recommended: brew install uv) or python3.12" >&2
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PY" -r requirements.txt
else
  "$PY" -m pip install -r requirements.txt
fi

"$PY" -m spatialvibe_mcp.doctor "$@"
