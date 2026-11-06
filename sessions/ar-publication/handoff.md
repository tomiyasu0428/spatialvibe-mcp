# AR publication to the deployed Worker — handoff

Worker: `https://spatialvibe-ar.aolarena16.workers.dev` (deployed from `review/ar-publication` d11f5bb,
private R2 `spatialvibe-ar-private`). Contract: `POST /api/publications` (see `cloudflare/ar-worker/worker.mjs`).
No secret values are recorded here.

## 2026-11-06
- Worker reachable through the cloud egress proxy; config complete (no 503). Unknown paths → 404,
  uploads without a valid credential → 401.
- Cloud environment `spatialvibe` (personal): allowed host `spatialvibe-ar.aolarena16.workers.dev`;
  one network secret for that host, header `Authorization` (Bearer), path prefix `/api/publications`,
  added by the user in the settings UI.
- Client: branch `claude/ar-proxy-publish` adds `SPATIALVIBE_AR_CREDENTIAL=proxy` (send a placeholder
  through the HTTPS proxy, which injects the saved credential). Local Keychain mode unchanged.
- Cloud session, same `POST /api/publications` (Content-Type text/plain, nothing stored):
  no Authorization header → 401; placeholder Bearer → 401 (also ~1 min and a few min later);
  client in proxy mode → 401. The Worker answers both cases alike, so "not injected" and
  "injected but wrong" cannot be told apart from the client.
- **Mac check (by the user):** the Keychain item (service `spatialvibe-ar-upload`, account `upload`)
  read in memory only by the approved Python + Security API, proxies and redirects disabled,
  `POST /api/publications`, Content-Type text/plain, empty body → **HTTP 415**. The key passed
  authentication; nothing was printed, saved or written to R2. **The Mac key and the Worker's
  UPLOAD_TOKEN match.**
- Remaining cause is on the cloud side: the network secret not yet applied to this session
  (it was added after the session moved to `spatialvibe`), or the format of the saved value
  (e.g. "Bearer " inside the value, trailing whitespace). No Cloudflare change or new key needed.
- After the Mac check, one auth re-check from the same cloud session (placeholder Bearer,
  Content-Type text/plain, empty body) → **401**. The calibration publish / hash / HEAD / Range /
  expiry tests were therefore not run. Next: start a fresh session on `spatialvibe` (secrets are
  loaded at session start) and/or re-check the saved value's format in the settings UI, then repeat
  the single auth check (expect 415) before publishing.
