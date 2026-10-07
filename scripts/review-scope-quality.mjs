// Synthetic diagnostic. Production import, Runtime.process, native assets and consumers remain in use.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {mkdirSync,writeFileSync,renameSync} from 'node:fs';
import {join} from 'node:path';
import {createUserMessage,LlmAdapter} from '@deepseek-ai/dsh-llm';
import {Session} from '@deepseek-ai/dsh-session';
import {appendPersonaHistory,personaHistoryContext} from './personamem-history.mjs';
export const name='review-scope-quality';
export const inject=['rsi','llm','agents','sessions','sessionPersistence','tools','skills'];
export function apply(ctx,config){
 const dir='/state/pilot/'+config.instanceId;mkdirSync(dir,{recursive:true});
 const requests=[],stages=[],sources=[],toolResults=[],blocked=[];let phase='setup',back=0,front=0,input,rt,scope;
 const save=(name,value)=>{const p=join(dir,name);writeFileSync(p+'.tmp',JSON.stringify(value,null,2)+'\n');renameSync(p+'.tmp',p);};
 const known=row=>Number.isFinite(row.usage?.totalTokens)&&row.usage.totalTokens>0;
 const exportAll=async()=>({workspace:await rt.request('export',{cwd:'/workspace'}),global:await rt.request('export',{cwd:'/workspace',scope:'global'})});
 const assetState=all=>Object.fromEntries(Object.entries(all).map(([key,value])=>[key,{memory:value.memory,memoryHistory:value.memoryHistory,skills:value.skills,profileFiles:value.profileFiles}]));
 const taskFor=async id=>id.startsWith('rsi-')?JSON.parse(await readFile(join(rt.directory,'learning-runs',id+'.json'),'utf8')):{taskId:'consumer'};
 ctx.on('llm/stream',async function*(options,next){
  const background=options.sessionId.startsWith('rsi-');
  if(background?back>=config.learningDispatchLimit:front>=config.dispatchLimit){blocked.push({sessionId:options.sessionId,phase,reason:'FIXED_CALL_CAP'});save('blocked-dispatches.json',blocked);throw Object.assign(new Error('Fixed scope quality request cap'),{code:'BUDGET_EXHAUSTED'});}
  assert.equal(options.provider,config.fixture?'pilot-fixture':'qwen');assert.equal(options.model,config.fixture?'fixture':'qwen3.8-27b');
  assert.ok(!(options.tools??[]).some(t=>['bash','run_code','shell','write_file'].includes(t.name)),'Task execution tools must be absent');
  const session=ctx.sessions.get(options.sessionId);if(session)await ctx.sessions.flush(session);
  const h=await ctx.sessionPersistence.open(options.sessionId,'read'),stored=await h.read();
  const restored=Session.fromRestore(options.sessionId,stored.events,h.header,h.inheritedEventCount,stored.eventState);await h.close();
  assert.deepEqual([...restored.deriveMessages()],options.messages,'Actual input differs from native durable prefix');
  const task=await taskFor(options.sessionId);
  const row={sessionId:options.sessionId,phase,background,taskId:task.taskId,scope:task.scope,messages:structuredClone(options.messages),tools:structuredClone(options.tools??[]),prefixEndSeq:stored.events.at(-1)?.seq,inputReconstructed:true,usage:null,responseBlocks:{},status:'DISPATCHING',observedAt:Date.now()};
  background?back++:front++;requests.push(row);save('model-requests.json',requests);
  try{for await(const chunk of next()){
   if(chunk.type==='usage')row.usage=chunk.usage;
   if(chunk.type==='text-delta')row.responseBlocks[chunk.index]=(row.responseBlocks[chunk.index]??'')+chunk.text;
   if(chunk.type==='block-end'){row.blocks??=[];row.blocks.push(structuredClone(chunk.block));if(chunk.block.type==='text')row.responseBlocks[chunk.index]=chunk.block.text;}
   if(chunk.type==='finish')row.finish=structuredClone(chunk.reason);yield chunk;
  }row.status=['stop','tool-calls'].includes(row.finish?.kind)?'RETURNED':'INCOMPLETE';}
  catch(error){row.status='ERROR';row.error=error.message;throw error;}
  finally{row.finishedAt=Date.now();save('model-requests.json',requests);}
 });
 ctx.on('tools/result',(execution,result)=>{toolResults.push({name:execution.name,callId:execution.callId,args:execution.arguments,isError:result.isError===true,phase});save('tool-results.json',toolResults);});
 if(config.fixture){
  class Fixture extends LlmAdapter{
   async *stream(options){
    const task=await taskFor(options.sessionId),prompt=options.messages.flatMap(m=>m.content).map(b=>b.text??'').join('\n');
    let block={type:'text',text:'Nothing to save.'};
    if(task.taskId==='l1-extraction'){
     const id=prompt.match(/\[([^\]]+)\] \[user\]/)?.[1];assert.ok(id);
     block.text=JSON.stringify([{scene_name:'电影海报收藏',message_ids:[id],memories:[{content:(phase==='before'?input.historyBefore:input.historyAfter).find(m=>m.role==='user').content,type:phase==='before'?'persona':'episodic',priority:80,source_message_ids:[id],metadata:{fixture:true}}]}]);
    }else if(task.taskId==='l1-conflict-detection'){
     const id=prompt.match(/record_id: ([^)]+)\)/)?.[1],old=(await (await rt.core('global')).readMemories())[0];assert.ok(id&&old);
     block.text=JSON.stringify([{record_id:id,action:'merge',target_ids:[old.id],merged_content:input.historyBefore.find(m=>m.role==='user').content+' '+input.historyAfter.find(m=>m.role==='user').content,merged_type:'persona',merged_priority:80}]);
    }else if(task.taskId.startsWith('scene-extract-')||task.taskId==='persona-generation'){
     const n=requests.filter(r=>r.sessionId===options.sessionId).length;
     const text=(phase==='before-profile'?input.historyBefore:input.historyAfter).find(m=>m.role==='user').content;
     block=n===1?{type:'tool-call',id:'fixture-profile-'+requests.length,name:'write',arguments:JSON.stringify({path:task.taskId==='persona-generation'?'persona.md':'电影海报收藏.md',content:task.taskId==='persona-generation'?'# 夹具画像\n'+text:'-----META-START-----\ncreated: 2026-10-07T00:00:00Z\nupdated: 2026-10-07T00:00:00Z\nsummary: 电影海报偏好\nheat: 1\n-----META-END-----\n\n'+text})}:{type:'text',text:'Saved.'};
    }else if(task.taskId==='consumer')block.text='夹具消费完成。'+input.historyAfter.find(m=>m.role==='user').content;
    yield {type:'block-start',index:0,blockType:block.type};yield {type:'block-end',index:0,block};yield {type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};yield {type:'finish',reason:{kind:block.type==='tool-call'?'tool-calls':'stop'}};
   }
  }
  ctx.effect(()=>ctx.llm.registerAdapter(['pilot-fixture'],new Fixture()));
 }
 ctx.effect(()=>{
  const alive=setInterval(()=>{},1000);let consumer,receipt;
  const wall=setTimeout(()=>{ctx.rsi.runtime.abort.abort(new Error('Fixed diagnostic wall expired'));consumer?.agent.cancel({kind:'hook',reason:'Scope diagnostic wall limit'});},config.wallTimeMs);
  const timer=setTimeout(async()=>{
   try{
    await ctx.rsi.ready;rt=ctx.rsi.runtime;input=JSON.parse(await readFile('/opt/rsi/scripts/scope-quality.json','utf8'));assert.equal(input.id,config.instanceId);
    scope=await rt.scope('/workspace');const core=await rt.core(scope.id),global=await rt.core('global');
    assert.equal((await core.readMemories()).length+(await global.readMemories()).length,0);
    // Explicit ticks control stage order; native observe performs normal capture and queue creation.
    rt.state.configure({learningEnabled:false});
    const originalObserve=rt.observe.bind(rt);rt.observe=(session,event)=>{if(!session.id.startsWith('scope-consumer-'))originalObserve(session,event);};
    const agentOptions={provider:config.fixture?'pilot-fixture':'qwen',model:config.fixture?'fixture':'qwen3.8-27b',maxTokens:4096};
    for(const [label,history] of [['before',input.historyBefore],['after',input.historyAfter]]){
     phase=label;const seed=ctx.sessions.prepare('scope-'+input.id+'-'+label,{meta:{cwd:'/workspace'}}),imported=await appendPersonaHistory(seed,history,{sourceLabel:'synthetic-scope-quality-v1'});
     const handle=await ctx.agents.create({sessionId:seed.id,meta:{cwd:'/workspace'},seed:imported.events,agentOptions});await ctx.sessions.flush(handle.agent.session);
     assert.deepEqual([...handle.agent.session.deriveMessages()].map(m=>({role:m.role,content:m.content.map(b=>b.text).join('')})),history);
     rt.observe(handle.agent.session,imported.events.at(-1));await rt.captureQueue;
     const jobs=rt.state.jobs(scope.id).filter(j=>j.session===seed.id);assert.equal(jobs.length,1);assert.equal(jobs[0].stages.failure?.attempts??0,0);
     sources.push({sessionId:seed.id,label,history,events:imported.events,messageIds:imported.messageIds});save('sources.json',sources);
     rt.state.configure({learningEnabled:true});
     try{await rt.within(scope.id,()=>rt.process(scope.id,seed.id),{sessionId:seed.id,route:agentOptions});}finally{rt.state.configure({learningEnabled:false});}
     assert.equal(rt.state.jobs(scope.id).find(j=>j.id===jobs[0].id).status,'completed');
     stages.push({phase:label,memory:await core.readMemories(),globalMemory:await global.readMemories(),snapshot:await rt.snapshot('/workspace')});save('stages.json',stages);
     phase=label+'-profile';
     for(const selected of label==='before'?['global']:[scope.id,'global'])await rt.request('rebuildProfile',{cwd:'/workspace',scope:selected});
     save(label+'-assets.json',await exportAll());
    }
    const frozen=await exportAll(),beforeJobs=rt.state.jobs().map(j=>j.id).sort();save('frozen-assets.json',frozen);
    const history=[...input.historyBefore,...input.historyAfter],seed=ctx.sessions.prepare('scope-consumer-'+input.id,{meta:{cwd:'/workspace'}}),imported=await appendPersonaHistory(seed,history,{sourceLabel:'synthetic-scope-quality-v1'});
    consumer=await ctx.agents.create({sessionId:seed.id,meta:{cwd:'/workspace'},seed:imported.events,agentOptions});
    phase='consumer';consumer.agent.inject(createUserMessage({source:{kind:'synthetic-history-context',form:'instructions'},content:[{type:'text',text:personaHistoryContext(history)}]}));
    consumer.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:input.question}]}));await consumer.agent.whenIdle();await ctx.sessions.flush(consumer.agent.session);
    const last=requests.filter(r=>!r.background).at(-1);assert.ok(last);
    const visible=last.messages.flatMap(m=>m.content).filter(b=>b.type==='text').map(b=>b.text).join('\n');
    for(const message of history)assert.ok(visible.includes(message.content),'Source prose missing in actual consumer request');
    const finalHandle=await ctx.sessionPersistence.open(consumer.agent.session.id,'read'),finalLog=await finalHandle.read();await finalHandle.close();
    const reason=finalLog.events.filter(e=>e.type==='turn/end').at(-1)?.data.reason;assert.equal(reason?.kind,'completed','Consumer did not finish normally');
    const response=Object.entries(last.responseBlocks).sort(([a],[b])=>Number(a)-Number(b)).map(([,v])=>v).join('\n');
    const latest=[...consumer.agent.session.deriveMessages()].filter(m=>m.role==='assistant'&&!imported.messageIds.includes(m.id)).at(-1);assert.ok(latest);assert.equal(response,latest.content.filter(b=>b.type==='text').map(b=>b.text).join('\n'));
    save('answer.json',{response,reason,fullHistoryRetained:true});
    assert.deepEqual(rt.state.jobs().map(j=>j.id).sort(),beforeJobs,'Consumer was learned');assert.deepEqual(assetState(await exportAll()),assetState(frozen),'Consumer changed asset content or versions');
    save('consumer-isolation.json',{noLearning:true,assetContentVersionsUnchanged:true});
    receipt={status:'COMPLETED_REQUIRES_CONTENT_REVIEW',fixture:!!config.fixture,caseId:input.id,fullHistoryRetained:true,questionLearned:false,independentEffectClaim:false,taskCommands:0};
   }catch(error){receipt={status:'ERROR',fixture:!!config.fixture,caseId:config.instanceId,phase,error:error.message,code:error.code??'DIAGNOSTIC_ERROR',classification:'TECHNICAL_OR_BUDGET_FAILURE_NOT_ANSWER_SCORE'};}
   finally{
    clearTimeout(wall);
    if(rt){rt.state.configure({learningEnabled:false});try{save('final-assets.json',await exportAll());save('snapshot.json',await rt.snapshot('/workspace'));}catch(error){receipt.exportError=error.message;}}
    for(const id of new Set([...sources.map(s=>s.sessionId),...requests.map(r=>r.sessionId),...(consumer?[consumer.agent.session.id]:[])]))try{const h=await ctx.sessionPersistence.open(id,'read'),s=await h.read();await h.close();save(id+'.events.json',s.events);}catch(error){receipt.logExportError=error.message;}
    await ctx.root.fiber.dispose();clearInterval(alive);save('model-requests.json',requests);save('stages.json',stages);
    receipt={...receipt,backgroundCalls:back,consumerCalls:front,actualRequests:requests.length,knownTokens:requests.reduce((n,r)=>n+(known(r)?r.usage.totalTokens:0),0),unknownActualUsage:requests.filter(r=>!known(r)).length,embeddingTokenUsage:null,allInputsReconstructed:requests.every(r=>r.inputReconstructed),triggerMode:'Explicit production queue processing and manual native profile rebuild; automatic timing not tested.'};
    save('receipt.json',receipt);console.log(JSON.stringify(receipt));process.exit(receipt.status==='ERROR'?1:0);
   }
  },0);return()=>{clearInterval(alive);clearTimeout(wall);clearTimeout(timer);};
 });
}
