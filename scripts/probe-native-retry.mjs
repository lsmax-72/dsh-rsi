import {fixtureEmbedding} from './fixture-embedding.mjs';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,mkdir,rm} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname,join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
const repo=dirname(dirname(fileURLToPath(import.meta.url))),root=await mkdtemp('/private/tmp/dsh-rsi-native-retry-'),req=createRequire(join(repo,'package.json'));
const original=await readFile(join(repo,'lib/index.js'),'utf8');
await writeFile(join(root,'runtime.mjs'),original.replace(/from "([^"]+)"/g,(_,id)=>`from ${JSON.stringify(id.startsWith('node:')?id:pathToFileURL(id.startsWith('.')?join(repo,'lib',id):req.resolve(id)).href)}`)+'\nexport {Runtime};\n');
const {Runtime}=await import(pathToFileURL(join(root,'runtime.mjs')));
let capWarnings=0;const logger={info(){},warn(message){if(message.includes('max retries reached'))capWarnings++;},error(){},debug(){}};
const cwd=join(root,'workspace');await mkdir(cwd);
const runtime=new Runtime({logger,llm:{prepareCall(){throw Error('Network dispatch forbidden');}}},{cwd,settings:{learningEnabled:true},l2DelaySeconds:86400},join(root,'assets'),fixtureEmbedding());
const entry=await runtime.scope(cwd),core=await runtime.core(entry.id),pipeline=runtime.pipelines.get(entry.id);
// Test-only acceleration exercises the unchanged native timer and retry count.
pipeline.L1_RETRY_DELAY_MS=5;
core.createSkillExtractor=()=>({extract:async()=>({candidates:[]})});
let attempts={};core.extractMemories=async ({sessionId})=>{attempts[sessionId]=(attempts[sessionId]??0)+1;if(sessionId==='transient' && attempts[sessionId]>1)return {records:[],storedCount:0};throw Object.assign(new Error('FIXTURE_FAILURE'),sessionId==='permanent'?{code:'UNSUPPORTED_TOOL'}:{});};
const enqueue=sessionId=>{runtime.state.enqueue({scope:entry.id,cwd,sessionId,turn:1,endSeq:1,reason:{kind:'completed'},route:{provider:'fixture',model:'fixture'},messages:[{role:'user',content:'隔离重试验证',timestamp:new Date().toISOString()}],events:[]});const job=runtime.state.jobs(entry.id).find(j=>j.session===sessionId);runtime.state.updateJob(job.id,'pending',{recorded:true});return job;};
const waitUntil=async pred=>{for(let i=0;i<200&&!pred();i++)await new Promise(resolve=>setTimeout(resolve,5));assert.ok(pred(),'native retry condition timed out');};
try {
  const transient=enqueue('transient');await pipeline.notifyConversation('transient',[{role:'user',content:'隔离重试验证'}]);await pipeline.flushSession('transient');await waitUntil(()=>runtime.state.jobs(entry.id).find(j=>j.id===transient.id).status==='completed');assert.equal(attempts.transient,2);
  const persistent=enqueue('persistent');await pipeline.notifyConversation('persistent',[{role:'user',content:'持续失败验证'}]);await pipeline.flushSession('persistent');await waitUntil(()=>capWarnings>0);assert.equal(attempts.persistent,6);assert.equal(runtime.state.jobs(entry.id).find(j=>j.id===persistent.id).stages.failure.attempts,6);assert.equal(pipeline.sessionStates.get('persistent').l2_pending_l1_count,0);
  await assert.rejects(runtime.process(entry.id,'persistent'));assert.equal(attempts.persistent,6);
  const permanent=enqueue('permanent');await assert.rejects(runtime.process(entry.id,'permanent'),e=>e.code==='UNSUPPORTED_TOOL');await assert.rejects(runtime.process(entry.id,'permanent'),e=>e.code==='UNSUPPORTED_TOOL');assert.equal(attempts.permanent,1);assert.equal(runtime.state.jobs(entry.id).find(j=>j.id===permanent.id).stages.failure.retryable,false);
  const budget=enqueue('budget');runtime.state.configure({dailyCallBudget:0});await assert.rejects(runtime.process(entry.id,'budget'),e=>e.code==='BUDGET_EXHAUSTED');assert.equal(runtime.state.jobs(entry.id).find(j=>j.id===budget.id).status,'paused');assert.equal(attempts.budget,undefined);
  runtime.state.configure({dailyCallBudget:100});enqueue('missing-route');const missing=runtime.state.jobs(entry.id).find(j=>j.session==='missing-route');missing.payload.route=null;runtime.state.db.prepare('UPDATE jobs SET payload=? WHERE id=?').run(JSON.stringify(missing.payload),missing.id);await assert.rejects(runtime.process(entry.id,'missing-route'),e=>e.code==='MISSING_ROUTE');assert.equal(attempts['missing-route'],undefined);
  console.log(JSON.stringify({status:'PASS',checkedAt:new Date().toISOString(),realModelRequests:0,nativeRetryDelayProductionMs:30000,testTimerMs:5,nativeMaxRetries:5,attempts,checks:['transient-failure-recovered-by-native-timer','persistent-failure-six-attempt-ceiling','failed-L1-does-not-advance-L2','persisted-ceiling-survives-new-callback','permanent-error-no-model-retry','budget-pauses-without-dispatch','missing-route-pauses-without-dispatch']},null,2));
}finally{await runtime.stop();await rm(root,{recursive:true,force:true});}
