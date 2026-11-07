// Real local workerd/Miniflare R2 binding; no Cloudflare account or production secret.
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {Miniflare} from 'miniflare';

test('local workerd and R2 contract',async t=>{
  const origin='https://ar.example.test',secret='T'.repeat(43);
  const bytes=new Uint8Array(await readFile(new URL('./calibration.usdz',import.meta.url)));
  const sha=Buffer.from(await crypto.subtle.digest('SHA-256',bytes)).toString('hex');
  const mf=new Miniflare({modules:true,scriptPath:fileURLToPath(new URL('./worker.mjs',import.meta.url)),
    compatibilityDate:'2026-07-30',r2Buckets:['AR_BUCKET'],
    bindings:{PUBLIC_ORIGIN:origin,UPLOAD_TOKEN:secret},
    host:'127.0.0.1',port:0});
  t.after(()=>mf.dispose());
  const metadata={parts_size_m:{x_width:0.1,y_depth:0.05,z_height:0.01},
    scene_size_m:{x_width:0.1,y_depth:0.05,z_height:0.01},include_context:false,ar_floor_mm:null};
  const headers={'Authorization':`Bearer ${secret}`,'Idempotency-Key':'I'.repeat(43),
    'Content-Type':'model/vnd.usdz+zip','X-Content-SHA256':sha,'X-AR-TTL-Seconds':'60',
    'X-AR-Metadata':JSON.stringify(metadata)};
  const publish=extra=>mf.dispatchFetch(origin+'/api/publications',
    {method:'POST',body:bytes,headers:{...headers,...extra}});
  let publication;
  await t.test('auth, checksum option, metadata and conditional first write',async()=>{
    const r=await publish();assert.equal(r.status,201,await r.clone().text());publication=await r.json();
    assert.equal(publication.sha256,sha);assert.deepEqual(publication.parts_size_m,metadata.parts_size_m);
  });
  await t.test('same-key retry uses the stored URL and expiry',async()=>{
    const r=await publish();assert.equal(r.status,200);assert.deepEqual(await r.json(),publication);
  });
  await t.test('concurrent create-only R2 writes have one winner',async()=>{
    const rs=await Promise.all([publish({'Idempotency-Key':'J'.repeat(43)}),publish({'Idempotency-Key':'J'.repeat(43)})]);
    assert.deepEqual(rs.map(r=>r.status).sort(),[200,201]);assert.deepEqual(await rs[0].json(),await rs[1].json());
  });
  await t.test('actual R2 full body, byte range, HEAD and thumbnail',async()=>{
    const r=await mf.dispatchFetch(publication.url+'/model.usdz',{headers:{Range:'bytes=0-7'}});
    assert.equal(r.status,206);assert.deepEqual(new Uint8Array(await r.arrayBuffer()),bytes.slice(0,8));
    assert.equal(r.headers.get('Content-Range'),`bytes 0-7/${bytes.length}`);
    const head=await mf.dispatchFetch(publication.url+'/model.usdz',{method:'HEAD'});
    assert.equal(head.status,200);assert.equal(await head.text(),'');assert.equal(Number(head.headers.get('Content-Length')),bytes.length);
    const thumbnail=await mf.dispatchFetch(publication.url+'/thumbnail.svg');assert.equal(thumbnail.status,200);
    assert.match(await thumbnail.text(),/<svg/);
  });
  await t.test('auth failure and bad package do not create new objects',async()=>{
    assert.equal((await publish({Authorization:`Bearer ${'W'.repeat(43)}`})).status,401);
    const r=await mf.dispatchFetch(origin+'/api/publications',
      {method:'POST',body:new Uint8Array(128),headers:{...headers,'Idempotency-Key':'K'.repeat(43)}});
    assert.equal(r.status,415);
  });
  const bucket=await mf.getR2Bucket('AR_BUCKET');
  await t.test('expired R2 metadata blocks every view path and HEAD/range',async()=>{
    const key='ar/'+new URL(publication.url).pathname.split('/').at(-1).slice(0,43);
    const stored=await bucket.get(key);assert.ok(stored);
    await bucket.put(key,await stored.arrayBuffer(),{customMetadata:{...stored.customMetadata,expires_at:'1'}});
    for(const suffix of ['', '/model.usdz','/thumbnail.svg'])for(const method of ['GET','HEAD']){
      const r=await mf.dispatchFetch(publication.url+suffix,{method,headers:{Range:'bytes=0-7'}});
      assert.equal(r.status,404);assert.match(r.headers.get('Cache-Control'),/no-store/);
    }
  });
  await t.test('only two atomic publication objects exist, with no partial assets',async()=>{
    const listed=await bucket.list();assert.equal(listed.objects.length,2);
  });
});
