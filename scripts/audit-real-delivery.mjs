import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {parseSkillFile} from '../lib/core-entry.js';

// Audit this saved pilot independently; never extracts assets or calls a model.
const [root,output]=process.argv.slice(2);
assert.ok(root&&output,'Usage: node scripts/audit-real-delivery.mjs PILOT2_ARTIFACTS OUTPUT_JSON');
const results=join(root,'final-recovery-results');
const read=async name=>JSON.parse(await readFile(join(results,name),'utf8'));
const requests=await read('model-requests.json'),journals=await read('journals.json');
const assets=await read('frozen-assets-before.json'),raw=await read('receipt.json');
const consumerId='pilot2-delivery-final';
const consumer=requests.filter(r=>r.sessionId===consumerId);
assert.ok(consumer.length,'No final consumer requests');
const scope=assets.scope;
const hash=text=>createHash('sha256').update(text).digest('hex');
const sourceMessages=new Map(journals.flatMap(j=>j.events).flatMap(e=>e.type==='user/message'?[[e.data.id,e.data]]:e.type==='assistant/message'?[[e.data.message.id,e.data.message]]:[]));
const memoryEvidence=assets.memory.map(memory=>{
 assert.ok(memory.source_message_ids.length,'Missing memory source');
 for(const id of memory.source_message_ids)assert.ok(sourceMessages.has(id),'Unknown source message '+id);
 const indexes=consumer.flatMap((r,i)=>r.messages.some(m=>m.source?.kind==='dsh-rsi'&&m.source.form==='memory'&&m.source.refs?.some(ref=>ref.scope===scope&&ref.memories.some(saved=>saved.id===memory.id&&saved.version===memory.version&&saved.content===memory.content))&&m.content.some(b=>b.type==='text'&&b.text.includes(memory.content)))?[i+1]:[]);
 return {id:memory.id,scope,version:memory.version,sourceSessionId:memory.sessionId,sourceMessageIds:memory.source_message_ids,contentSha256:hash(memory.content),requests:indexes};
});
const events=journals.find(j=>j.sessionId===consumerId).events;
const calls=events.filter(e=>e.type==='tool/call'&&e.data.name==='skill');
const skillEvidence=assets.skills.map(({head})=>{
 const name='rsi-'+head.name,body=parseSkillFile(head.content).body;
 const callIds=calls.filter(c=>JSON.parse(c.data.arguments).name===name).map(c=>c.data.callId);
 const indexes=consumer.flatMap((r,i)=>r.messages.some(m=>m.role==='tool'&&!m.isError&&callIds.includes(m.toolCallId)&&m.content.some(b=>b.type==='text'&&b.text.includes(body)))?[i+1]:[]);
 const reported=raw.skillEvidence.find(s=>s.id===head.skill_id);
 assert.equal(reported.version,head.version);assert.equal(reported.contentSha256,hash(body));
 return {id:head.skill_id,name,scope,version:head.version,sourceTaskId:head.task_id,contentSha256:hash(body),callIds,requests:indexes};
});
assert.ok(memoryEvidence.some(m=>m.requests.length),'No real memory body with valid identity');
assert.ok(skillEvidence.some(s=>s.requests.length),'No official Skill body in later request');
const usage={};let classified=0;
for(const phase of ['task','learning','consumer']){
 const rows=requests.filter(r=>phase==='task'?r.sessionId==='pilot2-task-11292':phase==='learning'?r.sessionId.startsWith('rsi-'):r.sessionId.startsWith('pilot2-delivery-'));
 classified+=rows.length;
 usage[phase]={requests:rows.length,missingUsage:rows.filter(r=>!r.usage).length,...Object.fromEntries(['inputTokens','outputTokens','totalTokens'].map(k=>[k,rows.reduce((sum,r)=>sum+(r.usage?.[k]??0),0)]))};
}
assert.equal(classified,requests.length,'Unclassified request: costs must not disappear');
const reconstructionFile=output+'.reconstruction.json';
execFileSync(process.execPath,[join(dirname(fileURLToPath(import.meta.url)),'audit-session-requests.mjs'),join(results,'model-requests.json'),join(root,'final-recovery-sessions'),reconstructionFile],{stdio:'pipe'});
const checks=JSON.parse(await readFile(reconstructionFile,'utf8'));assert.equal(checks.length,requests.length);
const knownTotalTokens=Object.values(usage).reduce((n,u)=>n+u.totalTokens,0);
const receipt={status:'ASSET_DELIVERY_PASS',consumerId,memoryDelivered:true,skillDelivered:true,memoryEvidence,skillEvidence,usage,knownTotalTokens,logReconstructionRequests:checks.length,rawProducerConsumerRequestCount:raw.usage.consumer.requests,auditCorrection:'Producer counted only the earlier consumer. Independent audit includes both diagnostic consumers and verifies every request belongs to one phase.',rawReceiptSha256:hash(await readFile(join(results,'receipt.json'))),modelCalls:0};
await writeFile(output,JSON.stringify(receipt,null,2));console.log(JSON.stringify({status:receipt.status,memoryAssets:memoryEvidence.length,skills:skillEvidence.length,requests:checks.length,knownTotalTokens,modelCalls:0}));
