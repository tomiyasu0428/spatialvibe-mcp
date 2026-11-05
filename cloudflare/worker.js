// spatialvibe AR host: PUT files with the upload token, then share /ar/<id>.
import { renderPage, ICON_SVG } from "./page.js";

const ID = /^[A-Za-z0-9_-]{16,64}$/;
const FILES = { "model.usdz": "model/vnd.usdz+zip", "thumb.png": "image/png", "meta.json": "application/json" };
const MAX = 50 * 1024 * 1024;
const HDR = { "X-Robots-Tag": "noindex", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff" };

function res(body, status = 200, type = "text/plain; charset=utf-8", extra = {}) {
  return new Response(body, { status, headers: { "Content-Type": type, ...HDR, ...extra } });
}

async function meta(env, id) {
  const o = await env.BUCKET.get(`${id}/meta.json`);
  if (!o) return null;
  const m = JSON.parse(await o.text());
  if (m.expires && Date.parse(m.expires) < Date.now()) return "expired";
  return m;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname.split("/").filter(Boolean);

    if (p[0] === "api" && p[1] === "ar" && request.method === "PUT") {
      const tok = (request.headers.get("Authorization") || "").replace(/^Bearer /, "");
      if (!env.UPLOAD_TOKEN || tok !== env.UPLOAD_TOKEN) return res("unauthorized", 401);
      const [id, file] = [p[2], p[3]];
      if (!ID.test(id || "") || !FILES[file]) return res("bad path", 400);
      const len = Number(request.headers.get("Content-Length") || 0);
      if (len > MAX) return res("too large", 413);
      let body = await request.arrayBuffer();
      if (body.byteLength > MAX) return res("too large", 413);
      if (file === "meta.json") {   // the server decides the expiry, not the uploader
        const m = JSON.parse(new TextDecoder().decode(body));
        const days = Number(env.TTL_DAYS || 30);
        m.expires = new Date(Date.now() + days * 864e5).toISOString();
        m.expires_text = `このリンクは ${m.expires.slice(0, 10)} まで使えます`;
        body = new TextEncoder().encode(JSON.stringify(m));
      }
      await env.BUCKET.put(`${id}/${file}`, body, { httpMetadata: { contentType: FILES[file] } });
      return res(JSON.stringify({ ok: true, url: `${url.origin}/ar/${id}` }), 200, "application/json");
    }

    if (request.method !== "GET" && request.method !== "HEAD") return res("method not allowed", 405);
    if (p.length === 1 && p[0] === "icon.svg") return res(ICON_SVG, 200, "image/svg+xml");

    if (p[0] === "ar" && ID.test(p[1] || "") && p.length === 2) {
      const m = await meta(env, p[1]);
      if (m === "expired") return res("このリンクは期限切れです", 410);
      if (!m) return res("見つかりません", 404);
      return res(renderPage(p[1], m), 200, "text/html; charset=utf-8", { "Cache-Control": "no-store" });
    }

    if (p[0] === "f" && ID.test(p[1] || "") && FILES[p[2]] && p[2] !== "meta.json") {
      const m = await meta(env, p[1]);
      if (m === "expired") return res("expired", 410);
      if (!m) return res("not found", 404);
      const o = await env.BUCKET.get(`${p[1]}/${p[2]}`);
      if (!o) return res("not found", 404);
      return new Response(o.body, { headers: { "Content-Type": FILES[p[2]], "Cache-Control": "private, max-age=300", ...HDR } });
    }
    return res("not found", 404);
  },
};
