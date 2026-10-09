import assert from 'node:assert/strict';
import {readFile,readdir,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import {Session} from '@deepseek-ai/dsh-session';
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {runInNewContext} from 'node:vm';

// Reuse the exact native fixed directive; do not maintain a copied instruction.
// The pinned image is trusted code, and evaluation is limited to its literal
// array expression, without imports, IO or access to the agent process.
async function nativeCompactionInstruction(){
 const require=createRequire(import.meta.url);
 const file=process.env.RSI_NATIVE_COMPACTION_MODULE??createRequire(require.resolve('@deepseek-ai/dsh-session')).resolve('@deepseek-ai/dsh-compaction-basic');
 const source=await readFile(file,'utf8');
 const expression=source.match(/const COMPACTION_INSTRUCTION = (\[[\s\S]*?\]\.join\("\\n"\));/);assert.ok(expression,'Native compaction directive shape changed');
 const tags=Object.fromEntries(['SUMMARY_OPEN_TAG','SUMMARY_CLOSE_TAG'].map(name=>{const value=source.match(new RegExp('const '+name+' = ("[^"]*");'));assert.ok(value);return [name,JSON.parse(value[1])];}));
 const instruction=runInNewContext(expression[1],tags,{timeout:100});
 assert.equal(typeof instruction,'string');return {instruction,sha256:createHash('sha256').update(source).digest('hex')};
}

// Offline audit of native stored prefixes, including durable fork cuts; no model dispatch.
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
 const {header,events}=sessions.get(id)??{};assert.ok(header,'Missing stored session '+id);const marker=events.filter(e=>e.type==='session/end-seed' && e.data.inherited===true).at(-1);
 const inherited=header.isSeeded?(assert.ok(marker,'Seeded session has no durable inherited cut'),marker.seq):0;
 assert.ok(!header.isSeeded || inherited<events.length);
 const frames=events.filter(e=>e.seq>=inherited && ['assistant/message','assistant/attempt'].includes(e.type));const sent=requests.filter(r=>r.sessionId===id);
 // New callers persist the exact dispatch prefix, which also covers native
 // compaction calls. The frame fallback is retained for old unseeded evidence.
 for(let i=0;i<sent.length;i++){let nativeCompactionModuleSha256;
 if(Number.isSafeInteger(sent[i].prefixEndSeq)){
   assert.ok(sent[i].prefixEndSeq>=inherited-1 && sent[i].prefixEndSeq<events.length);assert.equal(sent[i].inheritedEventCount,inherited);
   const prefix=events.slice(0,sent[i].prefixEndSeq+1),restored=Session.fromRestore(id,prefix,header,inherited,'detached');
   if(sent[i].purpose==='compaction'){
     assert.ok(prefix.some(e=>e.type==='compaction/start'),'No native compaction lifecycle');
     const native=await nativeCompactionInstruction(),last=sent[i].messages.at(-1);nativeCompactionModuleSha256=native.sha256;
     assert.equal(last.role,'user');assert.deepEqual(last.content,[{type:'text',text:native.instruction}]);
     // The native directive's UUID is provider-invisible. All replayed
     // identified messages must be exact, ordered members of the stored surface.
     const surface=[...restored.deriveMessages()];let at=-1;
     for(const message of sent[i].messages.slice(0,-1)){
       const index=surface.findIndex((candidate,j)=>j>at && candidate.id===message.id);
       assert.ok(index>=0,'Compaction input is not an ordered stored surface');assert.deepEqual(surface[index],message);at=index;
     }
   }else assert.deepEqual([...restored.deriveMessages()],sent[i].messages);checks.push({sessionId:id,request:i+1,prefixEndSeq:sent[i].prefixEndSeq,inheritedEventCount:inherited,purpose:sent[i].purpose??'task',nativeCompactionModuleSha256,matches:true,prefixOrigin:'observed immediately before dispatch'});continue;
 }
 assert.ok(frames.length>=sent.length-1,'Multiple missing dispatch frames '+id);const pending=!frames[i];
 if(pending){assert.equal(i,sent.length-1);assert.equal(sent[i].status,'DISPATCHING');assert.ok(!events.some(e=>e.seq>=inherited && e.type==='turn/end'),'Missing frame in ended turn '+id);}
 const prefix=pending?events:events.slice(0,events.indexOf(frames[i]));const restored=Session.fromRestore(id,prefix,header,inherited,'detached');assert.deepEqual([...restored.deriveMessages()],sent[i].messages);checks.push({sessionId:id,request:i+1,prefixEndSeq:prefix.at(-1)?.seq,inheritedEventCount:inherited,matches:true,responseFramePresent:!pending});}
}
await writeFile(outputFile,JSON.stringify(checks,null,2));return {status:'PASS',observedRequests:checks.length,pendingResponses:checks.filter(c=>!c.responseFramePresent).length,modelCalls:0};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href) console.log(JSON.stringify(await auditRequests(...process.argv.slice(2))));
