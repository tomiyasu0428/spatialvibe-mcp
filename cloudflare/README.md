# AR link host (Cloudflare Worker + R2)

`publish_ar` can upload the USDZ here and hand the user a link. Opened in Safari on an iPhone,
the page has one big picture: tap it and AR Quick Look starts at real scale
(`#allowsContentScaling=0` asks Quick Look not to allow pinch-resizing; not yet checked on a device).
Other browsers see "open this in Safari". Links use a long random id and expire after `TTL_DAYS`.

## Deploy (once)
```bash
cd cloudflare
npx wrangler login                       # or CLOUDFLARE_API_TOKEN with Workers + R2 edit rights
npx wrangler r2 bucket create spatialvibe-ar
npx wrangler secret put UPLOAD_TOKEN     # a long random string
npx wrangler deploy                      # prints https://spatialvibe-ar.<you>.workers.dev
```

## Use from the MCP server
```bash
SPATIALVIBE_PUBLISH=cloudflare:https://spatialvibe-ar.<you>.workers.dev
SPATIALVIBE_UPLOAD_TOKEN=<the same string as UPLOAD_TOKEN>
```
`publish_ar` then returns `link`.

## Files
- `worker.js` — upload (PUT with the token) and serving. `meta.json` gets its expiry from the Worker, not the uploader.
- `page.js` — the page the link opens.
- `worker.test.mjs` — `node --test cloudflare/worker.test.mjs` (in-memory R2).
- `dev_server.mjs` — run the Worker locally: `node cloudflare/dev_server.mjs 8787 dev-token`.
