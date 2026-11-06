// Real local workerd (Miniflare) with a KV binding and a stubbed upstream; dummy credentials only.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
import {build} from 'esbuild';
import {Miniflare} from 'miniflare';

const b64url = bytes => Buffer.from(bytes).toString('base64url');
const sha256 = async s => b64url(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
// wrangler bundles on deploy; here esbuild does the same in memory (workerd wants a path inside the cwd).
async function bundle() {
  const result = await build({entryPoints: [fileURLToPath(new URL('./worker.mjs', import.meta.url))], bundle: true, format: 'esm',
    platform: 'browser', conditions: ['workerd', 'worker'], external: ['cloudflare:*'], write: false, logLevel: 'silent'});
  return result.outputFiles[0].text;
}

test('gateway: OAuth front door and upstream relay', async t => {
  const origin = 'https://gateway.example.test', upstreamOrigin = 'https://mac.example.test';
  const upstreamToken = 'U'.repeat(43), password = 'correct horse battery staple';
  const script = await bundle();
  const seen = [];
  let upstreamMode = 'ok';
  const mf = new Miniflare({modules: true, script, compatibilityDate: '2026-07-30',
    compatibilityFlags: ['global_fetch_strictly_public'], kvNamespaces: ['OAUTH_KV'],
    bindings: {PUBLIC_ORIGIN: origin, UPSTREAM_ORIGIN: upstreamOrigin, UPSTREAM_TOKEN: upstreamToken, LOGIN_PASSWORD: password},
    outboundService: async request => {
      seen.push({url: request.url, method: request.method, headers: Object.fromEntries(request.headers), body: await request.text()});
      if (upstreamMode === 'down') return new Response('error code: 1033', {status: 530});
      if (upstreamMode === '401') return new Response('{"error":"invalid_token"}', {status: 401, headers: {'WWW-Authenticate': 'Bearer error="invalid_token"'}});
      return new Response('event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n',
        {status: 200, headers: {'Content-Type': 'text/event-stream', 'Mcp-Session-Id': 'sess-1', 'Set-Cookie': 'leak=1', 'X-Upstream': 'x'}});
    },
    host: '127.0.0.1', port: 0});
  t.after(() => mf.dispose());
  const get = (path, init) => mf.dispatchFetch(origin + path, init);

  await t.test('unauthenticated /mcp challenges with the resource metadata', async () => {
    const r = await get('/mcp', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
    assert.equal(r.status, 401);
    assert.match(r.headers.get('WWW-Authenticate'), /resource_metadata="https:\/\/gateway\.example\.test\/\.well-known\/oauth-protected-resource\/mcp"/);
    assert.equal(seen.length, 0, 'nothing reached the upstream');
    const prm = await (await get('/.well-known/oauth-protected-resource/mcp')).json();
    assert.deepEqual(prm.authorization_servers, [origin]);
    assert.equal(prm.resource, origin + '/mcp');
    const as = await (await get('/.well-known/oauth-authorization-server')).json();
    assert.equal(as.registration_endpoint, origin + '/oauth/register');
    assert.ok(as.code_challenge_methods_supported.includes('S256'));
    assert.equal(as.client_id_metadata_document_supported, true);
  });

  const redirectUri = 'https://client.example.test/callback';
  let clientId;
  await t.test('dynamic client registration (public client)', async () => {
    const r = await get('/oauth/register', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({client_name: 'Test <b>App</b>', redirect_uris: [redirectUri], token_endpoint_auth_method: 'none'})});
    assert.equal(r.status, 201, await r.clone().text());
    clientId = (await r.json()).client_id;
    assert.ok(clientId);
  });

  const verifier = 'v'.repeat(43), challenge = await sha256(verifier);
  const authorizeUrl = '/authorize?' + new URLSearchParams({response_type: 'code', client_id: clientId, redirect_uri: redirectUri,
    scope: 'mcp', state: 'st-1', code_challenge: challenge, code_challenge_method: 'S256', resource: origin + '/mcp'});
  let cookie, handle;
  await t.test('consent page: escaped client name, password form, bound to the browser', async () => {
    const r = await get(authorizeUrl);
    assert.equal(r.status, 200, await r.clone().text());
    const html = await r.text();
    assert.match(html, /Test &#60;b&#62;App&#60;\/b&#62;/);
    assert.doesNotMatch(html, /<b>App<\/b>/);
    assert.match(html, /client\.example\.test/);
    assert.match(html, /type="password"/);
    assert.match(r.headers.get('Content-Security-Policy'), /frame-ancestors 'none'/);
    handle = html.match(/name="handle" value="([^"]+)"/)[1];
    cookie = (r.headers.getSetCookie?.() ?? [r.headers.get('Set-Cookie')]).map(c => c.split(';')[0]).join('; ');
    assert.match(cookie, /__Host-oauth-/);
  });

  const post = form => get(authorizeUrl, {method: 'POST', body: new URLSearchParams(form).toString(), redirect: 'manual',
    headers: {'Content-Type': 'application/x-www-form-urlencoded', Cookie: cookie}});
  let code;
  await t.test('wrong password keeps the page; right password redirects with a code', async () => {
    const wrong = await post({handle, password: 'nope', decision: 'approve'});
    assert.equal(wrong.status, 401);
    assert.match(await wrong.text(), /Wrong password/);
    const ok = await post({handle, password, decision: 'approve'});
    assert.equal(ok.status, 302, await ok.clone().text());
    const location = new URL(ok.headers.get('Location'));
    assert.equal(location.origin + location.pathname, redirectUri);
    assert.equal(location.searchParams.get('state'), 'st-1');
    code = location.searchParams.get('code');
    assert.ok(code);
    const reused = await post({handle, password, decision: 'approve'});
    assert.notEqual(reused.status, 302, 'the handle works once');
  });

  let accessToken;
  await t.test('token exchange with PKCE', async () => {
    const r = await get('/oauth/token', {method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
      body: new URLSearchParams({grant_type: 'authorization_code', code, redirect_uri: redirectUri, client_id: clientId, code_verifier: verifier})});
    assert.equal(r.status, 200, await r.clone().text());
    const token = await r.json();
    accessToken = token.access_token;
    assert.ok(accessToken);
    assert.ok(token.refresh_token);
  });

  await t.test('/mcp relays with the upstream credential and filtered headers', async () => {
    const r = await get('/mcp', {method: 'POST', body: '{"jsonrpc":"2.0","id":1,"method":"initialize"}',
      headers: {Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream',
        Cookie: 'session=secret', 'Mcp-Protocol-Version': '2025-06-18', 'X-Forwarded-For': '1.2.3.4'}});
    assert.equal(r.status, 200, await r.clone().text());
    assert.equal(r.headers.get('Mcp-Session-Id'), 'sess-1');
    assert.equal(r.headers.get('Content-Type'), 'text/event-stream');
    assert.equal(r.headers.get('Set-Cookie'), null);
    assert.equal(r.headers.get('X-Upstream'), null);
    assert.match(await r.text(), /"result"/);
    const call = seen.at(-1);
    assert.equal(call.url, upstreamOrigin + '/mcp');
    assert.equal(call.headers.authorization, `Bearer ${upstreamToken}`);
    assert.equal(call.headers['mcp-protocol-version'], '2025-06-18');
    assert.equal(call.headers.cookie, undefined);
    assert.equal(call.headers['x-forwarded-for'], undefined);
    assert.equal(call.body, '{"jsonrpc":"2.0","id":1,"method":"initialize"}');
    assert.notEqual(call.headers.authorization, `Bearer ${accessToken}`);
  });

  await t.test('bad or missing bearer never reaches the upstream', async () => {
    const before = seen.length;
    for (const auth of ['Bearer ' + 'x'.repeat(40), `Bearer ${upstreamToken}`, undefined]) {
      const r = await get('/mcp', {method: 'POST', body: '{}', headers: {...(auth ? {Authorization: auth} : {}), 'Content-Type': 'application/json'}});
      assert.equal(r.status, 401);
    }
    assert.equal(seen.length, before);
    assert.equal((await get('/mcp/other', {headers: {Authorization: `Bearer ${accessToken}`}})).status, 404);
  });

  await t.test('upstream outages are reported without an OAuth challenge', async () => {
    const headers = {Authorization: `Bearer ${accessToken}`, 'Content-Type': 'application/json'};
    upstreamMode = 'down';
    const down = await get('/mcp', {method: 'POST', body: '{}', headers});
    assert.equal(down.status, 503);
    assert.equal(down.headers.get('WWW-Authenticate'), null);
    upstreamMode = '401';
    const mismatch = await get('/mcp', {method: 'POST', body: '{}', headers});
    assert.equal(mismatch.status, 502);
    assert.equal(mismatch.headers.get('WWW-Authenticate'), null);
    upstreamMode = 'ok';
  });

  await t.test('unknown paths and deny', async () => {
    assert.equal((await get('/anything')).status, 404);
    assert.equal((await get('/')).status, 200);
    const r = await get(authorizeUrl);
    const h = (await r.text()).match(/name="handle" value="([^"]+)"/)[1];
    const c = (r.headers.getSetCookie?.() ?? [r.headers.get('Set-Cookie')]).map(x => x.split(';')[0]).join('; ');
    const denied = await get(authorizeUrl, {method: 'POST', body: new URLSearchParams({handle: h, decision: 'deny'}).toString(),
      redirect: 'manual', headers: {'Content-Type': 'application/x-www-form-urlencoded', Cookie: c}});
    assert.equal(denied.status, 302);
    assert.match(denied.headers.get('Location'), /error=access_denied/);
  });
});

test('gateway refuses to run without a complete configuration', async t => {
  const script = await bundle();
  for (const bindings of [
    {PUBLIC_ORIGIN: 'https://g.example.test', UPSTREAM_ORIGIN: 'https://m.example.test', UPSTREAM_TOKEN: 'short', LOGIN_PASSWORD: 'correct horse battery'},
    {PUBLIC_ORIGIN: 'https://g.example.test', UPSTREAM_ORIGIN: 'https://m.example.test', UPSTREAM_TOKEN: 'U'.repeat(43), LOGIN_PASSWORD: 'short'},
    {PUBLIC_ORIGIN: 'http://g.example.test', UPSTREAM_ORIGIN: 'https://m.example.test', UPSTREAM_TOKEN: 'U'.repeat(43), LOGIN_PASSWORD: 'correct horse battery'},
  ]) {
    const mf = new Miniflare({modules: true, script, compatibilityDate: '2026-07-30', kvNamespaces: ['OAUTH_KV'], bindings, host: '127.0.0.1', port: 0});
    const r = await mf.dispatchFetch('https://g.example.test/.well-known/oauth-authorization-server');
    assert.equal(r.status, 503);
    await mf.dispose();
  }
});
