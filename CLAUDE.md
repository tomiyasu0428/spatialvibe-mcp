# spatialvibe-mcp

- Python 3.12 venv at `.venv/`; run everything with `.venv/bin/python`. Tests: `.venv/bin/python -m unittest discover -s tests`.
- `spatialvibe_mcp/` is the MCP server; `WORKFLOW.md` there is sent to Claude as server instructions — keep it short and in sync with what the tools actually do.
- No part templates by design. Models are free-form build123d scripts defining `parts` and `context`.
- Model scripts are untrusted: every child (runner, render, usdz) goes through `_isolation.py` (sandbox-exec, scratch folder, per-job budget; fail closed without the sandbox). `_files.py` holds the link-safe dirfd file routines and `wipe`, `_store.py` the project/version folders and result.json reading, `_build.py` the validation and admission of a build's output. Never add an unsandboxed path, never pass parent env or version folders to a child, and never open a version or scratch file by path — use `_files`.
- Units: mm, Z up in scripts; USDZ is metres, Y up (`usdz.py` converts).
- Reels: `reels/*/scenes.json` is the source of truth; `reel/engine.html` is shared by every reel, so changing it changes old reels too. Use the `progress-reel` subagent to make a new one.
- This repo is public: never commit photos, `data/`, tokens, or personal documents.
