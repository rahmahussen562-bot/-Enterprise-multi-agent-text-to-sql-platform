import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
const root = resolve(import.meta.dirname, '..');
for (const [key, name] of Object.entries({ TEMP:'tmp', TMP:'tmp', TMPDIR:'tmp', npm_config_cache:'npm-cache', PLAYWRIGHT_BROWSERS_PATH:'browsers' })) {
  const folder = resolve(root, '.runtime', name); mkdirSync(folder, {recursive:true}); process.env[key] = folder;
}
const run = (file, args) => new Promise(resolveExit => {
  const child = spawn(process.execPath, [resolve(root, 'node_modules', file), ...args], {cwd:root, env:process.env, stdio:'inherit'});
  child.on('exit', code => resolveExit(code ?? 1)); child.on('error', () => resolveExit(1));
});
const action = process.argv[2];
if (action === 'build') {
  const code = await run('typescript/bin/tsc', ['--noEmit']); if (code) process.exit(code);
  process.exit(await run('vite/bin/vite.js', ['build']));
} else if (action === 'test') process.exit(await run('vitest/vitest.mjs', ['run','--reporter=default','--reporter=junit','--outputFile=.runtime/frontend-tests.xml','--maxWorkers=1']));
else process.exit(await run('vite/bin/vite.js', [action === 'preview' ? 'preview' : '--host', ...(action === 'preview' ? ['--host','127.0.0.1'] : ['127.0.0.1'])]));
