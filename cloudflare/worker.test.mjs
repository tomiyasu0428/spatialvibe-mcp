// node --test cloudflare/  — the Worker against an in-memory R2.
import test from "node:test";
import assert from "node:assert/strict";
import worker from "./worker.js";

function env() {
  const store = new Map();
  return {
    UPLOAD_TOKEN: "secret-token", TTL_DAYS: "30",
    BUCKET: {
      async put(k, v) { store.set(k, typeof v === "string" ? new TextEncoder().encode(v) : new Uint8Array(v)); },
      async get(k) { const b = store.get(k); return b ? { body: b, text: async () => new TextDecoder().decode(b) } : null; },
    },
    store,
  };
}
const ID = "abcdefghijklmnop1234";
const put = (e, file, body, tok = "secret-token") => worker.fetch(new Request(`https://x.test/api/ar/${ID}/${file}`,
  { method: "PUT", body, headers: { Authorization: `Bearer ${tok}` } }), e);
const get = (e, path) => worker.fetch(new Request(`https://x.test${path}`), e);

test("upload needs the token", async () => {
  const e = env();
  assert.equal((await put(e, "model.usdz", "x", "wrong")).status, 401);
  assert.equal((await put(e, "evil.html", "x")).status, 400);
});

test("page has a Quick Look link that cannot be resized, escaped text, and serves the usdz", async () => {
  const e = env();
  assert.equal((await put(e, "model.usdz", "USDZDATA")).status, 200);
  const r = await put(e, "meta.json", JSON.stringify({ title: "マウント <b>", steps: ["床に向ける"], parts_size_cm: [4, 1.3, 13.2] }));
  assert.equal((await r.json()).url, `https://x.test/ar/${ID}`);
  const page = await (await get(e, `/ar/${ID}`)).text();
  assert.match(page, /rel="ar" href="\/f\/abcdefghijklmnop1234\/model\.usdz#allowsContentScaling=0"/);
  assert.match(page, /マウント &lt;b&gt;/);
  assert.match(page, /まで使えます/);
  const f = await get(e, `/f/${ID}/model.usdz`);
  assert.equal(f.headers.get("Content-Type"), "model/vnd.usdz+zip");
  assert.equal((await get(e, `/f/${ID}/meta.json`)).status, 404);
});

test("expired links stop working", async () => {
  const e = env();
  await put(e, "model.usdz", "U");
  await put(e, "meta.json", "{}");
  const k = `${ID}/meta.json`;
  const m = JSON.parse(new TextDecoder().decode(e.store.get(k)));
  m.expires = "2000-01-01T00:00:00Z";
  e.store.set(k, new TextEncoder().encode(JSON.stringify(m)));
  assert.equal((await get(e, `/ar/${ID}`)).status, 410);
  assert.equal((await get(e, `/f/${ID}/model.usdz`)).status, 410);
});
