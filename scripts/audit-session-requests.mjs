import assert from 'node:assert/strict';
import {readFile,readdir,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {Session} from '@deepseek-ai/dsh-session';

// Offline audit of unseeded pilot sessions; never dispatches a model request.
export async function auditRequests(requestsFile,sessionsRoot,outputFile) {
assert.ok(requestsFile&&sessionsRoot&&outputFile,'Usage: node scripts/audit-session-requests.mjs REQUESTS_JSON SESSIONS_DIR OUTPUT_JSON');
assert.notEqual(resolve(requestsFile),resolve(outputFile),'Do not overwrite observed requests');
const input=JSON.parse(await readFile(requestsFile,'utf8'));
const requests=Array.isArray(input)?input:input.requests;
assert.ok(Array.isArray(requests)&&requests.length,'No observed requests');
const paths=[];
async function walk(dir){for(const entry of await readdir(dir,{withFileTypes:true})){const path=join(dir,entry.name);if(entry.isDirectory())await walk(path);else if(entry.name==='session.v4.jsonl')paths.push(path);}}
await walk(sessionsRoot);
const sessions=new Map();
for(const path of paths){const [stored,...events]=(await readFile(path,'utf8')).trim().split('\n').map(JSON.parse);const {type,...header}=stored;assert.equal(type,'session');assert.equal(header.version,4);assert.ok(!sessions.has(header.id),'Duplicate session ID');sessions.set(header.id,{header,events});}
const checks=[];
for(const id of new Set(requests.map(r=>r.sessionId))){
 const {header,events}=sessions.get(id)??{};assert.ok(header,'Missing stored session '+id);assert.equal(header.isSeeded,false,'Forked sessions require a persistence-backed audit');
 const frames=events.filter(e=>['assistant/message','assistant/attempt'].includes(e.type));const sent=requests.filter(r=>r.sessionId===id);assert.ok(frames.length>=sent.length-1,'Multiple missing dispatch frames '+id);
 // request/header is an envelope change, not a marker for every dispatch.
 for(let i=0;i<sent.length;i++){const pending=!frames[i];
 if(pending){assert.equal(i,sent.length-1);assert.equal(sent[i].status,'DISPATCHING');assert.ok(!events.some(e=>e.type==='turn/end'),'Missing frame in ended turn '+id);}
 const prefix=pending?events:events.slice(0,events.indexOf(frames[i]));const restored=Session.fromRestore(id,prefix,header,0,'detached');assert.deepEqual([...restored.deriveMessages()],sent[i].messages);checks.push({sessionId:id,request:i+1,prefixEndSeq:prefix.at(-1)?.seq,matches:true,responseFramePresent:!pending});}
}
await writeFile(outputFile,JSON.stringify(checks,null,2));return {status:'PASS',observedRequests:checks.length,pendingResponses:checks.filter(c=>!c.responseFramePresent).length,modelCalls:0};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href) console.log(JSON.stringify(await auditRequests(...process.argv.slice(2))));
