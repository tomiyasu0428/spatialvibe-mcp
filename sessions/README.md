# Agent test loop

Each round simulates one real use from the field with three subagents (`.claude/agents/`):

| Agent | Role |
| --- | --- |
| `field-user` | The farmer: sends the request from the field, answers questions, reviews the result on "is it easy on site / can I see the dimensions" |
| `designer` | Claude with the spatialvibe tools (via `tools/sv.py`), following `spatialvibe_mcp/WORKFLOW.md` as-is |
| `checker` | Verifies files and numbers independently, tags issues `[tool]` / `[workflow]` / `[design]` |

Flow: request → questions → answers → design → (check ‖ review) → fix the tool/workflow → next round.
Each `round-NN/log.md` keeps the exchange, scores and what was changed. Generated models stay in
a scratch `SPATIALVIBE_HOME`, never in the repo. Progress is summarised as reels in `reels/`.
