# SpatialVibe MCP gateway

A Cloudflare Worker that lets Claude (claude.ai custom connector) and ChatGPT (connector /
developer mode) reach the SpatialVibe MCP server running on your Mac. The Worker is the OAuth 2.1
authorization server and the public `/mcp` endpoint; it relays `/mcp` to the Mac through a
Cloudflare Tunnel with one dedicated upstream credential. Nothing is modelled here, and no user
token ever reaches the Mac. The Japanese walkthrough is [`../../REMOTE_MCP.md`](../../REMOTE_MCP.md).

```
Claude / ChatGPT ──OAuth 2.1──▶ this Worker ──Bearer UPSTREAM_TOKEN──▶ Tunnel ──▶ Mac 127.0.0.1:8765 (/mcp)
                                 OAUTH_KV                               (Host = public_host)      python -m spatialvibe_mcp (http mode)
```

## What it does

- `/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource/mcp`,
  `/oauth/register` (RFC 7591), `/oauth/token`: provided by
  [`@cloudflare/workers-oauth-provider`](https://github.com/cloudflare/workers-oauth-provider)
  (PKCE S256 required, Client ID Metadata Documents enabled, refresh tokens 30 days, access tokens 1 h).
- `/authorize`: a single-owner consent page. It shows the client's name, where tokens go, and asks
  for the owner password (`LOGIN_PASSWORD`, compared in constant time, 1 s delay on failure). There
  is no account system: one password, one user id `owner`.
- `/mcp`: with a valid access token the request is relayed to `UPSTREAM_ORIGIN/mcp` with
  `Authorization: Bearer UPSTREAM_TOKEN` and only the MCP headers
  (`Content-Type`, `Accept`, `Mcp-Session-Id`, `Mcp-Protocol-Version`, `Last-Event-ID`). Cookies,
  the OAuth token and `CF-*` headers never cross. Responses keep only `Content-Type`,
  `Mcp-Session-Id`, `Mcp-Protocol-Version`, `Content-Length` and are `no-store`; streams (SSE) pass
  through unchanged.
- An unreachable Mac is a plain `503` and a credential mismatch a `502`, never an OAuth challenge,
  so clients do not loop through sign-in for a server-side fault.
- Missing or malformed configuration (origins, a 43-character `UPSTREAM_TOKEN`, a password of
  at least 12 characters) makes every route `503`.

## Test

```
pnpm install            # @cloudflare/workers-oauth-provider, miniflare, esbuild (pinned by pnpm-lock.yaml)
node --test gateway.test.mjs
```

The test bundles the Worker with esbuild (wrangler does the same on deploy), runs it in a local
workerd with a KV binding and a stubbed upstream, and walks the whole flow: challenge → metadata →
dynamic registration → consent page (escaping, wrong password, one-time handle) → PKCE token
exchange → relay with header filtering → bad tokens, outages and deny.

## Deploy (your own account)

1. `cp wrangler.example.jsonc wrangler.jsonc` (git-ignored); fill in the account id and the
   workers.dev subdomain. `wrangler kv namespace create OAUTH_KV` and paste the id.
2. `UPSTREAM_ORIGIN` is the Tunnel hostname that points at the Mac (see `REMOTE_MCP.md`).
3. Secrets, each read from stdin: `wrangler secret put LOGIN_PASSWORD` (a long passphrase you type
   on the consent page) and `wrangler secret put UPSTREAM_TOKEN` (32 random bytes as 43 base64url
   characters; the same value goes into the Mac's Keychain item, account `mcp-upstream`). Generate
   it with `python3 -c 'import secrets;print(secrets.token_urlsafe(32))'` and never paste it into
   a chat or a shell history line.
4. `wrangler deploy`, then open `https://<worker>/.well-known/oauth-authorization-server` to check.
5. Register `https://<worker>/mcp` in claude.ai (Settings → Connectors → Add custom connector) and
   in ChatGPT (Settings → Connectors / Apps, developer mode). Both discover OAuth from the `401`.

## Limits

- One owner password protects everything; anyone who learns it and completes the consent page
  can use the Mac's tools until you rotate `LOGIN_PASSWORD` and revoke grants (delete the KV
  namespace's `grant:` / `token:` keys or recreate the namespace).
- The gateway trusts the Tunnel hostname; the Mac still checks the `Host` header and the
  upstream credential, so a leaked hostname alone gives nothing.
- Long tool calls (`build_model` can take minutes) stream through the Worker; the client's own
  tool timeout still applies.
