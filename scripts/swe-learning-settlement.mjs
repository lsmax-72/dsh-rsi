// Runner-only observation: never trigger or change the native learning pipeline.
export function settlementReasons(snapshot, work, sessionId, turn, endSeq, captureExpected=true) {
  const reasons=[];
  const job=snapshot.jobs.find(j=>j.session===sessionId && j.turn===turn);
  if(captureExpected && !job)reasons.push('task-not-captured');
  else if(job && job.status!=='completed')reasons.push('job-'+job.status);
  if(captureExpected && (work.sourceCursor??-1)<endSeq)reasons.push('capture-cursor-behind');
  if(work.activeCalls)reasons.push('active-native-work');
  if(snapshot.profilePending)reasons.push('profile-pending');
  for(const pipeline of work.pipelines){
    const q=pipeline.queues;
    if(['l1','l2','l3'].some(k=>q[k]!==0 || q[k+'Pending'] || q[k+'Idle']!==true))reasons.push('native-queue-active');
    for(const s of pipeline.sessions)if(s.bufferedMessages || s.conversation_count || s.l2_pending_l1_count)reasons.push('native-timer-or-buffer-pending');
  }
  if(snapshot.jobs.some(j=>j.status!=='completed'))reasons.push('prior-learning-not-complete');
  if(snapshot.nativeProfileCalls.some(c=>c.status==='running'))reasons.push('native-profile-running');
  return [...new Set(reasons)];
}

export async function waitForLearning({rsi,snapshot,sessionId,turn,endSeq,captureExpected=true,maxWaitMs,persist,now=Date.now,sleep=ms=>new Promise(r=>setTimeout(r,ms))}) {
  const start=now(),deadline=start+maxWaitMs;
  if(!rsi || maxWaitMs===0)return {status:'SKIPPED',waitMs:0};
  for(;;){
    // A turn/end observer publishes asynchronously; queue emptiness before
    // this barrier must never be interpreted as a completed learning task.
    await rsi.runtime.captureQueue;
    const state=await snapshot();
    const work={sourceCursor:rsi.runtime.state.sources().find(s=>s.id===sessionId)?.cursor,activeCalls:rsi.runtime.active.size,
      pipelines:[...rsi.runtime.pipelines.values()].map(p=>({queues:p.getQueueSizes(),sessions:p.getSessionKeys().map(k=>({...p.getSessionState(k),bufferedMessages:p.getBufferedMessageCount(k)}))}))};
    const reasons=settlementReasons(state,work,sessionId,turn,endSeq,captureExpected);
    const result={status:reasons.length?'WAITING':'COMPLETED',waitMs:now()-start,sessionId,turn,endSeq,captureExpected,reasons,work};
    persist(state,result);
    if(!reasons.length)return result;
    if(now()>=deadline)return {...result,status:'DEADLINE_CHECKPOINT'};
    await sleep(Math.min(1000,deadline-now()));
  }
}
