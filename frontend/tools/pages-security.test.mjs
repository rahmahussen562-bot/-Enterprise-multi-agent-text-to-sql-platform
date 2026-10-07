import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pagesHeaders } from './pages-security.mjs';
test('CSP permits only the configured connections', () => {
  const headers = pagesHeaders({VITE_API_BASE_URL:'https://api.example.com/api/v1',VITE_WS_BASE_URL:'wss://api.example.com/api/v1'},true);
  assert.match(headers,/connect-src 'self' https:\/\/api.example.com wss:\/\/api.example.com;/);
  assert.doesNotMatch(headers,/connect-src[^;]* https: /);
  assert.match(headers,/microphone=\(\)/);
  assert.match(headers,/immutable/);
});
test('deployment fails without endpoints or with secrets in URLs', () => {
  assert.throws(() => pagesHeaders({},true));
  assert.throws(() => pagesHeaders({VITE_API_BASE_URL:'https://user:pw@host/api/v1'},false));
  assert.throws(() => pagesHeaders({VITE_API_BASE_URL:'https://host/api/v1?token=private'},false));
});
