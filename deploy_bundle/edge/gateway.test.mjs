import { test } from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes, createHmac } from 'node:crypto';
import { handle, verifySession } from './gateway.mjs';
const key = randomBytes(32);
const secret = key.toString('base64');
const now = Math.floor(Date.now()/1000);
const claims = {user_id:'test_branch',role:'branch_analyst',allowed_tables:['branch.account_summaries','branch.daily_flows','branch.loan_performance'],issued_at:now,expires_at:now+900};
function token(payload=claims,header={alg:'HS256',typ:'JWT'}) {
  const unsigned=Buffer.from(JSON.stringify(header)).toString('base64url')+'.'+Buffer.from(typeof payload==='string'?payload:JSON.stringify(payload)).toString('base64url');
  return unsigned+'.'+createHmac('sha256',key).update(unsigned).digest('base64url');
}
function env(overrides={}) {return {SESSION_KEY_B64:secret,ACCESS_CLIENT_ID:'test-service',ACCESS_CLIENT_SECRET:randomBytes(24).toString('base64url'),ORIGIN_URL:'https://origin.example.com',ALLOWED_ORIGINS:'https://sentinelsql-portal.pages.dev',IP_LIMITER:{limit:async()=>({success:true})},LOGIN_LIMITER:{limit:async()=>({success:true})},...overrides};}
function request(path='/api/v1/schema',headers={},options={}) {return new Request('https://api.example.com'+path,{headers:{'CF-Connecting-IP':'192.0.2.10',Origin:'https://sentinelsql-portal.pages.dev',Authorization:'Bearer '+token(),...headers},...options});}
test('prevalidates an API-compatible HS256 token',async()=>assert.deepEqual(await verifySession(token(),secret),claims));
test('rejects tampered signatures, expired tokens and algorithm substitution',async()=>{
  await assert.rejects(verifySession(token().slice(0,-5)+'AAAAA',secret));
  await assert.rejects(verifySession(token({...claims,expires_at:now-1}),secret));
  await assert.rejects(verifySession(token(claims,{alg:'none',typ:'JWT'}),secret));
});
test('rejects extra claims, duplicate claims and invalid lifetime',async()=>{
  await assert.rejects(verifySession(token({...claims,admin:true}),secret));
  await assert.rejects(verifySession(token(JSON.stringify(claims).replace('"user_id":','"user_id":"other","user_id":')),secret));
  await assert.rejects(verifySession(token({...claims,expires_at:now+3601}),secret));
});
test('rejects missing sessions before contacting origin',async()=>{
  let called=false;const response=await handle(request('/api/v1/schema',{Authorization:''}),env(),async()=>{called=true;});
  assert.equal(response.status,401);assert.equal(called,false);
});
test('denies hostile origins and URL credentials',async()=>{
  assert.equal((await handle(request('/api/v1/schema',{Origin:'https://hostile.example'}),env())).status,403);
  assert.equal((await handle(request('/api/v1/schema?access_token=private'),env())).status,400);
});
test('rate limits authentication independently and fails closed without a binding',async()=>{
  const deny={limit:async()=>({success:false})};
  assert.equal((await handle(request('/api/v1/auth/login',{}, {method:'POST'}),env({LOGIN_LIMITER:deny}))).status,429);
  assert.equal((await handle(request(),env({IP_LIMITER:undefined}))).status,503);
  assert.equal((await handle(request(),env({ACCESS_CLIENT_SECRET:undefined}))).status,503);
});
test('forwards only server-owned Access credentials and disables caching',async()=>{
  const response=await handle(request('/api/v1/schema',{'CF-Access-Client-Secret':'attacker',Cookie:'private=value'}),env({ACCESS_CLIENT_ID:'service',ACCESS_CLIENT_SECRET:'server-secret'}),async(req,options)=>{
    assert.equal(req.url,'https://origin.example.com/api/v1/schema');assert.equal(req.headers.get('CF-Access-Client-Secret'),'server-secret');
    assert.equal(req.headers.get('Cookie'),null);assert.equal(options.redirect,'manual');
    return Response.json({tables:[]},{headers:{'Set-Cookie':'leak=1','Cache-Control':'public'}});
  });
  assert.equal(response.status,200);assert.equal(response.headers.get('Cache-Control'),'no-store');assert.equal(response.headers.get('Set-Cookie'),null);
});
test('WebSocket first-frame authentication remains at origin and upgrade is untouched',async()=>{
  const upgrade={status:101,webSocket:{}};
  const response=await handle(request('/api/v1/query/stream',{Upgrade:'websocket',Authorization:''}),env(),async()=>upgrade);
  assert.equal(response,upgrade);
});
test('rejects insecure origins, routing loops and redirects',async()=>{
  assert.equal((await handle(request(),env({ORIGIN_URL:'http://origin.example.com'}))).status,503);
  assert.equal((await handle(request(),env({ORIGIN_URL:'https://api.example.com'}))).status,503);
  assert.equal((await handle(request(),env(),async()=>new Response(null,{status:302,headers:{Location:'https://login.example'}}))).status,502);
});
test('CORS preflight validates route, method and headers',async()=>{
  const headers={'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'};
  assert.equal((await handle(request('/api/v1/query/execute',headers,{method:'OPTIONS'}),env())).status,204);
  assert.equal((await handle(request('/api/v1/query/execute',{...headers,'Access-Control-Request-Headers':'x-unsafe'},{method:'OPTIONS'}),env())).status,403);
});
test('links client abort to the forwarded request',async()=>{
  const controller=new AbortController();
  await handle(request('/api/v1/schema',{}, {signal:controller.signal}),env(),async(req,options)=>{
    controller.abort();assert.equal(req.signal.aborted,true);assert.equal(options.signal.aborted,true);return Response.json({});
  });
});
test('rejects unknown routes and oversized requests',async()=>{
  assert.equal((await handle(request('/private'),env())).status,404);
  assert.equal((await handle(request('/api/v1/query/execute',{'Content-Length':'20000'},{method:'POST',body:'{}'}),env())).status,413);
});
