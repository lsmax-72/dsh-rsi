import assert from 'node:assert/strict';
import fs from 'node:fs';
import {Session} from '@deepseek-ai/dsh-session';
export const name='recover-native-profiles';export const inject=['rsi','llm','sessionPersistence'];
export function apply(ctx,config){
 const dir='/state/pilot/'+config.instanceId;fs.mkdirSync(dir,{recursive:true});const requests=[];let last=Date.now();
 const save=(name,value)=>fs.writeFileSync(dir+'/'+name,JSON.stringify(value,null,2));
 ctx.on('llm/stream',async function*(options,next){
  assert.ok(options.sessionId.startsWith('rsi-'),'Profile recovery must not dispatch task solvers');assert.ok(requests.length<config.learningDispatchLimit,'Fixed profile recovery cap');
  const handle=await ctx.sessionPersistence.open(options.sessionId,'read');const stored=await handle.read();assert.deepEqual([...Session.fromRestore(options.sessionId,stored.events,handle.header,handle.inheritedEventCount,stored.eventState).deriveMessages()],options.messages);await handle.close();
  const row={sessionId:options.sessionId,phase:'learning',messages:structuredClone(options.messages),inputReconstructed:true,usage:null,status:'DISPATCHING'};requests.push(row);last=Date.now();save('model-requests.json',requests);
  try{for await(const chunk of next()){if(chunk.type==='usage'){row.usage=chunk.usage;save('model-requests.json',requests);}yield chunk;}row.status='RETURNED';}catch(error){row.status='ERROR';row.error=error.message;throw error;}finally{last=Date.now();save('model-requests.json',requests);}
 });
 ctx.effect(()=>{const alive=setInterval(()=>{},1000),wall=setTimeout(()=>ctx.rsi.runtime.abort.abort(new Error('Profile recovery wall cap')),config.wallTimeMs),timer=setTimeout(async()=>{let receipt;try{
  await ctx.rsi.ready;const until=Date.now()+config.wallTimeMs;let settled=false,budgetExhausted=false;
  while(Date.now()<until){const snapshot=await ctx.rsi.request('snapshot',{cwd:'/workspace'});save('scheduler.json',snapshot);
   if(snapshot.nativeProfiles.every(p=>!p.trigger.should)&&snapshot.nativePipelines.length&&snapshot.nativePipelines.every(p=>p.queues.l1Idle&&p.queues.l2Idle&&p.queues.l3Idle&&p.sessions.every(s=>s.conversation_count===0&&s.l2_pending_l1_count===0))&&ctx.rsi.runtime.active.size===0&&Date.now()-last>=config.settleMs){settled=true;break;}
   // Once the fixed budget is spent, waiting cannot complete a failed native refresh.
   if(requests.length>=config.learningDispatchLimit&&ctx.rsi.runtime.active.size===0&&snapshot.nativePipelines.every(p=>p.queues.l1Idle&&p.queues.l2Idle&&p.queues.l3Idle)&&Date.now()-last>=config.settleMs){budgetExhausted=true;break;}
   await new Promise(resolve=>setTimeout(resolve,1000));
  }
  await ctx.rsi.request('settings',{cwd:'/workspace',settings:{learningEnabled:false}});const snapshot=await ctx.rsi.request('snapshot',{cwd:'/workspace'});save('learning.json',{settled,snapshot});save('assets.json',await ctx.rsi.request('export',{cwd:'/workspace'}));
  receipt={status:settled?'NATIVE_CHECKPOINT_RECOVERY_COMPLETED':'INCOMPLETE',budgetExhausted,foregroundRequests:0,learningRequests:requests.length,knownTokens:requests.reduce((n,r)=>n+(r.usage?.totalTokens??0),0),unknownActualUsage:requests.filter(r=>!r.usage).length,nativePipelines:snapshot.nativePipelines,originalFiveJobs:snapshot.jobs.map(j=>({id:j.id,status:j.status})),originalQuestionsNotReanswered:true,scorerRead:false,fixture:!!config.fixture};
 }catch(error){receipt={status:'ERROR',error:error.message,foregroundRequests:0,learningRequests:requests.length,knownTokens:requests.reduce((n,r)=>n+(r.usage?.totalTokens??0),0)};}finally{clearTimeout(wall);await ctx.root.fiber.dispose();save('receipt.json',receipt);console.log(JSON.stringify(receipt));process.exit(0);}},50);return()=>{clearInterval(alive);clearTimeout(wall);clearTimeout(timer);};});
}
