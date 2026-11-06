# spatialvibe-mcp

- Product name is **Pittari（ぴったり）**; `spatialvibe` stays as the code/package/env-var name. Use Pittari in anything user-facing (README, docs, demo videos).
- Python 3.12 venv at `.venv/`; run everything with `.venv/bin/python`. Tests: `.venv/bin/python -m unittest discover -s tests`.
- `spatialvibe_mcp/` is the MCP server; `WORKFLOW.md` there is sent to Claude as server instructions — keep it short and in sync with what the tools actually do.
- No part templates by design. Models are free-form build123d scripts defining `parts` and `context`.
- Units: mm, Z up in scripts; USDZ is metres, Y up (`usdz.py` converts).
- Reels: `reels/*/scenes.json` is the source of truth; `reel/engine.html` is shared by every reel, so changing it changes old reels too. Use the `progress-reel` subagent to make a new one.
- This repo is public: never commit photos, `data/`, tokens, or personal documents.
