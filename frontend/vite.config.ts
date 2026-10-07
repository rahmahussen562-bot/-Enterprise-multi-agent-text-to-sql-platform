import { defineConfig, loadEnv } from 'vite';
import { writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pagesHeaders } from './tools/pages-security.mjs';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
export default defineConfig(({mode}) => ({
  plugins:[react(), tailwindcss(), { name:'sentinel-pages-security', writeBundle() {
    const settings = {...loadEnv(mode, process.cwd(), ''), ...process.env} as Record<string, string>;
    writeFileSync(resolve('dist/_headers'), pagesHeaders(settings, settings.SENTINEL_PRODUCTION_BUILD === '1'));
  }}], cacheDir:'.runtime/vite',
  server:{port:5173, strictPort:true, host:'127.0.0.1', proxy:{'/api':{target:'http://127.0.0.1:8000',ws:true},'/openapi.json':{target:'http://127.0.0.1:8000'}}},
  preview:{port:4173,strictPort:true}, build:{outDir:'dist', sourcemap:false, chunkSizeWarningLimit:750},
}));
