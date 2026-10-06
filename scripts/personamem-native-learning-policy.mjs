import {readFile,readdir} from 'node:fs/promises';
import {join} from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {Session} from '@deepseek-ai/dsh-session';
export const NATIVE_LEARNING_POLICY='evaluate-closed-native-failure-v2';
const digest=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');

/** Freeze the bounded product's existing assets; never relabel learning as successful. */
export function decideClosedNativeLearning({policy,settled,snapshot,activeCount,expectedL0,requests=[],blocked=[],nativeRuns=[],callLimit}){
 assert.equal(policy,NATIVE_LEARNING_POLICY);
 assert.ok(Number.isSafeInteger(expectedL0)&&expectedL0>=0);
 assert.ok(Number.isSafeInteger(callLimit)&&callLimit>0,'Missing frozen learning call limit');
 assert.equal(snapshot.layers[snapshot.workspace.id].L0,expectedL0,'Incomplete native history capture');
 assert.equal(snapshot.settings.learningEnabled,false,'Learning must be disabled before freezing');
 assert.equal(snapshot.settings.dailyCallBudget,callLimit,'Native budget differs from frozen cap');
 assert.equal(activeCount,0,'Learning is still active');
 assert.ok(snapshot.nativePipelines.length&&snapshot.nativePipelines.every(p=>p.queues.l1Idle&&p.queues.l2Idle&&p.queues.l3Idle&&!p.queues.l1Pending&&!p.queues.l2Pending&&!p.queues.l3Pending),'Native learning queues are not quiescent');
 assert.ok(Array.isArray(snapshot.jobs)&&snapshot.jobs.every(j=>['completed','failed','paused'].includes(j.status)),'Queued/running/interrupted history job');
 assert.ok(requests.length<=callLimit&&requests.every(r=>r.phase==='learning'&&['RETURNED','ERROR','INCOMPLETE'].includes(r.status)&&Number.isFinite(r.finishedAt)),'No terminal actual learning ledger');
 assert.equal(snapshot.usage.calls,requests.length,'Reservations differ from actual observed requests');
 assert.ok(Array.isArray(snapshot.nativeProfileCalls),'Missing native profile call state');
 assert.ok(snapshot.nativeProfileCalls.every(c=>['completed','failed'].includes(c.status)),'Profile call is still active or unclassified');
 const runs=new Map();
 for(const item of nativeRuns){
  const {record,events,header,inheritedEventCount}=item;
  assert.ok([snapshot.workspace.id,'global'].includes(record.scope),'Native run belongs to another workspace');
  assert.ok(record.sessionId.startsWith('rsi-')&&!runs.has(record.sessionId),'Duplicate/non-native session');
  assert.ok(['completed','failed'].includes(record.status)&&Number.isFinite(record.finishedAt),'Native run has no terminal outcome');
  assert.equal(item.eventsSha256,digest(events),'Native journal hash mismatch');
  const end=events.findLast(e=>e.type==='turn/end');assert.ok(end,'Missing native terminal event');
  assert.equal(events.at(-1).seq,end.seq,'Native journal continues after its terminal event');
  if(record.status==='completed')assert.equal(end.data.reason.kind,'completed','Completed run has no successful native end');
  else{
   assert.ok(['ABORTED','BUDGET_EXHAUSTED'].includes(record.error?.code),'Unclassified/infrastructure native failure');
   assert.ok(record.error.code==='ABORTED'?end.data.reason.kind==='aborted'||end.data.reason.error?.code==='ABORTED':end.data.reason.kind==='error'&&end.data.reason.error?.code==='BUDGET_EXHAUSTED','Run failure/native end mismatch');
  }
  const actual=requests.filter(r=>r.sessionId===record.sessionId),steps=new Set();
  for(const row of actual){
   assert.ok(Number.isSafeInteger(row.prefixEndSeq),'Missing dispatch prefix sequence');
   const prefix=events.filter(e=>e.seq<=row.prefixEndSeq);assert.equal(prefix.at(-1)?.seq,row.prefixEndSeq,'Dispatch prefix missing from journal');
   const step=prefix.findLast(e=>e.type==='step/start')?.data.step;assert.ok(Number.isSafeInteger(step)&&!steps.has(step),'Duplicate/native dispatch step');steps.add(step);
   // Reuse native replay; a receipt assertion alone is not dispatch reconstruction proof.
   const replay=Session.fromRestore(record.sessionId,prefix,header,inheritedEventCount);
   assert.deepEqual([...replay.deriveMessages()],row.messages,'Actual input differs from native durable prefix');
  }
  runs.set(record.sessionId,{...item,end,steps});
 }
 assert.ok(requests.every(r=>runs.has(r.sessionId)),'Actual learning request missing native terminal journal');
 for(const call of snapshot.nativeProfileCalls){assert.deepEqual(runs.get(call.sessionId)?.record,call,'Latest profile state differs from persisted native run');}
 const quota=(receipt,item)=>{
  assert.equal(snapshot.usage.calls,callLimit,'Quota stop without the declared actual request count');
  assert.equal(receipt?.usedReservations,callLimit,'Quota reservations differ from actual cap');
  assert.equal(receipt?.callBudget,callLimit,'Quota receipt changed frozen budget');
  assert.equal(receipt.day,snapshot.usage.day,'Quota day mismatch');assert.ok(Number.isFinite(receipt.observedAt),'Missing quota time');
  if(item){
   assert.equal(receipt.reason,'HOST_LEARNING_QUOTA','Native run cannot use a history precheck receipt');
   assert.equal(receipt.scope,item.record.scope);assert.equal(receipt.task,item.record.taskId);
   const step=item.events.findLast(e=>e.type==='step/start')?.data.step;
   assert.equal(receipt.requestId,item.record.sessionId+':'+step,'Blocked request/native step mismatch');
   assert.ok(!item.steps.has(step),'Quota-denied request was counted as dispatched');
  }else assert.equal(receipt.reason,'HOST_LEARNING_QUOTA_PRECHECK','Missing native quota refusal receipt');
 };
 const failedJobs=snapshot.jobs.filter(j=>j.status!=='completed');
 for(const job of failedJobs){
  const code=job.stages?.failure?.code;assert.ok(['ABORTED','BUDGET_EXHAUSTED'].includes(code),'Unclassified/infrastructure history job failure');
  const matches=[...runs.values()].filter(item=>item.record.jobId===job.id&&item.record.sourceSessionId===job.sourceSessionId&&item.record.status==='failed'&&item.record.error.code===code);
  if(code==='ABORTED')assert.ok(matches.length,'Aborted job has no original native aborted run');
  else{
   const receipt=job.stages.failure.blockedDispatch;
   if(receipt?.reason==='HOST_LEARNING_QUOTA_PRECHECK'){assert.equal(receipt.jobId,job.id);assert.equal(receipt.scope,snapshot.workspace.id);quota(receipt);}
   else{assert.ok(matches.length,'Budget job has no native failed run');assert.ok(matches.some(item=>digest(item.record.blockedDispatch)===digest(receipt)),'Job/native blocked receipt mismatch');quota(receipt,matches.find(item=>digest(item.record.blockedDispatch)===digest(receipt)));}
  }
 }
 const failedProfiles=snapshot.nativeProfileCalls.filter(c=>c.status==='failed');
 for(const call of failedProfiles){const item=runs.get(call.sessionId);assert.ok(['L2','L3'].includes(call.layer),'Unknown profile layer');if(call.error.code==='BUDGET_EXHAUSTED')quota(call.blockedDispatch,item);}
 for(const item of runs.values())if(item.record.status==='failed')assert.ok(failedProfiles.some(c=>c.sessionId===item.record.sessionId)||failedJobs.some(j=>j.id===item.record.jobId),'Unattributed failed native run');
 if(settled){
  assert.equal(failedJobs.length+failedProfiles.length,0,'Failed learning was labelled complete');
  assert.equal(snapshot.profilePending,false,'Settled learning has pending profile work');
  assert.ok(snapshot.nativeProfiles.every(p=>!p.trigger.should),'Native profile trigger still pending');
  return {policy,status:'COMPLETED',complete:true,failedJobs:[],failedProfiles:[]};
 }
 assert.ok(failedJobs.length+failedProfiles.length,'No recorded bounded failure; pending triggers alone cannot freeze');
 return {policy,status:'FAILED_CLOSED_BOUNDED',complete:false,failedJobs:failedJobs.map(j=>({id:j.id,status:j.status,code:j.stages.failure.code,error:j.error})),failedProfiles:failedProfiles.map(c=>({scope:c.scope,layer:c.layer,sessionId:c.sessionId,code:c.error.code,error:c.error.message,blockedDispatch:c.blockedDispatch??null})),foregroundMayUseExistingAssets:true,learningFailureIsNotAnswerScore:true,nativeTerminalJournalsVerified:true,actualLearningRequests:requests.length};
}

/** Preserve every native background run, including a quota denial before its first dispatch. */
export async function collectPersonaNativeRuns(ctx,rsi){
 const directory=join(rsi.runtime.directory,'learning-runs'),items=[];
 for(const filename of (await readdir(directory)).filter(name=>/^rsi-.+\.json$/.test(name)).sort()){
  const record=JSON.parse(await readFile(join(directory,filename),'utf8'));
  const handle=await ctx.sessionPersistence.open(record.sessionId,'read');
  try{const stored=await handle.read();items.push({record,header:handle.header,inheritedEventCount:handle.inheritedEventCount,events:stored.events,eventsSha256:digest(stored.events)});}finally{await handle.close();}
 }
 return items;
}
