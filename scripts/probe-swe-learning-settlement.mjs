import assert from 'node:assert/strict';
import {settlementReasons,waitForLearning} from './swe-learning-settlement.mjs';
const idle={l1:0,l2:0,l3:0,l1Pending:false,l2Pending:false,l3Pending:false,l1Idle:true,l2Idle:true,l3Idle:true};
const complete={jobs:[{session:'task',turn:1,status:'completed'}],profilePending:false,nativeProfileCalls:[]};
const empty={sourceCursor:20,activeCalls:0,pipelines:[{queues:idle,sessions:[{bufferedMessages:0,conversation_count:0,l2_pending_l1_count:0}]}]};
assert.deepEqual(settlementReasons(complete,empty,'task',1,20),[]);
assert.ok(settlementReasons({...complete,jobs:[]},empty,'task',1,20).includes('task-not-captured'));
for(const field of ['bufferedMessages','conversation_count','l2_pending_l1_count']){
 const work=structuredClone(empty);work.pipelines[0].sessions[0][field]=1;
 assert.ok(settlementReasons(complete,work,'task',1,20).includes('native-timer-or-buffer-pending'));
}
for(const q of [{...idle,l1Pending:true},{...idle,l2:1},{...idle,l3Idle:false}])assert.ok(settlementReasons(complete,{...empty,pipelines:[{queues:q,sessions:[]}]},'task',1,20).length);
assert.ok(settlementReasons(complete,{...empty,sourceCursor:19},'task',1,20).length);
assert.ok(settlementReasons(complete,{...empty,activeCalls:1},'task',1,20).length);
assert.ok(settlementReasons({...complete,profilePending:true},empty,'task',1,20).length);
let clock=0,observations=0;
const runtime={captureQueue:Promise.resolve(),state:{sources:()=>[{id:'task',cursor:20}]},active:new Set(),pipelines:new Map()};
const result=await waitForLearning({rsi:{runtime},snapshot:async()=>++observations===1?{...complete,jobs:[]}:complete,sessionId:'task',turn:1,endSeq:20,maxWaitMs:900000,persist:()=>{},now:()=>clock,sleep:async ms=>{clock+=ms;}});
assert.equal(result.status,'COMPLETED');assert.equal(result.waitMs,1000);
clock=0;
const pending=await waitForLearning({rsi:{runtime},snapshot:async()=>({...complete,jobs:[{session:'task',turn:1,status:'paused'}]}),sessionId:'task',turn:1,endSeq:20,maxWaitMs:2500,persist:()=>{},now:()=>clock,sleep:async ms=>{clock+=ms;}});
assert.equal(pending.status,'DEADLINE_CHECKPOINT');assert.equal(pending.waitMs,2500);
assert.equal(complete.jobs[0].status,'completed');
assert.deepEqual(settlementReasons({...complete,jobs:[]},{...empty,sourceCursor:undefined},'task',1,20,false),[]);
assert.ok(settlementReasons({...complete,jobs:[]},{...empty,activeCalls:1},'task',1,20,false).length);
console.log(JSON.stringify({status:'PASS_SETTLEMENT_POLICY',realModelRequests:0,checks:['empty queue before capture rejected','buffered idle L1 and delayed L2 rejected','queued/running native work rejected','cursor behind rejected','safe completion exits before900seconds','deadline preserves paused work without classifying complete','native aborted turn skips new capture but still waits for prior work']}));
