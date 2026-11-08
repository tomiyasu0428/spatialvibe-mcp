# Remote MCP (Claude / ChatGPT → Mac) — handoff

Goal: ask for a shape from the phone, get an expiring AR link, check it in Safari. Steps ③④ (AR
Worker) existed; this adds ① ② — an OAuth gateway and an HTTP mode for the Mac-hosted server.
Design and operator steps: `REMOTE_MCP.md`. No secret values are recorded here.

## 2026-11-06
- `spatialvibe_mcp/_remote.py` + `SPATIALVIBE_TRANSPORT=http`: Streamable HTTP on 127.0.0.1:8765,
  one upstream Bearer credential (Keychain account `mcp-upstream`, constant-time compare), Host check
  for the Tunnel hostname, no OAuth metadata and no access log on the Mac. Launcher config keys
  `transport`, `public_host`, `upstream_keychain_service`, `http_port`.
- `cloudflare/mcp-gateway`: Worker on `@cloudflare/workers-oauth-provider` 1.2.4 (DCR + CIMD, PKCE),
  single-owner password consent page, `/mcp` relay with header filtering; outages → 503, credential
  mismatch → 502. `node --test gateway.test.mjs` runs the full flow in local workerd (11 checks).
- `mac/`: launchd agents for the server and cloudflared, Tunnel config example.
- Verified here: `tests/test_remote.py` (7), `tests/test_ar_launch.py` (5), gateway tests (11). Not
  verified: a real deploy (no Cloudflare access from the cloud session), the Tunnel, claude.ai and
  ChatGPT registration, a phone end-to-end. The AR Worker proxy-injection 401 from the cloud session
  is unresolved and no longer on this path (the Mac uses its Keychain key, 415 confirmed earlier).

## 2026-11-06 (later) — parked
- Decision: stop the gateway/Tunnel route for now. The phone drives Claude Code on the Mac with
  Remote Control instead (`claude remote-control` in the repo folder, or Desktop app `/remote-control`),
  which already carries the local stdio SpatialVibe MCP server, the Keychain AR key and the
  sandbox. No gateway, OAuth or Tunnel needed. Nothing here was deployed; the code stays on
  `claude/magical-goldberg-anag9s` for later.

## 2026-11-08 — resumed
- Decision reversed: the owner wants Pittari usable from browser/phone Claude via Cloudflare, so the
  gateway + Tunnel route is back. Merged into the work branch; `tests/test_remote.py` (7),
  `tests/test_ar_launch.py`, gateway tests (11) and AR Worker tests (35) pass in the cloud session.
- Still not done (needs the owner's Cloudflare account and Mac): KV namespace, Tunnel + DNS hostname,
  the two secrets, `wrangler deploy`, launchd agents, claude.ai connector registration.
