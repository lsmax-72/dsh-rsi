import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {parseSkillFile} from '../lib/core-entry.js';
import {auditRequests} from './audit-session-requests.mjs';

// Saved observations only. Do not repair generated assets or dispatch a model during audit.
const [root,output]=process.argv.slice(2);
assert.ok(root&&output,'Usage: node scripts/audit-default-flow.mjs ROOT OUTPUT_JSON');
const hash=value=>createHash('sha256').update(value).digest('hex');
const records=[];
for(const run of ['run','retry']) {
  const base=join(root,run),dir=join(base,'state/pilot/preflight');
  const read=async name=>JSON.parse(await readFile(join(dir,name),'utf8'));
  const requests=await read('model-requests.json'),receipt=await read('receipt.json');
  const initial=await read('initial.json');
  assert.equal(initial.assets.memory.length,0);assert.equal(initial.assets.skills.length,0);
  assert.equal(initial.settings.learningEnabled,true);
  assert.equal(initial.settings.everyNConversations,2);assert.equal(initial.settings.idleSeconds,30);
  const wire=(await readFile(join(base,'gateway.log'),'utf8')).trim().split('\n').map(JSON.parse);
  const forwarded=wire.filter(r=>r.request&&r.model);
  assert.equal(forwarded.length,requests.length);
  assert.ok(forwarded.every(r=>r.enableThinking===false&&!r.messageRoles.includes('developer')));
  const audit=await auditRequests(join(dir,'model-requests.json'),join(base,'state/home/sessions'),output+'.'+run+'.reconstruction.json');
  assert.equal(audit.observedRequests,requests.length);assert.equal(audit.pendingResponses,0);
  const usage={};
  for(const phase of ['source','consumer','learning']) {
    const rows=requests.filter(r=>r.phase===phase);
    usage[phase]={requests:rows.length,unknownUsage:rows.filter(r=>!r.usage).length,
      ...Object.fromEntries(['inputTokens','outputTokens','totalTokens'].map(key=>[key,rows.reduce((n,r)=>n+(r.usage?.[key]??0),0)]))};
  }
  records.push({run,dir,requests,receipt,wire,usage});
}
assert.ok(records.reduce((n,r)=>n+r.requests.length,0)<=25,'Do not exceed combined preflight cap');
const retry=records[1];
const assets=JSON.parse(await readFile(join(retry.dir,'assets.json'),'utf8'));
const events=(await readFile(join(retry.dir,'source-events.jsonl'),'utf8')).trim().split('\n').map(JSON.parse);
const source='pilot-preflight-source',consumer='pilot-preflight-consumer';
assert.equal(retry.receipt.phases.find(p=>p.phase==='source').stopReason.kind,'completed');
const sourceIds=new Set(events.filter(r=>r.sessionId===source).flatMap(r=>r.event.type==='user/message'?[r.event.data.id]:r.event.type==='assistant/message'?[r.event.data.message.id]:[]));
const consumerRequests=retry.requests.filter(r=>r.sessionId===consumer);
const memory=assets.memory.map(m=>{
  assert.ok(m.source_message_ids.length&&m.source_message_ids.every(id=>sourceIds.has(id)));
  const delivered=consumerRequests.flatMap((r,i)=>r.messages.some(msg=>msg.source?.kind==='dsh-rsi'&&msg.source.form==='memory'&&msg.source.refs.some(ref=>ref.scope===assets.scope&&ref.memories.some(row=>row.id===m.id&&row.version===m.version&&row.content===m.content))&&msg.content.some(b=>b.type==='text'&&b.text.includes(m.content)))?[i+1]:[]);
  return {id:m.id,version:m.version,scope:assets.scope,sourceMessageIds:m.source_message_ids,bodySha256:hash(m.content),requests:delivered};
});
assert.ok(memory.length&&memory.every(m=>m.requests.length));
const calls=events.filter(r=>r.sessionId===consumer&&r.event.type==='tool/call'&&r.event.data.name==='skill');
const skills=assets.skills.map(({head})=>{
  const body=parseSkillFile(head.content).body,name='rsi-'+head.name;
  const callIds=calls.filter(r=>JSON.parse(r.event.data.arguments).name===name).map(r=>r.event.data.callId);
  const ids=consumerRequests.flatMap((r,i)=>r.messages.some(m=>m.role==='tool'&&!m.isError&&callIds.includes(m.toolCallId)&&m.content.some(b=>b.type==='text'&&b.text.includes(body)))?[i+1]:[]);
  assert.equal(head.task_id,source+':1');
  return {id:head.skill_id,name,version:head.version,scope:assets.scope,sourceTaskId:head.task_id,bodySha256:hash(body),callIds,requests:ids};
});
assert.ok(skills.some(s=>s.requests.length));
const promptEvents=events.filter(r=>r.sessionId===consumer&&r.event.type==='user/message'&&r.event.data.source?.kind==='user');
 assert.ok(promptEvents.every(r=>!skills.some(s=>JSON.stringify(r.event.data).includes(s.name))),'Consumer must not name the generated Skill');
const layers=retry.receipt.after.layers[assets.scope];assert.equal(layers.L2,1);assert.equal(layers.L3,1);
assert.ok(assets.profileFiles.some(p=>p.path==='persona.md'));assert.ok(assets.profileFiles.some(p=>p.path.startsWith('scene_blocks/')));
const sourcePatch=await readFile(join(retry.dir,'prediction-source.patch'));
assert.ok(sourcePatch.toString().includes('notes/environment.md'));
assert.equal((await readFile(join(retry.dir,'prediction-consumer.patch'))).length,0);
const result={status:'DEFAULT_CAPTURE_AND_NATURAL_DELIVERY_PASS',formalBenchmarkStarted:false,
  sourceNormallyCompleted:true,consumerStopReason:retry.receipt.phases.find(p=>p.phase==='consumer').stopReason,
  memoryDelivered:true,skillNaturallyLoaded:true,memoryEvidence:memory,skillEvidence:skills,
  defaultLayers:layers,sourcePatchSha256:hash(sourcePatch),consumerPatchBytes:0,
  attempts:records.map(r=>({run:r.run,phases:r.receipt.phases,usage:r.usage,
    learningJobs:r.receipt.after.jobs.map(j=>({sourceSessionId:j.sourceSessionId,status:j.status,error:j.error}))})),
  totalForwardedRequests:records.reduce((n,r)=>n+r.requests.length,0),
  knownTotalTokens:records.reduce((n,r)=>n+Object.values(r.usage).reduce((k,u)=>k+u.totalTokens,0),0),
  unknownUsage:records.reduce((n,r)=>n+Object.values(r.usage).reduce((k,u)=>k+u.unknownUsage,0),0),
  reconstructedRequests:records.reduce((n,r)=>n+r.requests.length,0),auditModelCalls:0,
  limitations:['Consumer was cut off after two requests; natural Skill delivery passed but final response did not complete.',
    'L2/L3 creation observed; full-body consumption for these layers is not separately proven.',
    'Generated environmental prose retains inaccuracies; no manual correction or selection.',
    'No official issue-repair score or effectiveness claim for these maintenance tasks.']};
await writeFile(output,JSON.stringify(result,null,2));
console.log(JSON.stringify({status:result.status,totalForwardedRequests:result.totalForwardedRequests,knownTotalTokens:result.knownTotalTokens,unknownUsage:result.unknownUsage,layers,auditModelCalls:0}));
