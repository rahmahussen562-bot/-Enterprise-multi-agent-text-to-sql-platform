/* Optional public gateway. The API remains the authority for account revocation and RBAC. */
const roles = new Set(['sales_analyst','inventory_lead','compliance_officer','branch_analyst','fraud_investigator']);
const claimsKeys = ['user_id','role','allowed_tables','issued_at','expires_at'];
function decode(value) {
  if (!/^[A-Za-z0-9_-]+$/.test(value)) throw new Error('Invalid encoding.');
  return Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/') + '='.repeat((4-value.length%4)%4)), c => c.charCodeAt(0));
}
function uniqueJSON(bytes) {
  const text = new TextDecoder('utf-8',{fatal:true}).decode(bytes);
  const value = JSON.parse(text);
  // The API emits compact JSON. Canonical round-trip rejects duplicate object keys.
  if (JSON.stringify(value) !== text) throw new Error('Noncanonical token.');
  return value;
}
export async function verifySession(token, secret, ttl = 900, now = Math.floor(Date.now()/1000)) {
  if (typeof token !== 'string' || token.length > 8192) throw new Error('Invalid session.');
  const parts = token.split('.');
  if (parts.length !== 3 || !secret || !Number.isInteger(ttl) || ttl < 30 || ttl > 3600) throw new Error('Invalid session configuration.');
  const keyBytes = Uint8Array.from(atob(secret), c => c.charCodeAt(0));
  if (keyBytes.length < 32) throw new Error('Invalid session configuration.');
  const header = uniqueJSON(decode(parts[0]));
  if (JSON.stringify(header) !== '{"alg":"HS256","typ":"JWT"}') throw new Error('Unsupported algorithm.');
  const key = await crypto.subtle.importKey('raw',keyBytes,{name:'HMAC',hash:'SHA-256'},false,['verify']);
  if (!await crypto.subtle.verify('HMAC',key,decode(parts[2]),new TextEncoder().encode(parts[0]+'.'+parts[1]))) throw new Error('Invalid signature.');
  const claims = uniqueJSON(decode(parts[1]));
  if (!claims || Object.keys(claims).length !== 5 || claimsKeys.some(key => !Object.hasOwn(claims,key)) ||
      typeof claims.user_id !== 'string' || [...claims.user_id].length < 1 || [...claims.user_id].length > 128 || !roles.has(claims.role) ||
      !Array.isArray(claims.allowed_tables) || claims.allowed_tables.length < 1 || claims.allowed_tables.length > 32 ||
      claims.allowed_tables.some(value => typeof value !== 'string') ||
      !Number.isSafeInteger(claims.issued_at) || !Number.isSafeInteger(claims.expires_at) || claims.issued_at < 0 ||
      claims.issued_at > now+30 || claims.expires_at <= now || claims.expires_at-claims.issued_at <= 0 || claims.expires_at-claims.issued_at > ttl) throw new Error('Invalid claims.');
  return claims;
}

