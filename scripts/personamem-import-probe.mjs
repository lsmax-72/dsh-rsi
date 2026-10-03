import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {LlmAdapter} from '@deepseek-ai/dsh-llm';
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
    const imported=appendPersonaHistory(seed,input.history);
    const handleAgent=await ctx.agents.create({sessionId:seed.id,meta:{cwd:config.root},seed:imported.events,agentOptions:{provider:'personamem-fixture',model:'fixture'}});
    const session=handleAgent.agent.session;
    assert.equal(createHash('sha256').update(JSON.stringify([...session.deriveMessages()].map(m=>({role:m.role,content:m.content.map(b=>b.text).join('')})))).digest('hex'),createHash('sha256').update(JSON.stringify(input.history)).digest('hex'),'Agent factory lost imported seed');
    await ctx.sessions.flush(session);
    // Seed events are not republished. Import adaptation enters the same persisted-log recovery path.
    ctx.rsi.runtime.observe(session,imported.events.at(-1));await ctx.rsi.runtime.captureQueue;
    const handle=await ctx.sessionPersistence.open(session.id,'read');const saved=await handle.read();const restored=Session.fromRestore(session.id,saved.events,handle.header,handle.inheritedEventCount,saved.eventState);await handle.close();
    assert.deepEqual([...restored.deriveMessages()],[...session.deriveMessages()]);
    let snapshot;
    for(let i=0;i<500;i++){snapshot=await ctx.rsi.request('snapshot',{cwd:config.root});if(snapshot.jobs[0]?.status==='completed')break;await new Promise(r=>setTimeout(r,20));}
    assert.equal(snapshot.jobs[0]?.status,'completed',JSON.stringify({jobs:snapshot.jobs,eventTypes:saved.events.map(e=>e.type),sources:ctx.rsi.runtime.state.sources()}));
    const raw=input.history.filter(m=>m.role!=='system'),job=ctx.rsi.runtime.state.jobs(snapshot.workspace.id)[0];
    assert.deepEqual(job.payload.messages.filter(m=>['user','assistant'].includes(m.role)).map(m=>({role:m.role,content:m.content})),raw);
    assert.equal(snapshot.layers[snapshot.workspace.id].L0,raw.length);assert.ok(calls.length>0);
    const response={status:'PASS',checkedAt:new Date().toISOString(),importedMessages:input.history.length,rawMemoryMessages:raw.length,historyCutoffExclusive:input.historyCutoffExclusive,historySha256:createHash('sha256').update(JSON.stringify(imported.reconstructed)).digest('hex'),durableHistoryExactlyReconstructed:true,nativeTurnEndCapture:true,nativeL0Record:true,fixtureChatCalls:calls.length,realModelRequests:0,answersProvided:false,limitation:'Native import fixture only; model capacity and answering requests with unchanged history still require verification.'};
    await writeFile(join(config.root,'receipt.json'),JSON.stringify(response,null,2));process.exit(0);
  }catch(error){console.error(error);process.exit(1);}},50);return()=>clearTimeout(timer);});
}
