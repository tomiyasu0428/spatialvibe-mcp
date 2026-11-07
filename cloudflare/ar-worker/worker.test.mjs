import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createWorker,validateUsdz,byteRange} from './worker.mjs';

const bytes=new Uint8Array(await readFile(new URL('./calibration.usdz',import.meta.url)));
const origin='https://ar.example.test', token='T'.repeat(43), id='I'.repeat(43);
const digest=async data=>Buffer.from(await crypto.subtle.digest('SHA-256',data)).toString('hex');
const baseMeta={parts_size_m:{x_width:0.1,y_depth:0.05,z_height:0.01},
  scene_size_m:{x_width:0.1,y_depth:0.05,z_height:0.01},include_context:false,ar_floor_mm:null};
class Bucket {
  records=new Map();
  puts=0;
  heads=0;
  reads=0;
  throwAfterCommit=false;
  throwBeforeCommit=false;
  async head(key) { this.heads++; const r=this.records.get(key); return r?{size:r.bytes.length,customMetadata:{...r.meta}}:null; }
  async put(key,body,options) {
    this.puts++;
    assert.equal(options.onlyIf.get('If-None-Match'),'*');
    assert.equal(options.sha256,await digest(body));
    if (this.throwBeforeCommit) {this.throwBeforeCommit=false;throw Error('synthetic pre-commit failure');}
    // No await between the condition and committing, emulating atomic conditional put.
    if (this.records.has(key)) return null;
    this.records.set(key,{bytes:new Uint8Array(body),meta:{...options.customMetadata}});
    if(this.throwAfterCommit){this.throwAfterCommit=false;throw Error('synthetic lost response');}
    return this.head(key);
  }
  async get(key,options) {
    this.reads++;
    const head=await this.head(key);
    if(!head)return null;
    const r=this.records.get(key), range=options?.range;
    const body=range?r.bytes.slice(range.offset,range.offset+range.length):r.bytes.slice();
    return {...head,body:new Blob([body]).stream()};
  }
}
function setup() {
  const bucket=new Bucket();
  let clock=2000000000;
  const worker=createWorker({now:()=>clock});
  const env={PUBLIC_ORIGIN:origin,UPLOAD_TOKEN:token,AR_BUCKET:bucket};
  return {bucket,worker,env,setTime:value=>{clock=value;}};
}
async function upload(s,{body=bytes,headers={},omit=[],method='POST'}={}) {
  const h=new Headers({'Authorization':`Bearer ${token}`,'Content-Type':'model/vnd.usdz+zip',
    'Idempotency-Key':id,'X-AR-TTL-Seconds':'60','X-AR-Metadata':JSON.stringify(baseMeta),
    'X-Content-SHA256':await digest(bytes),...headers});
  for (const key of omit) h.delete(key);
  return s.worker.fetch(new Request(`${origin}/api/publications`,{method,headers:h,body,
    ...(body instanceof ReadableStream?{duplex:'half'}:{})}),s.env);
}
async function publish(s,options) {
  const r=await upload(s,options);
  assert.equal(r.status,201,await r.clone().text());
  return r.json();
}
const get=(s,path,options={})=>s.worker.fetch(new Request(path.startsWith('https:')?path:origin+path,options),s.env);
const keyFor=p=>'ar/'+new URL(p.url).pathname.split('/').at(-1).slice(0,43);
function securityHeaders(r) {
  assert.match(r.headers.get('Cache-Control'),/no-store/);
  assert.equal(r.headers.get('Referrer-Policy'),'no-referrer');
  assert.match(r.headers.get('X-Robots-Tag'),/noindex/);
  assert.equal(r.headers.get('X-Content-Type-Options'),'nosniff');
  assert.ok(r.headers.get('Content-Security-Policy'));
  assert.equal(r.headers.get('Access-Control-Allow-Origin'),null);
}

