import fs from 'node:fs/promises';
import { resolve } from 'node:path';
import openapiTS, { astToString } from 'openapi-typescript';
const root=resolve(import.meta.dirname,'..');
const result=astToString(await openapiTS(new URL('../openapi.json',import.meta.url)));
const file=resolve(root,'src/api/generated.ts');
if(process.argv.includes('--check')) {
  if(await fs.readFile(file,'utf8') !== result) throw new Error('API types drifted. Run npm run generate:api.');
} else { await fs.mkdir(resolve(root,'src/api'),{recursive:true}); await fs.writeFile(file,result); }
console.log('OpenAPI client contracts verified.');
