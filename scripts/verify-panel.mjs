import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const root=new URL('../vendor/panel/',import.meta.url);
const manifest=JSON.parse(await readFile(new URL('../source-manifest.json',root),'utf8')).panel;
for(const entry of manifest.files){const bytes=await readFile(new URL(entry.path,root));if(createHash('sha256').update(bytes).digest('hex')!==entry.sha256)throw Error(`Reused panel source changed: ${entry.path}`);}
console.log(`Verified ${manifest.files.length} reused panel files at ${manifest.revision}`);
