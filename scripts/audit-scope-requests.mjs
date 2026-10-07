import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';
import {readFile,readdir,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {Session} from '@deepseek-ai/dsh-session';
// Imported assistant frames precede real dispatches; use the observed durable prefix cursor.
export async function auditScopeRequests(requestsFile,sessionsRoot,output){
 const requests=JSON.parse(await readFile(requestsFile,'utf8')),sessions=new Map(),checks=[];
 async function walk(dir){for(const entry of await readdir(dir,{withFileTypes:true})){const p=join(dir,entry.name);if(entry.isDirectory())await walk(p);else if(entry.name==='session.v4.jsonl'){const [stored,...events]=(await readFile(p,'utf8')).trim().split('\n').map(JSON.parse);const {type,...header}=stored;assert.equal(type,'session');assert.ok(!sessions.has(header.id));sessions.set(header.id,{header,events});}}}
 await walk(sessionsRoot);assert.ok(requests.length);
 for(const row of requests){
  const {header,events}=sessions.get(row.sessionId)??{};assert.ok(header);assert.equal(header.isSeeded,false);assert.ok(Number.isSafeInteger(row.prefixEndSeq));
  const prefix=events.filter(e=>e.seq<=row.prefixEndSeq);assert.equal(prefix.at(-1)?.seq,row.prefixEndSeq);
  const restored=Session.fromRestore(row.sessionId,prefix,header,0,'detached');assert.ok(isDeepStrictEqual([...restored.deriveMessages()],row.messages),'Observed input mismatches saved prefix '+row.sessionId);
  checks.push({sessionId:row.sessionId,prefixEndSeq:row.prefixEndSeq,matches:true});
 }
 const result={status:'PASS',observedRequests:checks.length,realModelRequests:0,checks};await writeFile(output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});return result;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){const r=await auditScopeRequests(...process.argv.slice(2));console.log(JSON.stringify({status:r.status,observedRequests:r.observedRequests,realModelRequests:0}));}
