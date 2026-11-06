// SpatialVibe MCP gateway: OAuth 2.1 front door for Claude / ChatGPT, relaying /mcp to the Mac
// through a Cloudflare Tunnel. One owner, one password, one upstream credential. No model code runs here.
//
// Bindings (wrangler.example.jsonc): OAUTH_KV (KV), PUBLIC_ORIGIN, UPSTREAM_ORIGIN (vars),
// LOGIN_PASSWORD, UPSTREAM_TOKEN (secrets, `wrangler secret put`, never CLI arguments).
import {OAuthProvider, AuthorizationError, CimdFetchError} from '@cloudflare/workers-oauth-provider';

const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const ORIGIN = /^https:\/\/[a-z0-9-]+(\.[a-z0-9-]+)+$/;
const MIN_PASSWORD = 12;
const SCOPES = ['mcp'];
// Headers that may cross the gateway in each direction; everything else (cookies, the OAuth
// bearer token, CF-* headers, upstream challenges) stays on its own side.
const TO_UPSTREAM = ['content-type', 'accept', 'mcp-session-id', 'mcp-protocol-version', 'last-event-id'];
const FROM_UPSTREAM = ['content-type', 'mcp-session-id', 'mcp-protocol-version', 'content-length'];
const encoder = new TextEncoder();
const escape = value => String(value).replace(/[&<>"']/g, ch => `&#${ch.charCodeAt(0)};`);

const pageHeaders = () => ({
  'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer',
  'X-Content-Type-Options': 'nosniff', 'X-Robots-Tag': 'noindex, nofollow',
  'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
});
const page = (body, status = 200, extra) => {
  const headers = new Headers(extra);
  for (const [k, v] of Object.entries(pageHeaders())) headers.set(k, v);
  return new Response(body, {status, headers});
};
const text = (body, status) => new Response(body, {status, headers: {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}});

function configError(env) {
  if (!ORIGIN.test(env.PUBLIC_ORIGIN ?? '') || !ORIGIN.test(env.UPSTREAM_ORIGIN ?? '')) return 'origins';
  if (!TOKEN.test(env.UPSTREAM_TOKEN ?? '')) return 'upstream credential';
  if (typeof env.LOGIN_PASSWORD !== 'string' || env.LOGIN_PASSWORD.length < MIN_PASSWORD) return 'login password';
  return null;
}

async function passwordMatches(env, given) {
  if (typeof given !== 'string' || given.length > 1024) return false;
  const [a, b] = await Promise.all([encoder.encode(given), encoder.encode(env.LOGIN_PASSWORD)]
    .map(bytes => crypto.subtle.digest('SHA-256', bytes)));
  return crypto.subtle.timingSafeEqual(a, b);
}

function consentPage(details, handle, {wrong = false} = {}) {
  const origin = details.clientDomain
    ? `Published by <strong>${escape(details.clientDomain)}</strong>.`
    : 'This app registered itself; its name is not verified.';
  return `<!doctype html>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>SpatialVibe MCP</title>
<style>body{font:16px/1.5 system-ui,sans-serif;max-width:32em;margin:3em auto;padding:0 1em}input,button{font:inherit;padding:.4em .6em}label{display:block;margin:1em 0}.warn{color:#a00}</style>
<h1>Allow ${escape(details.clientName)} to use SpatialVibe?</h1>
<p>${origin} Access will be sent to <strong>${escape(details.redirectHost)}</strong>.</p>
${details.redirectIsLoopback ? '<p class="warn"><strong>This sends access to an app on this computer.</strong> Continue only if you just started signing in from it.</p>' : ''}
<p>Scope: ${details.scope.map(escape).join(', ') || '(none)'}</p>
${wrong ? '<p class="warn">Wrong password.</p>' : ''}
<form method="post">
  <input type="hidden" name="handle" value="${escape(handle)}">
  <label>Owner password <input type="password" name="password" autocomplete="current-password" required autofocus></label>
  <p><button name="decision" value="approve">Allow</button> <button name="decision" value="deny" formnovalidate>Deny</button></p>
</form>`;
}

async function describeAgain(oauth, request) {
  try {
    return await oauth.describeConsent(await oauth.parseAuthRequest(request));
  } catch {
    return {clientName: 'this app', redirectHost: '(see the app)', redirectIsLoopback: false, scope: SCOPES};
  }
}

async function authorize(request, env) {
  const oauth = env.OAUTH_PROVIDER;
  try {
    if (request.method === 'GET') {
      const authRequest = await oauth.parseAuthRequest(request);
      const details = await oauth.describeConsent(authRequest);
      const consent = await oauth.beginConsent(authRequest);
      return page(consentPage(details, consent.handle), 200, consent.headers);
    }
    if (request.method !== 'POST') return text('Method not allowed', 405);
    const form = await request.formData();
    const handle = String(form.get('handle') ?? '');
    if (form.get('decision') !== 'approve') {
      const denied = await oauth.denyConsent(request, handle);
      return new Response(null, {status: 302, headers: denied.headers});
    }
    if (!(await passwordMatches(env, form.get('password')))) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      // The handle is untouched (not consumed), so the same page can be answered again. The form
      // posts back to the same URL, query included, so the request can be described again.
      return page(consentPage(await describeAgain(oauth, request), handle, {wrong: true}), 401);
    }
    const approved = await oauth.approveConsent(request, handle, {scope: SCOPES});
    const {redirectTo} = await oauth.completeAuthorization({
      request: approved.request, userId: 'owner', metadata: {}, scope: SCOPES, props: {userId: 'owner'},
    });
    approved.headers.set('Location', redirectTo);
    return new Response(null, {status: 302, headers: approved.headers});
  } catch (error) {
    if (error instanceof AuthorizationError && error.redirectTo) return Response.redirect(error.redirectTo, 302);
    if (error instanceof AuthorizationError || error instanceof CimdFetchError) {
      const message = error instanceof AuthorizationError ? error.description : 'This app could not be verified.';
      return page(`<!doctype html><meta charset="utf-8"><title>SpatialVibe MCP</title><p>${escape(message)}</p><p>Start again from the app.</p>`, 400);
    }
    throw error;
  }
}

const defaultHandler = {
  async fetch(request, env) {
    const problem = configError(env);
    if (problem) return text('Gateway is not configured', 503);
    const {pathname} = new URL(request.url);
    if (pathname === '/authorize') return authorize(request, env);
    if (pathname === '/') return page('<!doctype html><meta charset="utf-8"><title>SpatialVibe MCP</title><p>SpatialVibe MCP gateway.</p>');
    return text('Not found', 404);
  },
};

const apiHandler = {
  async fetch(request, env) {
    const problem = configError(env);
    if (problem) return text('Gateway is not configured', 503);
    const url = new URL(request.url);
    if (url.pathname !== '/mcp') return text('Not found', 404);
    const headers = new Headers();
    for (const name of TO_UPSTREAM) {
      const value = request.headers.get(name);
      if (value !== null) headers.set(name, value);
    }
    headers.set('Authorization', `Bearer ${env.UPSTREAM_TOKEN}`);
    headers.set('User-Agent', 'SpatialVibe-MCP-Gateway/1');
    const body = request.method === 'GET' || request.method === 'HEAD' ? undefined : request.body;
    let upstream;
    try {
      upstream = await fetch(`${env.UPSTREAM_ORIGIN}/mcp`, {method: request.method, headers, body, redirect: 'manual'});
    } catch {
      return text('The modelling computer is offline', 503);
    }
    // Cloudflare answers for an unreachable Tunnel origin with its own 5xx page (e.g. 530 / 1033).
    if (upstream.status >= 500) return text('The modelling computer is offline', 503);
    if (upstream.status === 401 || upstream.status === 421) {
      // Never relay the upstream challenge: the client would retry OAuth forever for a server-side fault.
      return text('Gateway and modelling computer disagree about the upstream credential', 502);
    }
    const out = new Headers({'Cache-Control': 'no-store'});
    for (const name of FROM_UPSTREAM) {
      const value = upstream.headers.get(name);
      if (value !== null) out.set(name, value);
    }
    return new Response(upstream.body, {status: upstream.status, headers: out});
  },
};

const providers = new Map();
function provider(origin) {
  let instance = providers.get(origin);
  if (!instance) {
    instance = new OAuthProvider({
      apiRoute: '/mcp', apiHandler, defaultHandler,
      authorizeEndpoint: '/authorize', tokenEndpoint: '/oauth/token', clientRegistrationEndpoint: '/oauth/register',
      scopesSupported: SCOPES, requiredScopes: SCOPES,
      resourceMetadata: {resource: `${origin}/mcp`, authorization_servers: [origin], resource_name: 'SpatialVibe MCP'},
      clientIdMetadataDocumentEnabled: true,
      accessTokenTTL: 3600, refreshTokenTTL: 30 * 86400,
      onError({status, code, description}) { console.warn(`oauth ${status} ${code}: ${description}`); },
    });
    providers.set(origin, instance);
  }
  return instance;
}

export default {
  fetch(request, env, ctx) {
    if (configError(env)) return text('Gateway is not configured', 503);
    return provider(env.PUBLIC_ORIGIN).fetch(request, env, ctx);
  },
};
