import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {LlmAdapter,createUserMessage} from '@deepseek-ai/dsh-llm';
import {Session} from '@deepseek-ai/dsh-session';
import {appendPersonaHistory} from './personamem-history.mjs';
export const name='personamem-import-probe';
export const inject=['llm','agents','sessions','sessionPersistence','rsi'];
export function apply(ctx,config){
  const calls=[];
  class Fixture extends LlmAdapter{
    async *stream(options){calls.push(options);const system=options.messages.filter(m=>m.role==='system').map(m=>m.content.map(b=>b.text).join('')).join('\n');const text=system.includes('Skill Review Agent')?'Nothing to save.':'[]';yield {type:'block-start',index:0,blockType:'text'};yield {type:'block-end',index:0,block:{type:'text',text}};yield {type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};yield {type:'finish',reason:{kind:'stop'}};}
  }
  ctx.effect(()=>ctx.llm.registerAdapter(['personamem-fixture'],new Fixture()));
  ctx.effect(()=>{const timer=setTimeout(async()=>{try{
    await ctx.rsi.ready;
    const input=JSON.parse(await readFile(config.input,'utf8'));
    const seed=ctx.sessions.prepare('personamem-history-fixture',{meta:{cwd:config.root}});
    const imported=await appendPersonaHistory(seed,input.history,{systemBoundaries:config.systemBoundaries===true});
    const handleAgent=await ctx.agents.create({sessionId:seed.id,meta:{cwd:config.root},seed:imported.events,agentOptions:{provider:'personamem-fixture',model:'fixture'}});
    const session=handleAgent.agent.session;
    assert.equal(createHash('sha256').update(JSON.stringify([...session.deriveMessages()].map(m=>({role:m.role,content:m.content.map(b=>b.text).join('')})))).digest('hex'),createHash('sha256').update(JSON.stringify(input.history)).digest('hex'),'Agent factory lost imported seed');
    await ctx.sessions.flush(session);
    // Seed events are not republished. Import adaptation enters the same persisted-log recovery path.
    ctx.rsi.runtime.observe(session,imported.events.at(-1));await ctx.rsi.runtime.captureQueue;
    const handle=await ctx.sessionPersistence.open(session.id,'read');const saved=await handle.read();const restored=Session.fromRestore(session.id,saved.events,handle.header,handle.inheritedEventCount,saved.eventState);await handle.close();
    assert.deepEqual([...restored.deriveMessages()],[...session.deriveMessages()]);
    let snapshot;
    for(let i=0;i<2000;i++){snapshot=await ctx.rsi.request('snapshot',{cwd:config.root});if(snapshot.jobs.length&&snapshot.jobs.every(j=>j.status==='completed'))break;await new Promise(r=>setTimeout(r,20));}
    assert.ok(snapshot.jobs.length&&snapshot.jobs.every(j=>j.status==='completed'),JSON.stringify({jobs:snapshot.jobs,eventTypes:saved.events.map(e=>e.type),sources:ctx.rsi.runtime.state.sources()}));
    const raw=input.history.filter(m=>m.role!=='system'),job=ctx.rsi.runtime.state.jobs(snapshot.workspace.id);
    const jobMessages=job.sort((a,b)=>a.payload.turn-b.payload.turn).flatMap(j=>j.payload.messages);
    assert.deepEqual(jobMessages.filter(m=>['user','assistant'].includes(m.role)).map(m=>({role:m.role,content:m.content})),raw);
    assert.equal(snapshot.layers[snapshot.workspace.id].L0,raw.length);assert.ok(calls.length>0);
    await ctx.rsi.request('settings',{cwd:config.root,settings:{learningEnabled:false}});
    handleAgent.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:input.questions[0].prompt}]}));await handleAgent.agent.whenIdle();await ctx.sessions.flush(session);
    const rawRequest=calls.find(r=>r.sessionId===session.id),rawTexts=rawRequest.messages.map(m=>m.content.filter(b=>b.type==='text').map(b=>b.text).join(''));
    const missingBeforeAdaptation=input.history.map((row,index)=>({role:row.role,index,content:row.content})).filter(row=>!rawTexts.includes(row.content));
    // The ordinary agent renderer owns system nodes; restore dataset system backgrounds as explicit history context.
    const comparison=await ctx.agents.create({sessionId:'personamem-history-system-adapted',meta:{cwd:config.root},seed:imported.events,agentOptions:{provider:'personamem-fixture',model:'fixture'}});
    const backgrounds=input.history.map((row,index)=>({...row,index})).filter(row=>row.role==='system');
    comparison.agent.inject(createUserMessage({source:{kind:'personamem-history',form:'recall',sessionId:session.id},content:[{type:'text',text:'Original system backgrounds in this public history, in historical order (indices refer to the imported log):\n'+backgrounds.map(row=>`[Historical system at original index ${row.index}]\n${row.content}`).join('\n\n')}]}));
    comparison.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:input.questions[0].prompt}]}));await comparison.agent.whenIdle();await ctx.sessions.flush(comparison.agent.session);
    const adapted=calls.find(r=>r.sessionId===comparison.agent.session.id),actualText=adapted.messages.flatMap(m=>m.content).filter(b=>b.type==='text').map(b=>b.text).join('\n');
    const missingAfterAdaptation=input.history.map((row,index)=>({index,role:row.role,chars:row.content.length,content:row.content})).filter(row=>!actualText.includes(row.content)).map(({content,...row})=>row);
    assert.equal(missingAfterAdaptation.length,0,JSON.stringify({missingAfterAdaptation,missingBeforeAdaptation:missingBeforeAdaptation.map(({content,...row})=>row)}));
    const response={status:'PASS',checkedAt:new Date().toISOString(),importedMessages:input.history.length,rawMemoryMessages:raw.length,turnBoundaries:imported.turnBoundaries,nativeImportedJobs:snapshot.jobs.length,historyCutoffExclusive:input.historyCutoffExclusive,historySha256:createHash('sha256').update(JSON.stringify(imported.reconstructed)).digest('hex'),durableHistoryExactlyReconstructed:true,nativeTurnEndCapture:true,nativeL0Record:true,fixtureChatCalls:calls.length,historySystemNodesNormalizedAway:missingBeforeAdaptation.filter(row=>row.role==='system').map(row=>row.index),historyAfterExplicitSystemBackgroundAdaptation:true,foregroundFixtureCalls:2,realModelRequests:0,answersProvided:false,limitation:'Native import fixture only; All historical text is preserved in the adapted answering request; system backgrounds become labelled historical user context. Real model capacity still requires verification.'};
    await writeFile(join(config.root,'receipt.json'),JSON.stringify(response,null,2));process.exit(0);
  }catch(error){console.error(error);process.exit(1);}},50);return()=>clearTimeout(timer);});
}
