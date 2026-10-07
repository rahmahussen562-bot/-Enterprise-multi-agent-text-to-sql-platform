import { describe, expect, it } from 'vitest';
import { apiBase, streamURL } from './routing';
describe('production endpoint configuration', () => {
  it('prefers the new API setting and retains the legacy setting', () => {
    expect(apiBase({api:'https://api.example.com/api/v1/', legacy:'/old'})).toBe('https://api.example.com/api/v1');
    expect(apiBase({legacy:'/api/v1/'})).toBe('/api/v1');
  });
  it('derives a secure stream from the API origin', () => {
    expect(streamURL('https://api.example.com/api/v1', undefined, 'https://portal.pages.dev')).toBe('wss://api.example.com/api/v1/query/stream');
  });
  it('supports a separately routed stream origin', () => {
    expect(streamURL('/api/v1', 'wss://stream.example.com/api/v1/', 'https://portal.pages.dev')).toBe('wss://stream.example.com/api/v1/query/stream');
  });
  it('supports local HTTP and relative development routes', () => {
    expect(apiBase({api:'http://127.0.0.1:8000/api/v1'})).toContain('127.0.0.1');
    expect(streamURL('/api/v1', undefined, 'http://localhost:5173')).toBe('ws://localhost:5173/api/v1/query/stream');
  });
  it.each(['http://api.example.com/api/v1','https://user:secret@api.example.com/api/v1','//evil.example/api/v1','https://api.example/api/v1?token=private','https://api.example/api/v1#private'])('rejects unsafe API configuration %s', api => {
    expect(() => apiBase({api})).toThrow();
  });
  it('rejects insecure remote and token-bearing streams', () => {
    expect(() => streamURL('/api/v1','ws://api.example.com/api/v1','https://portal.pages.dev')).toThrow();
    expect(() => streamURL('/api/v1','wss://api.example.com/api/v1?token=secret','https://portal.pages.dev')).toThrow();
  });
});
