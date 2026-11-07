# SpatialVibe AR Worker

A small Cloudflare Worker that turns an uploaded USDZ into an expiring, unguessable
AR Quick Look link. `publish_ar` uses it when `SPATIALVIBE_PUBLISH=cloudflare`
(see `../../AR_PUBLICATION.md`).

## What it does

- `POST /api/publications` with a dedicated bearer upload credential (Worker secret
  `UPLOAD_TOKEN`). Browser `Origin` requests are refused.
- Stores one object per publication in a **private** R2 bucket bound as `AR_BUCKET`:
  the USDZ plus its expiry and public dimensions, written once with a conditional put.
- Returns an 86-character capability URL (`/ar/<id>`). The page, `model.usdz` and
  `thumbnail.svg` are served until the expiry (60 s – 1 day), then every route is 404,
  including HEAD and Range.
- Page: `rel="ar"` link with `#allowsContentScaling=0`, printable dimensions and floor
  hint. No external assets, `no-store`, `no-referrer`, `noindex`, strict CSP.
- Accepts exactly the USDZ shape the MCP exporter produces (one uncompressed, aligned
  `model.usdc`, CRC-checked). Limit 8 MiB by default (max 16 MiB).

## Test

```
pnpm install          # dev dependency: miniflare (pinned by pnpm-lock.yaml)
node --test worker.test.mjs runtime.test.mjs
```

`runtime.test.mjs` runs the Worker in a real local workerd with a local R2 binding,
using `calibration.usdz` (an anonymous 100 x 50 x 10 mm box) and dummy credentials.
With `node_modules` present, the Python suite also publishes through this local Worker
(`tests/test_ar_publication.py`).

## Deploy (your own account)

1. Create a NEW private R2 bucket for this Worker only. Keep r2.dev and custom domains
   off. Add a lifecycle rule deleting `ar/` objects after 2 days (longer than the
   maximum 1-day link lifetime; it is cleanup, not access control).
2. `cp wrangler.example.jsonc wrangler.jsonc` (git-ignored) and fill in the account id,
   workers.dev subdomain and bucket name. Observability/logpush stay off so capability
   URLs are not logged.
3. Generate one random 32-byte credential (43 base64url characters). Store it as the
   Worker secret with `wrangler secret put UPLOAD_TOKEN` (stdin, never a CLI argument)
   and in the macOS Keychain of the machine running the MCP server (see
   `../../AR_PUBLICATION.md`). Do not give the MCP server any Cloudflare admin token.
4. Deploy, then smoke-test with the calibration block only: authenticated upload, page,
   model hash, HEAD, Range, thumbnail, and 404 for every route after expiry.

Without `UPLOAD_TOKEN` the Worker refuses every upload with 503, so a deployment
without the secret is never an unauthenticated uploader.

## Limits

- Anyone with the full link can view it until expiry; expiry cannot recall copies
  already downloaded.
- There is no admin/revocation endpoint; delete the object with an administrative
  operation if early removal is needed.
- Cloudflare's edge rejects some default HTTP client user agents (error 1010) before
  the Worker runs; the MCP client sends its own `SpatialVibe-MCP-AR-Publisher/1`.
- Checked on an iPhone (2026-11-06): Quick Look opens from the expiring link and shows the
  model at real size. Scale lock and placement accuracy are not yet checked.
