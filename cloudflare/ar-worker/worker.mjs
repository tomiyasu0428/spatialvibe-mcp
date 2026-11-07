// Independent candidate only. No deployment, secrets, external assets or logging.
const MIME = 'model/vnd.usdz+zip';
const TOKEN = /^[A-Za-z0-9_-]{43}$/;
const encoder = new TextEncoder();
class HTTPError extends Error { constructor(status, message) { super(message); this.status = status; } }
const fail = (status, message) => { throw new HTTPError(status, message); };
const hex = bytes => Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
const b64 = bytes => btoa(String.fromCharCode(...new Uint8Array(bytes))).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');
const sha = async bytes => hex(await crypto.subtle.digest('SHA-256', bytes));
async function hmac(secret, data, usage = ['sign']) {
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret), {name:'HMAC',hash:'SHA-256'}, false, usage);
  return {key, signature:await crypto.subtle.sign('HMAC', key, encoder.encode(data))};
}
async function authorized(request, secret) {
  if (!TOKEN.test(secret ?? '')) fail(503, 'Publication unavailable');
  const value = request.headers.get('Authorization') ?? '';
  const match = /^Bearer ([A-Za-z0-9_-]{43})$/.exec(value);
  if (!match) fail(401, 'Authentication required');
  const candidate = await hmac(match[1], 'spatialvibe-upload-auth-v1');
  const expected = await hmac(secret, 'spatialvibe-upload-auth-v1', ['sign','verify']);
  if (!await crypto.subtle.verify('HMAC', expected.key, candidate.signature,
                                encoder.encode('spatialvibe-upload-auth-v1'))) fail(401, 'Authentication required');
}
const commonHeaders = () => new Headers({
  'Cache-Control':'private, no-store, max-age=0',
  'Referrer-Policy':'no-referrer',
  'X-Robots-Tag':'noindex, nofollow, noarchive, nosnippet',
  'X-Content-Type-Options':'nosniff',
  'Cross-Origin-Resource-Policy':'same-origin',
  'Permissions-Policy':'camera=(), microphone=(), geolocation=()',
  'Content-Security-Policy':"default-src 'none'; img-src 'self'; script-src 'none'; style-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
});
function response(body, status = 200, contentType = 'text/plain; charset=utf-8', extra = {}) {
  const headers = commonHeaders();
  headers.set('Content-Type',contentType);
  for (const [key,value] of Object.entries(extra)) headers.set(key,String(value));
  return new Response(body,{status,headers});
}
function json(body, status = 200) { return response(JSON.stringify(body),status,'application/json'); }
function config(env) {
  let origin;
  try { origin = new URL(env.PUBLIC_ORIGIN); } catch { fail(503,'Publication unavailable'); }
  if (origin.protocol !== 'https:' || origin.origin !== env.PUBLIC_ORIGIN || origin.username || origin.password ||
      /REPLACE|YOUR-/i.test(origin.hostname) || !env.AR_BUCKET)
    fail(503,'Publication unavailable');
  const max = Number(env.MAX_UPLOAD_BYTES ?? 8 * 1024 * 1024);
  if (!Number.isSafeInteger(max) || max < 128 || max > 16 * 1024 * 1024) fail(503,'Publication unavailable');
  return {origin:origin.origin,max};
}
async function boundedBody(request, max) {
  const advertised = request.headers.get('Content-Length');
  if (advertised !== null && (!/^\d+$/.test(advertised) || !Number.isSafeInteger(Number(advertised)))) fail(400,'Invalid length');
  if (Number(advertised) > max) fail(413,'Upload too large');
  if (!request.body) fail(400,'Empty upload');
  const reader = request.body.getReader();
  let length = 0;
  const chunks = [];
  try {
    while (true) {
      const {value,done} = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > max) { await reader.cancel(); fail(413,'Upload too large'); }
      chunks.push(value);
    }
  } catch (error) {
    if (error instanceof HTTPError) throw error;
    fail(400,'Incomplete upload');
  } finally { reader.releaseLock(); }
  if (advertised !== null && Number(advertised) !== length) fail(400,'Incomplete upload');
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk,offset); offset += chunk.byteLength; }
  return bytes;
}
const crcTable = Uint32Array.from({length:256},(_,n) => {
  for (let bit=0;bit<8;bit++) n = n & 1 ? 0xedb88320 ^ (n >>> 1) : n >>> 1;
  return n >>> 0;
});
function crc32(bytes) {
  let crc = 0xffffffff;
  for (let i=0;i<bytes.length;i++) crc = crcTable[(crc ^ bytes[i]) & 255] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
export function validateUsdz(bytes) {
  // Deliberately supports this MCP's single-root, uncompressed binary USD package.
  // This verifies ZIP integrity/magic, not semantic correctness of arbitrary USD.
  const bad = () => fail(415,'Unsupported or invalid USDZ package');
  if (bytes.length < 128) bad();
  const d = new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const e = bytes.length - 22;
  if (d.getUint32(e,true)!==0x06054b50 || d.getUint16(e+4,true)!==0 || d.getUint16(e+6,true)!==0 ||
      d.getUint16(e+8,true)!==1 || d.getUint16(e+10,true)!==1 || d.getUint16(e+20,true)!==0) bad();
  const c = d.getUint32(e+16,true), cs = d.getUint32(e+12,true);
  if (c<64 || cs<46 || c+cs!==e || c+46>e || d.getUint32(c,true)!==0x02014b50) bad();
  const flags=d.getUint16(c+8,true), method=d.getUint16(c+10,true);
  const size=d.getUint32(c+24,true), packed=d.getUint32(c+20,true), crc=d.getUint32(c+16,true);
  const nl=d.getUint16(c+28,true), extra=d.getUint16(c+30,true), comment=d.getUint16(c+32,true);
  if ((flags!==0 && flags!==0x800) || method!==0 || size!==packed || size<8 ||
      d.getUint16(c+34,true)!==0 || d.getUint32(c+42,true)!==0 || 46+nl+extra+comment!==cs || comment!==0) bad();
  if (d.getUint32(0,true)!==0x04034b50 || d.getUint16(6,true)!==flags || d.getUint16(8,true)!==0 ||
      d.getUint32(14,true)!==crc || d.getUint32(18,true)!==size || d.getUint32(22,true)!==size ||
      d.getUint16(26,true)!==nl) bad();
  const start=30+nl+d.getUint16(28,true);
  if (start%64!==0 || start+size!==c || nl!==10) bad();
  const ascii=(offset,text)=>[...text].every((ch,i)=>bytes[offset+i]===ch.charCodeAt(0));
  if (!ascii(30,'model.usdc') || !ascii(c+46,'model.usdc') ||
      !ascii(start,'PXR-USDC') || crc32(bytes.subarray(start,c))!==crc) bad();
}
function metadata(request) {
  const text=request.headers.get('X-AR-Metadata') ?? '';
  if (encoder.encode(text).length>1024) fail(400,'Invalid metadata');
  let value;
  try { value=JSON.parse(text); } catch { fail(400,'Invalid metadata'); }
  const keys=['ar_floor_mm','include_context','parts_size_m','scene_size_m'];
  if (!value || Object.keys(value).sort().join()!==keys.join() || typeof value.include_context!=='boolean') fail(400,'Invalid metadata');
  for (const field of ['parts_size_m','scene_size_m']) {
    const vector=value[field];
    if (!vector || Object.keys(vector).sort().join()!=='x_width,y_depth,z_height' ||
        Object.values(vector).some(n=>typeof n!=='number' || !Number.isFinite(n) || n<0 || n>1000)) fail(400,'Invalid metadata');
  }
  if (value.ar_floor_mm!==null && (typeof value.ar_floor_mm!=='number' || !Number.isFinite(value.ar_floor_mm) ||
      Math.abs(value.ar_floor_mm)>1e6 || !value.include_context)) fail(400,'Invalid metadata');
  return JSON.stringify(value);
}
function publicResult(cap, object, origin) {
  return {url:`${origin}/ar/${cap}${object.customMetadata.read_cap}`,expires_at:Number(object.customMetadata.expires_at),
          sha256:object.customMetadata.sha256, ...JSON.parse(object.customMetadata.model)};
}
async function upload(request,env,settings,now) {
  await authorized(request,env.UPLOAD_TOKEN);
  if (request.headers.get('Origin')) fail(403,'Browser uploads are disabled');
  if (request.headers.get('Content-Type')!==MIME || request.headers.has('Content-Encoding')) fail(415,'USDZ required');
  const id=request.headers.get('Idempotency-Key') ?? '';
  if (!TOKEN.test(id)) fail(400,'A 32-byte base64url idempotency key is required');
  const ttlText=request.headers.get('X-AR-TTL-Seconds') ?? '3600';
  const ttl=Number(ttlText);
  if (!/^\d+$/.test(ttlText) || !Number.isInteger(ttl) || ttl<60 || ttl>86400) fail(400,'TTL must be 60 to 86400 seconds');
  const model=metadata(request), bytes=await boundedBody(request,settings.max);
  validateUsdz(bytes);
  const digest=await sha(bytes);
  if (request.headers.get('X-Content-SHA256')!==digest) fail(400,'Upload checksum mismatch');
  const cap=b64((await hmac(env.UPLOAD_TOKEN,`spatialvibe-capability-v1:${id}`)).signature);
  const key=`ar/${cap}`;
  const reply=object => {
    if (object.customMetadata.sha256!==digest || object.customMetadata.model!==model || object.customMetadata.ttl!==String(ttl)) fail(409,'Idempotency key already used');
    if (Number(object.customMetadata.expires_at)<=now()) fail(410,'Publication expired; use a new idempotency key');
    return json(publicResult(cap,object,settings.origin));
  };
  const existing=await env.AR_BUCKET.head(key);
  if (existing) return reply(existing);
  // One atomic object plus metadata is the entire publication, so no partial bundle is visible.
  // Independent read capability prevents an old URL reviving after lifecycle deletion
  // followed by reuse of the same upload idempotency key.
  const customMetadata={sha256:digest,model,ttl:String(ttl),expires_at:String(now()+ttl),
                        read_cap:b64(crypto.getRandomValues(new Uint8Array(32)))};
  const stored=await env.AR_BUCKET.put(key,bytes,{onlyIf:new Headers({'If-None-Match':'*'}),
    sha256:digest,httpMetadata:{contentType:MIME,cacheControl:'private, no-store'},customMetadata});
  if (!stored) {
    const winner=await env.AR_BUCKET.head(key);
    if (!winner) fail(503,'Publication unavailable; retry with the same idempotency key');
    return reply(winner);
  }
  return json(publicResult(cap,stored,settings.origin),201);
}
function live(object,now) {
  const expiry=Number(object?.customMetadata?.expires_at);
  return object && Number.isSafeInteger(expiry) && expiry>now();
}
export function byteRange(header,size) {
  const m=/^bytes=(\d*)-(\d*)$/.exec(header);
  if (!m || (!m[1]&&!m[2])) fail(416,'Invalid range');
  let start,end;
  if (!m[1]) { const suffix=Number(m[2]); if (!Number.isSafeInteger(suffix)||suffix<=0) fail(416,'Invalid range'); start=Math.max(0,size-suffix); end=size-1; }
  else { start=Number(m[1]); end=m[2]?Number(m[2]):size-1; }
  if (!Number.isSafeInteger(start)||!Number.isSafeInteger(end)||start>=size||start>end) fail(416,'Invalid range');
  return {offset:start,length:Math.min(end,size-1)-start+1};
}
const SVG='<svg xmlns="http://www.w3.org/2000/svg" width="320" height="200" viewBox="0 0 320 200"><rect width="320" height="200" fill="#f4f2ec"/><path d="M100 80l60-30 60 30v60l-60 30-60-30zM100 80l60 30 60-30M160 110v60" fill="#ed9c4e" stroke="#372f28" stroke-width="3"/><text x="160" y="190" text-anchor="middle" font-family="sans-serif" font-size="16">AR Quick Look</text></svg>';
function page(cap,expiry,model) {
  const part=model.parts_size_m;
  const dimensions=[part.x_width,part.y_depth,part.z_height].map(n=>Number((n*1000).toFixed(2))).join(' × ');
  const floor=model.ar_floor_mm!==null ? `<p>床の位置: ${model.ar_floor_mm} mm。床にスマホを向けてから AR を開き、周囲の形を実物に合わせてください。</p>` : '';
  const modelUrl=`/ar/${cap}/model.usdz#allowsContentScaling=0`;
  return `<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta name="referrer" content="no-referrer"><meta name="robots" content="noindex,nofollow"><title>SpatialVibe AR</title>
<h1>AR で形を確認</h1>
<p>iPhoneのSafariで、下の画像をタップしてください。</p>
<a id="ar" rel="ar" href="${modelUrl}"><img src="/ar/${cap}/thumbnail.svg" alt="ARで開く" width="320" height="200"></a>
<p><a href="${modelUrl}">USDZファイルを直接開く</a></p>
<p>アプリ内でモデルを開けない場合は、このページのリンクをSafariで開いてください。</p>
<p>印刷する部品の外形: ${dimensions} mm</p>${floor}
<p>有効期限: ${new Date(expiry*1000).toISOString()}</p><p>リンクを知っている人は期限内に閲覧できます。保存したコピーは期限後も残ります。</p><p>縮尺変更を制限する設定です。実機での縮尺・位置精度は未検証です。大切な寸法は実測してください。</p></html>`;
}
async function view(request,env,path,now) {
  const [,cap,asset]=/^\/ar\/([A-Za-z0-9_-]{86})(?:\/(model\.usdz|thumbnail\.svg))?$/.exec(path) ?? [];
  if (!cap) fail(404,'Not found');
  const key=`ar/${cap.slice(0,43)}`, object=await env.AR_BUCKET.head(key);
  const permitted=value=>live(value,now) && value.customMetadata.read_cap===cap.slice(43);
  if (!permitted(object)) fail(404,'Not found');
  if (asset==='model.usdz') {
    const headers={'Accept-Ranges':'bytes','Content-Disposition':'inline; filename="model.usdz"'};
    let range;
    if (request.method==='GET' && request.headers.has('Range') && !request.headers.has('If-Range')) {
      try { range=byteRange(request.headers.get('Range'),object.size); }
      catch(error) { if(error.status===416) return response(null,416,MIME,{'Content-Range':`bytes */${object.size}`}); throw error; }
    }
    headers['Content-Length']=range?.length ?? object.size;
    if (range) headers['Content-Range']=`bytes ${range.offset}-${range.offset+range.length-1}/${object.size}`;
    if (request.method==='HEAD') {
      if (!permitted(object)) fail(404,'Not found');
      return response(null,200,MIME,headers);
    }
    const got=await env.AR_BUCKET.get(key,range?{range}:undefined);
    if (!permitted(got)) { if(got?.body) await got.body.cancel(); fail(404,'Not found'); }
    return response(got.body,range?206:200,MIME,headers);
  }
  let body,type;
  if (asset==='thumbnail.svg') { body=SVG; type='image/svg+xml'; }
  else {
    body=page(cap,Number(object.customMetadata.expires_at),JSON.parse(object.customMetadata.model));
    type='text/html; charset=utf-8';
  }
  if (!live(object,now)) fail(404,'Not found');
  return response(request.method==='HEAD'?null:body,200,type,{'Content-Length':encoder.encode(body).length});
}
export function createWorker({now=()=>Math.floor(Date.now()/1000)}={}) {
  return {async fetch(request,env) {
    try {
      const settings=config(env), url=new URL(request.url);
      if (url.origin!==settings.origin) fail(421,'Invalid origin');
      if (url.search || url.pathname.includes('%')) fail(404,'Not found');
      if (url.pathname==='/api/publications' && request.method==='POST') return await upload(request,env,settings,now);
      if (request.method!=='GET' && request.method!=='HEAD') fail(405,'Method not allowed');
      return await view(request,env,url.pathname,now);
    } catch(error) {
      const status=error instanceof HTTPError?error.status:503;
      const message=error instanceof HTTPError?error.message:'Publication unavailable; retry with the same idempotency key';
      return response(request.method==='HEAD'?null:message,status);
    }
  }};
}
export default createWorker();
