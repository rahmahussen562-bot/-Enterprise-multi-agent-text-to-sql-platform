export function pagesHeaders(settings = {}, strict = false) {
  const origins = new Set(["'self'"]);
  const api = settings.VITE_API_BASE_URL || settings.VITE_API_URL || '/api/v1';
  const ws = settings.VITE_WS_BASE_URL || api;
  if (strict && (!settings.VITE_API_BASE_URL || !settings.VITE_WS_BASE_URL)) throw new Error('Production deployment requires explicit API and WebSocket base URLs.');
  for (const [value, stream] of [[api, false], [ws, true]]) {
    if (value.startsWith('/') && !value.startsWith('//') && !/[?#\\\s]/.test(value)) continue;
    const url = new URL(value);
    if (stream && url.protocol === 'https:') url.protocol = 'wss:';
    if (stream && url.protocol === 'http:') url.protocol = 'ws:';
    if (!(stream ? ['wss:', 'ws:'] : ['https:', 'http:']).includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Unsafe deployment endpoint.');
    if (['http:', 'ws:'].includes(url.protocol) && (strict || !['localhost','127.0.0.1','[::1]'].includes(url.hostname))) throw new Error('Production endpoints require TLS.');
    origins.add(url.origin);
  }
  const csp = `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src ${[...origins].join(' ')}; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; worker-src 'self'; manifest-src 'self'`;
  return `/*\n  Content-Security-Policy: ${csp}\n  Strict-Transport-Security: max-age=31536000; includeSubDomains\n  X-Content-Type-Options: nosniff\n  X-Frame-Options: DENY\n  Referrer-Policy: no-referrer\n  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()\n  Cross-Origin-Opener-Policy: same-origin\n\n/index.html\n  Cache-Control: no-cache\n\n/assets/*\n  Cache-Control: public, max-age=31536000, immutable\n`;
}
