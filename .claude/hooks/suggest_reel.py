"""PostToolUse hook: after a successful `git commit`, ask Claude to offer a progress reel."""
import json
import sys

event = json.load(sys.stdin)
cmd = (event.get("tool_input") or {}).get("command", "")
resp = event.get("tool_response") or {}
failed = resp.get("interrupted") or (isinstance(resp, dict) and resp.get("exit_code") not in (None, 0))
if "git commit" in cmd and not failed:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "additionalContext": (
            "A commit was just made in spatialvibe-mcp. After finishing the current task, ask the user "
            "in one short line whether to make a 20-second progress reel (MP4) of the changes since the "
            "last reel. If they agree, delegate to the progress-reel subagent. Do not make it without asking."
        ),
    }}))
