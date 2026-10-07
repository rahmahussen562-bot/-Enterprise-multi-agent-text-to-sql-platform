import fs from 'node:fs/promises';
import { resolve, relative } from 'node:path';
const root=resolve(import.meta.dirname,'..');
const hits=[];
async function scan(folder){
  for(const entry of await fs.readdir(folder,{withFileTypes:true})){
    const path=resolve(folder,entry.name);
    if(entry.isDirectory())await scan(path);
    else if(/\.(tsx?|css|html)$/.test(entry.name)){
      const source=await fs.readFile(path,'utf8');
      if(/\p{Extended_Pictographic}/u.test(source))hits.push(relative(root,path));
    }
  }
}
await scan(resolve(root,'src'));await scan(resolve(root,'public'));
const html=await fs.readFile(resolve(root,'index.html'),'utf8');
if(/\p{Extended_Pictographic}/u.test(html))hits.push('index.html');
const report={emojiFiles:hits,passed:!hits.length};
await fs.writeFile(resolve(root,'.runtime/source-audit.json'),JSON.stringify(report,null,2));
if(hits.length)throw new Error('Emoji policy violation: '+hits.join(', '));
console.log('Zero-emoji source policy verified.');