function reply(status, code, detail, origin, headers = {}) {
  return Response.json({detail,error_code:code,ast_trace:[]},{status,headers:{
    'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
    ...(origin ? {'Access-Control-Allow-Origin':origin,'Vary':'Origin'} : {}),...headers}});
}
function allowedMethod(path, method) {
  if (['/api/v1/health','/api/v1/schema','/api/v1/telemetry/audit-logs','/api/v1/query/stream'].includes(path)) return method === 'GET';
  if (['/api/v1/auth/login','/api/v1/query/classify','/api/v1/query/execute'].includes(path)) return method === 'POST';
  if (/^\/api\/v1\/query\/jobs\/[0-9a-f-]{36}$/.test(path)) return method === 'GET';
  if (/^\/api\/v1\/query\/jobs\/[0-9a-f-]{36}\/cancel$/.test(path)) return method === 'POST';
  return false;
}
export async function handle(request, env, fetchOrigin = fetch) {
  const url = new URL(request.url);
  const origin = request.headers.get('Origin');
  const origins = (env.ALLOWED_ORIGINS || '').split(',').filter(Boolean);
  if (!origins.length || !env.IP_LIMITER || !env.LOGIN_LIMITER || !env.SESSION_KEY_B64 || !env.ORIGIN_URL || !env.ACCESS_CLIENT_ID || !env.ACCESS_CLIENT_SECRET) return reply(503,'GATEWAY_CONFIGURATION','Gateway configuration is unavailable.');
  if (origin && !origins.includes(origin)) return reply(403,'ORIGIN_REJECTED','Origin is not authorized.');
  if ([...url.searchParams.keys()].some(key => /token|authorization|password/i.test(key))) return reply(400,'URL_CREDENTIALS','Credentials must not appear in URLs.',origin);
  const ip = request.headers.get('CF-Connecting-IP');
  if (!ip) return reply(403,'EDGE_CONTEXT_REQUIRED','Trusted edge context is required.',origin);
  const limiter = url.pathname === '/api/v1/auth/login' ? env.LOGIN_LIMITER : env.IP_LIMITER;
  try {
    if (!(await limiter.limit({key:ip})).success) return reply(429,'EDGE_RATE_LIMIT','Request rate exceeded.',origin,{'Retry-After':'60'});
  } catch { return reply(503,'RATE_LIMIT_UNAVAILABLE','Admission control is unavailable.',origin); }
  if (request.method === 'OPTIONS') {
    const requested = request.headers.get('Access-Control-Request-Method');
    const headers = (request.headers.get('Access-Control-Request-Headers') || '').toLowerCase().split(',').map(s=>s.trim()).filter(Boolean);
    if (!origin || !allowedMethod(url.pathname,requested) || headers.some(h=>!['authorization','content-type'].includes(h))) return reply(403,'CORS_REJECTED','Preflight is not authorized.',origin);
    return new Response(null,{status:204,headers:{'Access-Control-Allow-Origin':origin,'Vary':'Origin',
      'Access-Control-Allow-Methods':'GET, POST, OPTIONS','Access-Control-Allow-Headers':'Authorization, Content-Type',
      'Access-Control-Max-Age':'600','Cache-Control':'no-store'}});
  }
  if (!allowedMethod(url.pathname,request.method)) return reply(404,'ROUTE_NOT_FOUND','API route was not found.',origin);
  const stream = url.pathname === '/api/v1/query/stream';
  if (stream && (request.headers.get('Upgrade') || '').toLowerCase() !== 'websocket') return reply(426,'WEBSOCKET_REQUIRED','WebSocket upgrade is required.',origin);
  const publicRoute = url.pathname === '/api/v1/auth/login' || url.pathname === '/api/v1/health';
  if (!publicRoute && !stream) {
    const match = /^Bearer ([A-Za-z0-9_.-]+)$/.exec(request.headers.get('Authorization') || '');
    try { await verifySession(match?.[1],env.SESSION_KEY_B64,Number(env.SESSION_TTL || '900')); }
    catch { return reply(401,'INVALID_SESSION','Invalid or expired session token.',origin); }
  }
  if (Number(request.headers.get('Content-Length') || 0) > 16384) return reply(413,'REQUEST_LIMIT','Request body is too large.',origin);
  let target;
  try {
    target = new URL(env.ORIGIN_URL);
    if (target.protocol !== 'https:' || target.username || target.password || target.search || target.hash || target.pathname !== '/' || target.host === url.host) throw new Error();
    target.pathname = url.pathname; target.search = url.search;
  } catch { return reply(503,'GATEWAY_CONFIGURATION','Origin routing is unavailable.',origin); }
  const forwarded = new Request(target,request);
  for (const header of ['Host','Cookie','CF-Access-Client-Id','CF-Access-Client-Secret','X-Forwarded-For']) forwarded.headers.delete(header);
  if (Boolean(env.ACCESS_CLIENT_ID) !== Boolean(env.ACCESS_CLIENT_SECRET)) return reply(503,'GATEWAY_CONFIGURATION','Origin authentication is unavailable.',origin);
  if (env.ACCESS_CLIENT_ID) {
    forwarded.headers.set('CF-Access-Client-Id',env.ACCESS_CLIENT_ID);
    forwarded.headers.set('CF-Access-Client-Secret',env.ACCESS_CLIENT_SECRET);
  }
  forwarded.headers.set('X-Forwarded-For',ip);
  try {
    const response = await fetchOrigin(forwarded,{redirect:'manual',signal:request.signal,cf:{cacheTtl:0,cacheEverything:false}});
    // Browser WebSockets authenticate in their first frame at FastAPI. Preserve the
    // 101 response untouched so disconnects reach the origin's cancellation hooks.
    if (stream) return response;
    if (response.status >= 300 && response.status < 400) return reply(502,'ORIGIN_REDIRECT','Unexpected origin redirect.',origin);
    const result = new Response(response.body,response);
    result.headers.set('Cache-Control','no-store');
    result.headers.delete('Set-Cookie');
    result.headers.delete('Access-Control-Allow-Origin');
    if (origin) result.headers.set('Access-Control-Allow-Origin',origin);
    result.headers.set('Vary','Origin');
    result.headers.set('X-Content-Type-Options','nosniff');
    return result;
  } catch { return reply(502,'ORIGIN_UNAVAILABLE','API origin is unavailable.',origin); }
}
export default {fetch:(request,env)=>handle(request,env)};
