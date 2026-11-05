// Local stand-in for the deployed Worker (in-memory R2), for tests and trying publish_ar offline.
// node cloudflare/dev_server.mjs <port> <token>
import http from "node:http";
import worker from "./worker.js";

const [port, token] = [Number(process.argv[2] || 8787), process.argv[3] || "dev-token"];
const store = new Map();
const env = {
  UPLOAD_TOKEN: token, TTL_DAYS: "30",
  BUCKET: {
    async put(k, v) { store.set(k, new Uint8Array(v)); },
    async get(k) { const b = store.get(k); return b ? { body: b, text: async () => new TextDecoder().decode(b) } : null; },
  },
};
http.createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = ["GET", "HEAD"].includes(req.method) ? undefined : Buffer.concat(chunks);
  const r = await worker.fetch(new Request(`http://127.0.0.1:${port}${req.url}`, { method: req.method, headers: req.headers, body }), env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(port, "127.0.0.1", () => console.log(`ready ${port}`));
