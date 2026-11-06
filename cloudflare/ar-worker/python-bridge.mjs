// Test-only stdio transport. Never deploy this helper or use real credentials.
import {Miniflare} from 'miniflare';
import {fileURLToPath} from 'node:url';
let input='';
for await(const block of process.stdin) input+=block;
const request=JSON.parse(input);
const mf=new Miniflare({modules:true,rootPath:fileURLToPath(new URL('.',import.meta.url)),
  scriptPath:fileURLToPath(new URL('./worker.mjs',import.meta.url)),
  compatibilityDate:'2026-07-30',r2Buckets:['AR_BUCKET'],host:'127.0.0.1',port:0,
  bindings:{PUBLIC_ORIGIN:'https://ar.example.test',UPLOAD_TOKEN:'T'.repeat(43)}});
try{
  const response=await mf.dispatchFetch(request.url,{method:'POST',headers:request.headers,
    body:Buffer.from(request.body,'base64')});
  process.stdout.write(JSON.stringify({status:response.status,body:await response.text()}));
}finally{await mf.dispose();}
