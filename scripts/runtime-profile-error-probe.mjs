import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {LlmAdapter} from '@deepseek-ai/dsh-llm';
import {Session} from '@deepseek-ai/dsh-session';
import {decidePersonaLearning,NATIVE_LEARNING_POLICY,PARTIAL_LEARNING_POLICY} from './personamem-learning-policy.mjs';
import {collectPersonaNativeRuns} from './personamem-native-learning-policy.mjs';
export const name='dsh-rsi-profile-error-probe';
export const inject=['rsi','llm','sessionPersistence'];
export function apply(ctx,config){
 const requests=[];let recovery=false;
 class Fixture extends LlmAdapter{
  async *stream(options){
   const {signal,...request}=options;const h=await ctx.sessionPersistence.open(options.sessionId,'read'),stored=await h.read();await h.close();
   const row={...structuredClone(request),phase:'learning',prefixEndSeq:stored.events.at(-1).seq,status:'DISPATCHING',usage:null};requests.push(row);
   if(!recovery)assert.equal(requests.length,1,'Quota must prevent every subsequent provider stream');
   const block=recovery?(requests.length%2?{type:'tool-call',id:'fixture-write-'+requests.length,name:'write',arguments:JSON.stringify({path:'persona.md',content:'# 恢复画像\n仅为成功写入夹具，不是质量或效果验证。'})}:{type:'text',text:'Saved.'}):{type:'tool-call',id:'fixture-read-old-persona',name:'read',arguments:JSON.stringify({path:'persona.md'})};
   try{yield{type:'block-start',index:0,blockType:block.type};yield{type:'block-end',index:0,block};row.usage={inputTokens:13,outputTokens:7,totalTokens:20};yield{type:'usage',usage:row.usage};yield{type:'finish',reason:{kind:block.type==='tool-call'?'tool-calls':'stop'}};row.status='RETURNED';}finally{row.finishedAt=Date.now();}
  }
 }
 ctx.effect(()=>ctx.llm.registerAdapter(['rsi-probe'],new Fixture()));
 ctx.effect(()=>{
  const alive=setInterval(()=>{},1000),timer=setTimeout(async()=>{try{
   await ctx.rsi.ready;const cwd=join(config.root,'workspace-profile');await mkdir(cwd,{recursive:true});const runtime=ctx.rsi.runtime,entry=await runtime.scope(cwd);
   if(config.phase==='restore'){
    const snapshot=await runtime.snapshot(cwd);assert.equal(requests.length,0);assert.equal(snapshot.nativeProfileCalls.length,2);assert.ok(snapshot.nativeProfileCalls.every(call=>call.status==='failed'&&call.error.code==='BUDGET_EXHAUSTED'&&call.blockedDispatch.reason==='HOST_LEARNING_QUOTA'));assert.ok(snapshot.profilePending);assert.equal(snapshot.usage.calls,1);const oldFiles=await Promise.all(snapshot.nativeProfileCalls.map(async call=>({path:join(runtime.directory,'learning-runs',call.sessionId+'.json'),bytes:await readFile(join(runtime.directory,'learning-runs',call.sessionId+'.json'))})));
    recovery=true;runtime.state.configure({dailyCallBudget:5,learningEnabled:true});
    for(const scope of [entry.id,'global'])assert.equal(await (await runtime.core(scope)).generatePersona(true),true);
    const recovered=await runtime.snapshot(cwd);assert.equal(requests.length,4);assert.ok(recovered.nativeProfileCalls.every(call=>call.status==='completed'));assert.ok(!recovered.profilePending);assert.equal(recovered.usage.calls,5);assert.equal(recovered.usage.totalTokens,100);
    for(const original of oldFiles)assert.deepEqual(await readFile(original.path),original.bytes,'Original failed run is preserved after successful recovery');
    await writeFile(join(config.root,'restored.json'),JSON.stringify({status:'PASS',requestsBeforeRecovery:0,fixtureRecoveryRequests:4,profileFailuresPreserved:2,budgetEvidencePreserved:true,successfulNativeRecoveryClearsLatestFailure:true,profilePendingAfterRecovery:false,realProviderRequests:0}));process.exit(0);
   }
   runtime.state.configure({dailyCallBudget:1,learningEnabled:true});
   const seed=async core=>{const date=new Date().toISOString();await core.profile.writeFile('.metadata/scene_index.json',JSON.stringify([{filename:'fixture.md',summary:'隔离场景',heat:1,created:date,updated:date}]));await core.profile.writeFile('scene_blocks/fixture.md','# 场景\n这是隔离夹具。');await core.profile.writeFile('persona.md','# 已有画像\n这不是学习效果验证。');await core.storeMemory({id:'fixture-memory',sessionKey:'fixture',sessionId:'fixture',content:'隔离画像失败验收。',type:'episodic',priority:70,scene_name:'隔离场景',source_message_ids:['fixture-source'],metadata:{}});await core.checkpoint.incrementScenesProcessed();};
   const core=await runtime.core(entry.id);await seed(core);const checkpoint=await core.checkpoint.read();await assert.rejects(core.generatePersona(true),e=>e.code==='BUDGET_EXHAUSTED');assert.deepEqual(await core.checkpoint.read(),checkpoint);
   const global=await runtime.core('global');await seed(global);await assert.rejects(global.generatePersona(true),e=>e.code==='BUDGET_EXHAUSTED');
   const snapshot=await runtime.snapshot(cwd);assert.equal(requests.length,1);assert.equal(runtime.active.size,0);assert.equal(snapshot.usage.calls,1);assert.equal(snapshot.usage.totalTokens,20);assert.equal(snapshot.usage.unknownUsage,0);assert.ok(snapshot.profilePending);assert.ok(snapshot.nativeProfiles.some(p=>p.trigger.should));
   const proofs=[];
   for(const call of snapshot.nativeProfileCalls){
    assert.equal(call.status,'failed');assert.equal(call.error.code,'BUDGET_EXHAUSTED');assert.equal(call.blockedDispatch.reason,'HOST_LEARNING_QUOTA');assert.equal(call.blockedDispatch.usedReservations,1);assert.equal(call.blockedDispatch.callBudget,1);
    const run=JSON.parse(await readFile(join(runtime.directory,'learning-runs',call.sessionId+'.json'),'utf8'));assert.deepEqual(run,call);
    const handle=await ctx.sessionPersistence.open(call.sessionId,'read');let stored;try{stored=await handle.read();const end=stored.events.findLast(e=>e.type==='turn/end');assert.equal(end.data.reason.error.code,'BUDGET_EXHAUSTED');if(call.scope===entry.id){const firstHeader=stored.events.find(e=>e.type==='request/header');const restored=Session.fromRestore(call.sessionId,stored.events.slice(0,firstHeader.seq+1),handle.header,handle.inheritedEventCount,stored.eventState);assert.deepEqual([...restored.deriveMessages()],requests[0].messages);assert.equal(call.blockedDispatch.requestId,call.sessionId+':2');assert.ok(stored.events.some(e=>e.type==='tool/result'));}else{assert.equal(call.blockedDispatch.requestId,call.sessionId+':1');assert.ok(!stored.events.some(e=>e.type==='assistant/message'));}}finally{await handle.close();}
    proofs.push({scope:call.scope,sessionId:call.sessionId,errorCode:call.error.code,blockedDispatch:call.blockedDispatch,nativeJournalSha256:createHash('sha256').update(JSON.stringify(stored.events)).digest('hex'),nativeTerminalErrorVerified:true});
   }
   runtime.state.configure({learningEnabled:false});
   const gateSnapshot=await runtime.snapshot(cwd),nativeRuns=await collectPersonaNativeRuns(ctx,ctx.rsi);
   const gateInput={policy:NATIVE_LEARNING_POLICY,settled:false,snapshot:gateSnapshot,activeCount:runtime.active.size,expectedL0:0,requests,callLimit:1,nativeRuns};
   const disposition=decidePersonaLearning(gateInput);assert.equal(disposition.complete,false);assert.equal(disposition.failedJobs.length,0);assert.equal(disposition.failedProfiles.length,2);
   const controls=[{name:'actual-post-tool-and-zero-dispatch-profile-quota',status:disposition.status}];
   const reject=(name,change)=>{const input=structuredClone(gateInput);change(input);assert.throws(()=>decidePersonaLearning(input));controls.push({name,rejected:true});};
   reject('old-partial-policy-still-rejects-profile-only',v=>v.policy=PARTIAL_LEARNING_POLICY);
   reject('strict-default-still-rejects',v=>delete v.policy);
   reject('active-native-call',v=>v.activeCount=1);
   reject('learning-not-disabled',v=>v.snapshot.settings.learningEnabled=true);
   reject('pending-queue',v=>v.snapshot.nativePipelines[0].queues.l2Pending=true);
   reject('missing-L0',v=>v.expectedL0=1);
   reject('unfinished-dispatch',v=>v.requests[0].status='DISPATCHING');
   reject('missing-native-log',v=>v.nativeRuns=[]);
   reject('changed-native-event',v=>v.nativeRuns[0].events.pop());
   reject('changed-native-input',v=>v.requests[0].messages[0].content[0].text+=' altered');
   reject('snapshot-vs-persisted-run-mismatch',v=>v.snapshot.nativeProfileCalls[0].error.code='UNKNOWN');
   reject('quota-below-fixed-cap',v=>v.callLimit=2);
   reject('reservation-is-not-actual-dispatch',v=>v.snapshot.usage.calls=2);
   reject('invented-failed-history-job',v=>v.snapshot.jobs.push({id:'invented',status:'failed',stages:{failure:{code:'ABORTED'}}}));
   reject('failed-learning-is-not-complete',v=>v.settled=true);
   reject('blocked-step-was-actually-dispatched',v=>{const call=v.snapshot.nativeProfileCalls.find(c=>c.scope===entry.id);call.blockedDispatch.requestId=call.sessionId+':1';const item=v.nativeRuns.find(r=>r.record.sessionId===call.sessionId);item.record=structuredClone(call);});
   // Exercise the real pre-dispatch guard on an empty synthetic queued source, not a fake failed row.
   runtime.state.configure({learningEnabled:true});const precheckSource='fixture-quota-precheck';
   runtime.state.enqueue({scope:entry.id,cwd,sessionId:precheckSource,turn:1,endSeq:0,messages:[],events:[]});
   await assert.rejects(runtime.process(entry.id,precheckSource),e=>e.code==='BUDGET_EXHAUSTED'&&e.blockedDispatch?.reason==='HOST_LEARNING_QUOTA_PRECHECK');
   assert.equal(requests.length,1,'History precheck refusal has no model dispatch');runtime.state.configure({learningEnabled:false});
   const precheckInput={...gateInput,snapshot:await runtime.snapshot(cwd)},precheckDisposition=decidePersonaLearning(precheckInput);assert.equal(precheckDisposition.failedJobs.length,1);assert.equal(precheckDisposition.failedProfiles.length,2);
   const precheckFreezeProof={input:precheckInput,disposition:precheckDisposition,actualAdditionalRequests:0,sourceKind:'empty synthetic queue; exercises real process quota guard, not a dataset history'};
   const nativeFreezeProof={gateInput,disposition,controls,scope:'Installed-host native profile-quota fixture; no real dataset history, foreground answers, quality or benefit claim.'};
   await writeFile(join(config.root,'result.json'),JSON.stringify({status:'PASS',realProviderRequests:0,fixtureDispatches:1,taskCommandsExecuted:0,knownFixtureTokens:20,unknownUsage:0,proofs,nativeFreezeProof,precheckFreezeProof,checks:['existing-persona-does-not-mask-post-tool-quota-failure','first-request-quota-denial-has-zero-dispatch','structured-run-outcome-matches-snapshot','original-native-terminal-error-and-blocked-request-ID-match','only-actual-first-request-usage-counted','failure-checkpoint-and-pending-trigger-preserved','actual-request-reconstructs-from-native-prefix'],limitation:'Isolated installed-host fixture; no real profile-quality claim and no new experiment failure policy.'}));process.exit(0);
  }catch(error){console.error(error.stack);process.exit(1);}},0);
  return()=>{clearInterval(alive);clearTimeout(timer);};
 });
}
