import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {mkdirSync,writeFileSync,renameSync,openSync,fsyncSync,closeSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {createUserMessage,LlmAdapter} from '@deepseek-ai/dsh-llm';
import {Session} from '@deepseek-ai/dsh-session';
import {appendPersonaHistory,personaHistoryContext,importedHistoryTimeNote} from './personamem-history.mjs';
import {decidePersonaLearning,STRICT_LEARNING_POLICY,NATIVE_LEARNING_POLICY} from './personamem-learning-policy.mjs';
import {collectPersonaNativeRuns} from './personamem-native-learning-policy.mjs';
export const hasKnownPersonaUsage=row=>Number.isFinite(row.usage?.totalTokens)&&row.usage.totalTokens>0;
export const name='personamem-pilot-task';
export const inject=['llm','agents','sessions','sessionPersistence','tools','skills'];

// Experimental driver only. Native import, learning, recall and Skill tools stay in their normal paths.
export function apply(ctx,config){
  const dir='/state/pilot/'+config.instanceId;mkdirSync(dir,{recursive:true});
  const requests=[],checks=[],answers=[],tools=[],blocked=[];let phase='setup',front=0,back=0,questionCalls=0,lastLearningActivity=Date.now(),rsi,learningDisposition;
  const durable=(name,value)=>{const path=dir+'/'+name,tmp=path+'.tmp';writeFileSync(tmp,JSON.stringify(value,null,2));const fd=openSync(tmp,'r');try{fsyncSync(fd);}finally{closeSync(fd);}renameSync(tmp,path);};
  const save=()=>durable('model-requests.json',requests);
  ctx.on('llm/stream',async function*(options,next){
    const background=options.sessionId.startsWith('rsi-');
    if(background?back>=config.learningDispatchLimit:questionCalls>=config.dispatchLimit){blocked.push({sessionId:options.sessionId,reason:'EXPERIMENT_CALL_CAP',phase,time:Date.now()});durable('blocked-dispatches.json',blocked);throw Object.assign(new Error('Persona pilot dispatch cap'),{code:'BUDGET_EXHAUSTED'});}
    if(background){assert.equal(phase,'learning','Question answers must never become learning input');back++;lastLearningActivity=Date.now();}else{front++;questionCalls++;}
    const session=ctx.sessions.get(options.sessionId);if(session)await ctx.sessions.flush(session);
    const handle=await ctx.sessionPersistence.open(options.sessionId,'read');const stored=await handle.read();
    const restored=Session.fromRestore(options.sessionId,stored.events,handle.header,handle.inheritedEventCount,stored.eventState);await handle.close();
    assert.deepEqual([...restored.deriveMessages()],options.messages,'Dispatch is not reconstructable from the durable native log');
    checks.push({sessionId:options.sessionId,prefixEndSeq:stored.events.at(-1)?.seq,matches:true});durable('reconstruction.json',checks);
    const row={sessionId:options.sessionId,phase:background?'learning':phase,messages:structuredClone(options.messages),usage:null,responseBlocks:{},status:'DISPATCHING',observedAt:Date.now(),prefixEndSeq:stored.events.at(-1)?.seq};requests.push(row);save();
    try{for await(const chunk of next()){if(chunk.type==='usage'){row.usage=chunk.usage;save();}if(chunk.type==='text-delta')row.responseBlocks[chunk.index]=(row.responseBlocks[chunk.index]??'')+chunk.text;if(chunk.type==='block-end'&&chunk.block.type==='text')row.responseBlocks[chunk.index]=chunk.block.text;if(chunk.type==='finish')row.finish=structuredClone(chunk.reason);yield chunk;}row.status=['stop','tool-calls'].includes(row.finish?.kind)?'RETURNED':'INCOMPLETE';}catch(error){row.status='ERROR';row.error=error.message;throw error;}finally{if(row.status==='DISPATCHING')row.status=['stop','tool-calls'].includes(row.finish?.kind)?'RETURNED':'INCOMPLETE';row.finishedAt=Date.now();if(background)lastLearningActivity=Date.now();save();}
  });
  ctx.on('tools/result',(execution,result)=>{tools.push({name:execution.name,callId:execution.callId,args:execution.arguments,isError:result.isError===true,phase,requestOrdinal:front});durable('tool-results.json',tools);});
  if(config.fixture){
    let fixtureSkillCalls=0;
    class Fixture extends LlmAdapter{
      async *stream(options){
        const background=options.sessionId.startsWith('rsi-'),system=options.messages.filter(m=>m.role==='system').flatMap(m=>m.content).map(b=>b.text??'').join('\n');
        const skillReview=system.includes('Skill Review Agent');let block={type:'text',text:background?(skillReview?'Nothing to save.':'[]'):'<final_answer>(a)</final_answer>'};
        if(background&&(config.fixtureClosedLearningFailure||config.fixtureClosedProfileFailure)){
          if(skillReview){
            fixtureSkillCalls++;
            if(fixtureSkillCalls>1&&config.fixtureClosedLearningFailure){yield{type:'finish',reason:{kind:'error',failure:{code:'ABORTED',message:'FIXTURE closed Skill review abort after native asset write'}}};return;}
            block=fixtureSkillCalls>1?{type:'text',text:'Saved.'}:{type:'tool-call',id:'fixture-pre-abort-skill',name:'skill_create',arguments:JSON.stringify({name:'fixture-log-preservation',content:'---\nname: fixture-log-preservation\ndescription: Explicit fixture, no real successful experience\n---\n\n# 测试记录\n保留完整失败日志。以下仅为隔离夹具，不是真实成功经验。'})};
          }else{
            const prompt=options.messages.filter(m=>m.role==='user').flatMap(m=>m.content).map(b=>b.text??'').join('\n'),id=prompt.match(/\[([^\]]+)\] \[user\]/)?.[1];assert.ok(id);
            block={type:'text',text:JSON.stringify([{scene_name:'隔离测试记录',message_ids:[id],memories:[{content:'保留完整失败日志。显式隔离夹具。',type:'instruction',priority:70,source_message_ids:[id],metadata:{fixture:true}}]}])};
          }
        }
        yield{type:'block-start',index:0,blockType:block.type};
        if(!background&&config.fixtureAnswerStop==='error-after-text'){yield{type:'text-delta',index:0,text:block.text};throw new Error('FIXTURE interrupted after partial output');}
        yield{type:'block-end',index:0,block};yield{type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};
        yield{type:'finish',reason:{kind:background?(block.type==='tool-call'?'tool-calls':'stop'):(config.fixtureAnswerStop??'stop')}};
      }
    }
    ctx.effect(()=>ctx.llm.registerAdapter(['pilot-fixture'],new Fixture()));
  }
  ctx.effect(()=>{const alive=setInterval(()=>{},1000);const timer=setTimeout(async()=>{let deadline;let receipt;
    try{
      const input=JSON.parse(await readFile('/opt/rsi/personamem.json','utf8'));assert.equal(input.questions.length,config.expectedQuestionCount??2);assert.ok(!Object.hasOwn(input,'correct_answer'));rsi=ctx.get('rsi');assert.equal(!!rsi,config.arm==='rsi');if(rsi)await rsi.ready;
      // Benchmark answers and their replayed seed turns must never be queued for later learning.
      if(rsi){const observe=rsi.runtime.observe.bind(rsi.runtime),prefix='persona-'+input.personaId+'-question-';rsi.runtime.observe=(session,event)=>{if(!session.id.startsWith(prefix))observe(session,event);};}
      const seed=ctx.sessions.prepare('persona-'+input.personaId+'-history',{meta:{cwd:'/workspace'}});const imported=await appendPersonaHistory(seed,input.history,{systemBoundaries:true});
      const agentOptions={provider:config.fixture?'pilot-fixture':'qwen',model:config.fixture?'fixture':'qwen3.8-27b',maxTokens:4096};
      const history=await ctx.agents.create({sessionId:seed.id,meta:{cwd:'/workspace'},seed:imported.events,agentOptions});await ctx.sessions.flush(history.agent.session);
      const importedRoles=[...history.agent.session.deriveMessages()].map(m=>({role:m.role,content:m.content.map(b=>b.text).join('')}));assert.deepEqual(importedRoles,input.history);
      durable('import.json',{personaId:input.personaId,contextId:input.contextId,cutoff:input.historyCutoffExclusive,messages:input.history.length,historySha256:createHash('sha256').update(JSON.stringify(input.history)).digest('hex'),nativeHistoryExact:true,turnBoundaries:imported.turnBoundaries});
      if(rsi){
        phase='learning';lastLearningActivity=Date.now();const until=Date.now()+config.settleMs;
        rsi.runtime.observe(history.agent.session,imported.events.at(-1));
        // Capture is the native log recovery entry. L0 indexing can consume much of this bounded window.
        await rsi.runtime.captureQueue;
        let settled=false;
        while(Date.now()<until){const snapshot=await rsi.request('snapshot',{cwd:'/workspace'});durable('scheduler.json',snapshot);
          if((config.learningFailurePolicy!==NATIVE_LEARNING_POLICY||!snapshot.profilePending)&&snapshot.jobs.length&&snapshot.jobs.every(j=>j.status==='completed')&&snapshot.nativeProfiles.every(p=>!p.trigger.should)&&snapshot.nativePipelines.length&&snapshot.nativePipelines.every(p=>p.queues.l1Idle&&p.queues.l2Idle&&p.queues.l3Idle&&p.sessions.every(s=>s.conversation_count===0&&s.l2_pending_l1_count===0))&&rsi.runtime.active.size===0&&Date.now()-lastLearningActivity>=(config.fixture?1000:45000)){settled=true;break;}
          if(snapshot.jobs.some(j=>['failed','paused','interrupted'].includes(j.status))&&rsi.runtime.active.size===0)break;
          if(config.learningFailurePolicy===NATIVE_LEARNING_POLICY&&snapshot.nativeProfileCalls.some(c=>c.status==='failed')&&snapshot.jobs.every(j=>['completed','failed','paused'].includes(j.status))&&rsi.runtime.active.size===0&&snapshot.nativePipelines.every(p=>p.queues.l1Idle&&p.queues.l2Idle&&p.queues.l3Idle&&!p.queues.l1Pending&&!p.queues.l2Pending&&!p.queues.l3Pending))break;
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
        await rsi.request('settings',{cwd:'/workspace',settings:{learningEnabled:false}});const snapshot=await rsi.request('snapshot',{cwd:'/workspace'});durable('learning.json',{settled,snapshot});durable('assets.json',await rsi.request('export',{cwd:'/workspace'}));
        let nativeRuns,nativeEvidenceSha256;
        if(config.learningFailurePolicy===NATIVE_LEARNING_POLICY){nativeRuns=await collectPersonaNativeRuns(ctx,rsi);durable('native-learning-runs.json',nativeRuns);nativeEvidenceSha256=createHash('sha256').update(await readFile(dir+'/native-learning-runs.json')).digest('hex');}
        const learningInput={policy:config.learningFailurePolicy??STRICT_LEARNING_POLICY,settled,snapshot,activeCount:rsi.runtime.active.size,expectedL0:input.history.filter(m=>m.role!=='system').length,requests:requests.filter(r=>r.phase==='learning'),blocked,callLimit:config.learningDispatchLimit,nativeRuns};
        // Retain the attempted gate input even if it rejects; never manufacture a failed job.
        durable('learning.json',{settled,snapshot,activeCount:learningInput.activeCount,expectedL0:learningInput.expectedL0,callLimit:learningInput.callLimit,nativeEvidenceSha256});
        learningDisposition=decidePersonaLearning(learningInput);
        durable('learning.json',{settled,snapshot,activeCount:learningInput.activeCount,expectedL0:learningInput.expectedL0,callLimit:learningInput.callLimit,nativeEvidenceSha256,disposition:learningDisposition});
      }
      const assetState=value=>({memory:value.memory,memoryHistory:value.memoryHistory,skills:value.skills,profileFiles:value.profileFiles});let frozenAssets,frozenLearning;if(rsi){frozenAssets=assetState(await rsi.request('export',{cwd:'/workspace'}));const s=await rsi.request('snapshot',{cwd:'/workspace'});frozenLearning={jobs:s.jobs.map(j=>j.id).sort(),sources:[...new Set(s.jobs.map(v=>v.sourceSessionId))].sort(),layers:s.layers};}
      for(const q of input.questions){phase=q.id;questionCalls=0;const id='persona-'+input.personaId+'-question-'+q.id;
        const handle=await ctx.agents.create({sessionId:id,meta:{cwd:'/workspace'},seed:imported.events,agentOptions});
        handle.agent.inject(createUserMessage({source:{kind:'personamem-history',form:'recall',sessionId:seed.id},content:[{type:'text',text:personaHistoryContext(input.history)}]}));
        handle.agent.inject(createUserMessage({source:{kind:'benchmark-protocol',form:'instructions'},content:[{type:'text',text:q.protocol}]}));
        const start=Date.now();deadline=setTimeout(()=>handle.agent.cancel({kind:'hook',reason:'Persona pilot wall time limit'}),config.wallTimeMs);
        handle.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:q.question+'\n\n'+q.options}]}));await handle.agent.whenIdle();await ctx.sessions.flush(handle.agent.session);clearTimeout(deadline);
        const sent=requests.find(r=>r.sessionId===id);assert.ok(sent,'No model dispatch; inspect the saved native turn/end reason for '+id);const visible=sent.messages.flatMap(m=>m.content).filter(b=>b.type==='text').map(b=>b.text).join('\n');assert.ok(input.history.every(m=>visible.includes(m.content)),'Baseline/RSI lost historical text');assert.ok(visible.includes(personaHistoryContext(input.history)),'Common historical time context missing from actual answering request');
        const reader=await ctx.sessionPersistence.open(id,'read');const saved=await reader.read();await reader.close();
        const reason=saved.events.filter(e=>e.type==='turn/end').at(-1)?.data.reason;
        // Native aborted outputs live in assistant/attempt, not deriveMessages(). Preserve the emitted text.
        const last=requests.filter(r=>r.sessionId===id).at(-1);
        const response=Object.entries(last.responseBlocks).sort(([a],[b])=>Number(a)-Number(b)).map(([,text])=>text).join('\n');
        if(reason?.kind==='completed'){
          const committed=[...handle.agent.session.deriveMessages()].filter(m=>m.role==='assistant'&&!imported.messageIds.includes(m.id)).at(-1);assert.ok(committed);
          assert.equal(response,committed.content.filter(b=>b.type==='text').map(b=>b.text).join('\n'),'Saved output differs from the native committed response');
        }
        answers.push({questionId:q.id,personaId:input.personaId,sessionId:id,response,responseOrigin:'last native model text blocks, including aborted attempts',answerAvailable:!!response.trim(),stopReason:reason,requests:questionCalls,wallMs:Date.now()-start,allHistoricalTextPresent:true,commonHistoricalTimeNotePresent:visible.includes(importedHistoryTimeNote),historicalContextSha256:createHash('sha256').update(personaHistoryContext(input.history)).digest('hex')});durable('answers.json',answers);
      }
      if(rsi){const s=await rsi.request('snapshot',{cwd:'/workspace'});const after={jobs:s.jobs.map(j=>j.id).sort(),sources:[...new Set(s.jobs.map(v=>v.sourceSessionId))].sort(),layers:s.layers};assert.deepEqual(after,frozenLearning,'Question sessions contaminated the frozen learning snapshot');const afterAssets=assetState(await rsi.request('export',{cwd:'/workspace'}));assert.deepEqual(afterAssets,frozenAssets,'Question sessions changed frozen asset content or versions');durable('question-isolation.json',{matches:true,assetContentAndVersionsMatch:true,before:frozenLearning,after,assetStateSha256:createHash('sha256').update(JSON.stringify(frozenAssets)).digest('hex')});}
      receipt={status:'COMPLETED',developmentPilot:!config.personaFormal,formalPersonaMemEvaluation:!!config.personaFormal,arm:config.arm,fixture:!!config.fixture,personaId:input.personaId,questionIds:input.questions.map(q=>q.id),historyCutoffExclusive:input.historyCutoffExclusive,historySha256:createHash('sha256').update(JSON.stringify(input.history)).digest('hex'),foregroundRequests:front,learningRequests:back,knownTokens:requests.reduce((sum,r)=>sum+(hasKnownPersonaUsage(r)?r.usage.totalTokens:0),0),unknownActualUsage:requests.filter(r=>!hasKnownPersonaUsage(r)).length,answersProvided:false,completeHistoryInBothArms:true,commonHistoricalTimeNote:true,historicalContextSha256:createHash('sha256').update(personaHistoryContext(input.history)).digest('hex'),learningFailurePolicy:config.learningFailurePolicy??STRICT_LEARNING_POLICY,learningDisposition,learningStateSha256:rsi?createHash('sha256').update(await readFile(dir+'/learning.json')).digest('hex'):undefined,roleProjection:'Historical system backgrounds are labelled producer context; not identical to official standalone roles',accuracy:null};
    }catch(error){receipt={status:'ERROR',developmentPilot:!config.personaFormal,formalPersonaMemEvaluation:!!config.personaFormal,fixture:!!config.fixture,classification:'UNCLASSIFIED_NOT_TASK_FAIL',error:error.message,foregroundRequests:front,learningRequests:back,knownTokens:requests.reduce((sum,r)=>sum+(hasKnownPersonaUsage(r)?r.usage.totalTokens:0),0),unknownActualUsage:requests.filter(r=>!hasKnownPersonaUsage(r)).length};}
    finally{clearTimeout(deadline);await ctx.root.fiber.dispose();save();durable('receipt.json',receipt);console.log(JSON.stringify(receipt));process.exit(receipt.status==='COMPLETED'?0:1);}
  },0);return()=>{clearInterval(alive);clearTimeout(timer);};});
}