test('actual MCP calibration package passes ZIP/USDC validation',()=>validateUsdz(bytes));
test('authenticated atomic publication retains dimensions and uses an opaque URL',async()=>{
  const s=setup(), p=await publish(s);
  assert.match(p.url,/^https:\/\/ar\.example\.test\/ar\/[A-Za-z0-9_-]{86}$/);
  assert.equal(p.expires_at,2000000060);
  assert.equal(p.sha256,await digest(bytes));
  assert.deepEqual(p.parts_size_m,baseMeta.parts_size_m);
  assert.equal(p.include_context,false);
  assert.equal(p.ar_floor_mm,null);
  assert.equal(s.bucket.records.size,1);
});
test('page offers an AR image and direct model link without JavaScript or capability detection',async()=>{
  const s=setup(),p=await publish(s),r=await get(s,p.url),html=await r.text();
  assert.equal(r.status,200);securityHeaders(r);
  assert.match(html,/rel="ar" href="[^\"]+#allowsContentScaling=0"><img/);
  assert.doesNotMatch(html,/<script\b|\bhidden\b/);
  const modelPath=new URL(p.url).pathname+'/model.usdz#allowsContentScaling=0';
  assert.ok(html.includes(`<a href="${modelPath}">USDZファイルを直接開く</a>`));
  assert.match(html,/Safari/);assert.match(html,/100 × 50 × 10 mm/);
  assert.match(html,/未検証/);
  assert.match(r.headers.get('Content-Security-Policy'),/script-src 'none'/);
  assert.doesNotMatch(html,/https:\/\/(?!ar\.example\.test)/);
});
test('full USDZ response and HEAD have matching MIME/length and HEAD has no R2 body read',async()=>{
  const s=setup(),p=await publish(s),r=await get(s,p.url+'/model.usdz');
  assert.equal(r.status,200);securityHeaders(r);
  assert.equal(r.headers.get('Content-Type'),'model/vnd.usdz+zip');
  assert.equal(Number(r.headers.get('Content-Length')),bytes.length);
  assert.deepEqual(new Uint8Array(await r.arrayBuffer()),bytes);
  const reads=s.bucket.reads,head=await get(s,p.url+'/model.usdz',{method:'HEAD'});
  assert.equal(head.status,200);assert.equal(await head.text(),'');assert.equal(s.bucket.reads,reads);
  const rangedHead=await get(s,p.url+'/model.usdz',{method:'HEAD',headers:{Range:'bytes=0-7'}});
  assert.equal(rangedHead.status,200);assert.equal(Number(rangedHead.headers.get('Content-Length')),bytes.length);
});
test('single, open, suffix and clamped byte ranges return exact content',async()=>{
  const s=setup(),p=await publish(s);
  for(const [range,start,end] of [['bytes=0-7',0,7],['bytes=12-',12,bytes.length-1],
    ['bytes=-10',bytes.length-10,bytes.length-1],['bytes=0-999999',0,bytes.length-1]]){
    const r=await get(s,p.url+'/model.usdz',{headers:{Range:range}});
    assert.equal(r.status,206);securityHeaders(r);
    assert.equal(r.headers.get('Content-Range'),`bytes ${start}-${end}/${bytes.length}`);
    assert.equal(Number(r.headers.get('Content-Length')),end-start+1);
    assert.deepEqual(new Uint8Array(await r.arrayBuffer()),bytes.slice(start,end+1));
  }
});
test('malformed, multiple and unsatisfiable ranges return 416',async()=>{
  const s=setup(),p=await publish(s);
  for(const Range of ['bytes=','bytes=-0','bytes=8-2','bytes=999999-','bytes=0-1,3-4','bytes=1e3-','items=0-1']){
    const r=await get(s,p.url+'/model.usdz',{headers:{Range}});
    assert.equal(r.status,416,Range);assert.equal(r.headers.get('Content-Range'),`bytes */${bytes.length}`);securityHeaders(r);
  }
});
test('If-Range is conservatively ignored with full content, never 304',async()=>{
  const s=setup(),p=await publish(s);
  const r=await get(s,p.url+'/model.usdz',{headers:{Range:'bytes=0-7','If-Range':'"anything"','If-None-Match':'*'}});
  assert.equal(r.status,200);assert.equal((await r.arrayBuffer()).byteLength,bytes.length);
});
test('expiry boundary denies page, USDZ, thumbnail, HEAD and Range even with conditional headers',async()=>{
  const s=setup(),p=await publish(s);s.setTime(p.expires_at-1);
  assert.equal((await get(s,p.url)).status,200);s.setTime(p.expires_at);
  for(const suffix of ['', '/model.usdz','/thumbnail.svg']) for(const method of ['GET','HEAD']) {
    const r=await get(s,p.url+suffix,{method,headers:{Range:'bytes=0-7','If-None-Match':'*'}});
    assert.equal(r.status,404);securityHeaders(r);assert.equal(r.headers.get('Content-Range'),null);
    if(method==='HEAD')assert.equal(await r.text(),'');
  }
});
test('expiry is rechecked after asynchronous R2 model read',async()=>{
  const s=setup(),p=await publish(s),original=s.bucket.get.bind(s.bucket);
  s.bucket.get=async(...args)=>{const r=await original(...args);s.setTime(p.expires_at);return r;};
  assert.equal((await get(s,p.url+'/model.usdz')).status,404);
});
test('anonymous/wrong upload token rejected before body read or R2 access',async()=>{
  for(const Authorization of ['',`Bearer ${'W'.repeat(43)}`,'Basic abc']){
    const s=setup(),r=await upload(s,{headers:{Authorization}});
    assert.equal(r.status,401);securityHeaders(r);assert.equal(s.bucket.puts,0);assert.equal(s.bucket.heads,0);
  }
});
test('browser-origin uploads and preflight are disabled',async()=>{
  const s=setup();assert.equal((await upload(s,{headers:{Origin:'https://evil.test'}})).status,403);
  const r=await get(s,'/api/publications',{method:'OPTIONS'});assert.equal(r.status,405);securityHeaders(r);
});
test('TTL bounds, idempotency key, checksum, MIME and encoding are checked',async()=>{
  const cases=[['X-AR-TTL-Seconds','59',400],['X-AR-TTL-Seconds','86401',400],
    ['X-AR-TTL-Seconds','NaN',400],['X-AR-TTL-Seconds','1e3',400],['Idempotency-Key','../secret',400],
    ['X-Content-SHA256','0'.repeat(64),400],['Content-Type','text/html',415],['Content-Encoding','gzip',415]];
  for(const [name,value,status] of cases){const s=setup();assert.equal((await upload(s,{headers:{[name]:value}})).status,status,name);assert.equal(s.bucket.puts,0);}
});
test('metadata rejects extra/private fields, injection, invalid vectors and contradictory floor',async()=>{
  for(const model of [{...baseMeta,project:'/Users/private'}, {...baseMeta,include_context:'true'},
    {...baseMeta,parts_size_m:{...baseMeta.parts_size_m,x_width:'<script>'}},
    {...baseMeta,scene_size_m:{x_width:-1,y_depth:0,z_height:0}}, {...baseMeta,ar_floor_mm:-1100},null]){
    const s=setup();assert.equal((await upload(s,{headers:{'X-AR-Metadata':JSON.stringify(model)}})).status,400);assert.equal(s.bucket.puts,0);
  }
});
test('context/floor metadata remains available',async()=>{
  const s=setup(),model={...baseMeta,include_context:true,ar_floor_mm:-1100};
  const p=await publish(s,{headers:{'X-AR-Metadata':JSON.stringify(model)}});
  assert.equal(p.ar_floor_mm,-1100);assert.match(await (await get(s,p.url)).text(),/-1100 mm/);
});
test('advertised length and actual streaming byte limits are enforced',async()=>{
  const s=setup();s.env.MAX_UPLOAD_BYTES='128';
  assert.equal((await upload(s,{headers:{'Content-Length':String(bytes.length)}})).status,413);
  const stream=new ReadableStream({start(c){c.enqueue(new Uint8Array(80));c.enqueue(new Uint8Array(80));c.close();}});
  assert.equal((await upload(s,{body:stream})).status,413);assert.equal(s.bucket.puts,0);
});
test('interrupted body, empty and length mismatch never create an object',async()=>{
  for(const body of [new Uint8Array(),new ReadableStream({start(c){c.enqueue(bytes.slice(0,10));c.error(Error('synthetic interruption'));}})]){
    const s=setup(),r=await upload(s,{body});assert.ok([400,415].includes(r.status));assert.equal(s.bucket.records.size,0);
  }
  const s=setup();assert.equal((await upload(s,{headers:{'Content-Length':'1'}})).status,400);
});
test('corrupt package, fake ZIP, traversal name, compression and CRC corruption are rejected',async()=>{
  const fixtures=[new Uint8Array(128),bytes.slice(0,-5)];
  for(const offset of [8,30,64]){const copy=bytes.slice();copy[offset]^=1;fixtures.push(copy);}
  for(const body of fixtures){const s=setup(),r=await upload(s,{body,headers:{'X-Content-SHA256':await digest(body)}});assert.equal(r.status,415);assert.equal(s.bucket.puts,0);}
});
test('retry returns original URL and expiry, conflicting retry is rejected',async()=>{
  const s=setup(),p=await publish(s);s.setTime(2000000020);
  const r=await upload(s);assert.equal(r.status,200);assert.deepEqual(await r.json(),p);assert.equal(s.bucket.puts,1);
  assert.equal((await upload(s,{headers:{'X-AR-TTL-Seconds':'120'}})).status,409);
  s.setTime(p.expires_at);assert.equal((await upload(s)).status,410);
});
test('concurrent duplicate requests have one immutable winner',async()=>{
  const s=setup(),rs=await Promise.all([upload(s),upload(s)]);
  assert.deepEqual(rs.map(r=>r.status).sort(),[200,201]);
  assert.deepEqual(await rs[0].json(),await rs[1].json());assert.equal(s.bucket.records.size,1);
});
test('unknown outcome after commit recovers on same-key retry without extending expiry',async()=>{
  const s=setup();s.bucket.throwAfterCommit=true;
  const failed=await upload(s);assert.equal(failed.status,503);securityHeaders(failed);
  assert.equal(s.bucket.records.size,1);s.setTime(2000000010);
  const r=await upload(s);assert.equal(r.status,200);assert.equal((await r.json()).expires_at,2000000060);
});
test('failed write before commit leaves no publication',async()=>{
  const s=setup();s.bucket.throwBeforeCommit=true;
  assert.equal((await upload(s)).status,503);assert.equal(s.bucket.records.size,0);
  assert.equal((await upload(s)).status,201);
});
test('deletion and reuse of upload key cannot reactivate the old URL',async()=>{
  const s=setup(),p=await publish(s);s.setTime(p.expires_at);
  s.bucket.records.delete(keyFor(p));
  const replacement=await publish(s);
  assert.notEqual(replacement.url,p.url);
  assert.equal((await get(s,p.url)).status,404);
  assert.equal((await get(s,replacement.url)).status,200);
});
test('knowing the storage lookup half does not grant read access',async()=>{
  const s=setup(),p=await publish(s),url=p.url.slice(0,-43)+'W'.repeat(43);
  for(const asset of ['', '/model.usdz','/thumbnail.svg']) assert.equal((await get(s,url+asset)).status,404);
});
test('opaque paths, no listing, encoded traversal, query URLs and unrelated origins fail closed',async()=>{
  const s=setup(),p=await publish(s);
  for(const path of ['/','/ar','/ar/'+id,'/ar/'+id+'/../private','/ar/'+id+'%2fmodel.usdz',
    '/ar/'+id+'/other.png',new URL(p.url).pathname+'?token=abc']){
    const r=await get(s,path);assert.equal(r.status,404,path);securityHeaders(r);
  }
  assert.equal((await get(s,'https://unrelated.test'+new URL(p.url).pathname)).status,421);
});
test('missing/corrupt expiry metadata and deleted object fail closed',async()=>{
  const s=setup(),p=await publish(s),r=s.bucket.records.get(keyFor(p));
  for(const value of ['NaN','',undefined]){r.meta.expires_at=value;assert.equal((await get(s,p.url)).status,404);}
  s.bucket.records.delete(keyFor(p));assert.equal((await get(s,p.url)).status,404);
});
test('configuration rejects placeholder domain, missing auth/bucket and unsafe memory limit',async()=>{
  for(const mutation of [{PUBLIC_ORIGIN:'https://spatialvibe-ar.REPLACE-SUBDOMAIN.workers.dev'}, {UPLOAD_TOKEN:''},
    {AR_BUCKET:null},{MAX_UPLOAD_BYTES:'999999999'},{PUBLIC_ORIGIN:'http://ar.example.test'}]){
    const s=setup();Object.assign(s.env,mutation);const r=await upload(s);assert.equal(r.status,503);securityHeaders(r);
  }
});
test('range parser rejects unsafe numeric values',()=>{
  assert.throws(()=>byteRange('bytes=9007199254740993-',100));
  assert.throws(()=>byteRange('bytes=-9007199254740993',100));
});
