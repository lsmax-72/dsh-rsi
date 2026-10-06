import {NATIVE_LEARNING_POLICY,decideClosedNativeLearning} from './personamem-native-learning-policy.mjs';
export {NATIVE_LEARNING_POLICY};
import assert from 'node:assert/strict';
export const STRICT_LEARNING_POLICY='require-complete';
export const PARTIAL_LEARNING_POLICY='evaluate-closed-bounded-failure';
/** Foreground answers remain measurable after a closed learner timeout; unhealthy capture stays fatal. */
export function decideLegacyPersonaLearning({policy=STRICT_LEARNING_POLICY,settled,snapshot,activeCount,expectedL0,requests=[],blocked=[]}){
 assert.ok([STRICT_LEARNING_POLICY,PARTIAL_LEARNING_POLICY].includes(policy),'Unknown frozen learning failure policy');
 assert.equal(snapshot.layers[snapshot.workspace.id].L0,expectedL0,'Incomplete native history capture');
 if(settled){
  assert.equal(activeCount,0,'Settled learning must have no active calls');
  assert.ok(snapshot.jobs.length&&snapshot.jobs.every(j=>j.status==='completed'),'Settled learning has unfinished jobs');
  assert.ok(snapshot.nativePipelines.length&&snapshot.nativePipelines.every(p=>p.queues.l1Idle&&p.queues.l2Idle&&p.queues.l3Idle),'Settled learning queues are not idle');
  assert.ok(snapshot.nativeProfiles.every(p=>!p.trigger.should),'Settled learning has pending profile work');
  return {policy,status:'COMPLETED',complete:true,failedJobs:[]};
 }
 assert.equal(policy,PARTIAL_LEARNING_POLICY,'Native history learning did not finish within the predeclared window; do not score this as a task failure or expand it silently');
 assert.equal(activeCount,0,'Learning is still active; cannot freeze partial assets');
 assert.ok(snapshot.nativePipelines.length&&snapshot.nativePipelines.every(p=>p.queues.l1Idle&&p.queues.l2Idle&&p.queues.l3Idle&&!p.queues.l1Pending&&!p.queues.l2Pending&&!p.queues.l3Pending),'Native learning queues are not quiescent');
 assert.ok(requests.length&&requests.every(r=>['RETURNED','ERROR','INCOMPLETE'].includes(r.status)),'No terminal actual learning ledger');
 const failed=snapshot.jobs.filter(j=>j.status!=='completed');
 assert.ok(failed.length,'Partial policy requires a recorded failed/paused job');
 assert.ok(failed.every(j=>['failed','paused'].includes(j.status)&&['ABORTED','BUDGET_EXHAUSTED'].includes(j.stages?.failure?.code)),'Unclassified, infrastructure or non-budget learning failure remains fatal');
 if(failed.some(j=>j.stages.failure.code==='BUDGET_EXHAUSTED'))assert.ok(blocked.some(b=>b.reason==='EXPERIMENT_CALL_CAP'),'Budget stop needs its actual blocked-dispatch receipt');
 return {policy,status:'FAILED_CLOSED_BOUNDED',complete:false,failedJobs:failed.map(j=>({id:j.id,status:j.status,code:j.stages.failure.code,error:j.error})),foregroundMayUseExistingAssets:true,learningFailureIsNotAnswerScore:true};
}

export function decidePersonaLearning(input){return input.policy===NATIVE_LEARNING_POLICY?decideClosedNativeLearning(input):decideLegacyPersonaLearning(input);}
