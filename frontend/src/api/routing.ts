export function apiBase(config: { api?: string; legacy?: string } = {}) {
  const value = (config.api || config.legacy || '/api/v1').replace(/\/+$/, '');
  if (value.startsWith('/') && !value.startsWith('//') && !/[?#\\\s]/.test(value)) return value;
  const url = new URL(value);
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Invalid API base URL.');
  if (url.protocol === 'http:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) throw new Error('Remote API connections require HTTPS.');
  return url.toString().replace(/\/+$/, '');
}
export function streamURL(api: string, ws: string | undefined, pageOrigin: string) {
  const url = new URL((ws || api).replace(/\/+$/, '') + '/query/stream', pageOrigin);
  if (url.protocol === 'https:') url.protocol = 'wss:';
  if (url.protocol === 'http:') url.protocol = 'ws:';
  if (!['wss:', 'ws:'].includes(url.protocol) || url.username || url.password || url.search || url.hash) throw new Error('Invalid WebSocket base URL.');
  if (url.protocol === 'ws:' && !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)) throw new Error('Remote streaming requires WSS.');
  return url.toString();
}
