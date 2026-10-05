import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {Session} from '@deepseek-ai/dsh-session';
import {appendPersonaHistory} from './personamem-history.mjs';
import {shouldExtractL1} from '../lib/core-entry.js';
export const name='review-development-memory';
export const inject=['rsi','agents','sessions','sessionPersistence','llm'];
export function apply(ctx,config){
  const requests=[];
  ctx.on('llm/stream',async function*(options,next){
    assert.ok(requests.length<1,'One-call review budget exceeded');assert.ok(options.sessionId.startsWith('rsi-'),'Review must not dispatch a task solver');
    const handle=await ctx.sessionPersistence.open(options.sessionId,'read');const saved=await handle.read();
    assert.deepEqual([...Session.fromRestore(options.sessionId,saved.events,handle.header,handle.inheritedEventCount,saved.eventState).deriveMessages()],options.messages);await handle.close();
    const request={sessionId:options.sessionId,status:'DISPATCHING',usage:null,messages:structuredClone(options.messages),inputReconstructed:true};requests.push(request);
    try{for await(const chunk of next()){if(chunk.type==='usage')request.usage=chunk.usage;if(chunk.type==='finish')request.finishReason=structuredClone(chunk.reason);yield chunk;}request.status=['stop','tool-calls'].includes(request.finishReason?.kind)?'RETURNED':'INCOMPLETE';}catch(error){request.status='ERROR';request.error=error.message;throw error;}
  });
  ctx.effect(()=>{const alive=setInterval(()=>{},1000),timer=setTimeout(async()=>{let receipt;try{
    await ctx.rsi.ready;
    const id='development-source-review';let events;
    if(config.importHistory){
      const input=JSON.parse(await readFile(config.source,'utf8'));assert.deepEqual(Object.keys(input),['history']);
      const seed=ctx.sessions.prepare(id,{meta:{cwd:config.root}});events=(await appendPersonaHistory(seed,input.history,{systemBoundaries:true})).events;
    }else{
      const lines=(await readFile(config.source,'utf8')).trim().split('\n').map(JSON.parse);events=lines.filter(row=>Number.isSafeInteger(row.seq));
    }
    const handle=await ctx.agents.create({sessionId:id,meta:{cwd:config.root},seed:events,agentOptions:{provider:'qwen',model:'qwen3.8-27b'}});await ctx.sessions.flush(handle.agent.session);
    const stored=await ctx.sessionPersistence.open(id,'read');const data=await stored.read();const restored=Session.fromRestore(id,data.events,stored.header,stored.inheritedEventCount,data.eventState);assert.deepEqual([...restored.deriveMessages()],[...handle.agent.session.deriveMessages()]);await stored.close();
    // Same native L1 input boundary; original tool results stay in the imported log, not prose evidence.
    let messages=[];
    for(const event of data.events){
      const message=event.type==='user/message'&&event.data.source.kind==='user'?event.data:event.type==='assistant/message'?event.data.message:null;
      if(message)messages.push({id:message.id,role:message.role,content:message.content.map(b=>b.type==='text'?b.text:JSON.stringify(b)).join('\n'),timestamp:event.time});
    }
    const scope=await ctx.rsi.runtime.scope(config.root),core=await ctx.rsi.runtime.core(scope.id);
    if(config.importHistory){
      assert.equal(ctx.rsi.runtime.state.settings().learningEnabled,false,'Manual development batch must not start automatic learning');
      await ctx.rsi.runtime.captureStored(id,config.root);
      const job=ctx.rsi.runtime.state.jobs(scope.id).find(j=>j.payload.sessionId===id&&j.payload.turn===config.turn);assert.ok(job);
      const source=job.payload.messages.filter(m=>['user','assistant'].includes(m.role)&&shouldExtractL1(m.content));
      assert.ok(Number.isSafeInteger(config.batchStart)&&config.batchStart>=0&&config.batchStart<source.length);
      // Replay one existing ten-new/five-background batch; do not replace the native formatter.
      messages=source.slice(Math.max(0,config.batchStart-5),config.batchStart+10).map(m=>({...m,timestamp:Date.parse(m.timestamp)}));
      assert.ok(messages.every(m=>m.timestampKind==='imported-unknown'));
      await writeFile(join(config.root,'source-batch.json'),JSON.stringify(messages,null,2));
    }
    const result=await ctx.rsi.runtime.within(scope.id,()=>core.extractMemories({messages,sessionKey:id,sessionId:id}),{route:{provider:'qwen',model:'qwen3.8-27b'},sessionId:id,manual:true});
    const records=await core.readMemories();
    const oneOffRules=records.filter(r=>r.type==='instruction'&&/get_inlines|ModelAdmin/.test(r.content));
    receipt={status:config.importHistory?'GENERATED_REQUIRES_CONTENT_REVIEW':oneOffRules.length?'FAIL':'PASS',checkedAt:new Date().toISOString(),method:'One native L1 development replay into fresh assets; no task solver, Skill review, scorer input or effect claim.',sourceMessages:messages.length,storedCount:result.storedCount,records,oneOffRules:oneOffRules.map(r=>r.id),realModelRequests:requests.length,knownTokens:requests.reduce((sum,r)=>sum+(r.usage?.totalTokens??0),0),unknownUsage:requests.filter(r=>!r.usage||!Number.isFinite(r.usage.totalTokens)||r.usage.totalTokens<=0).length,allInputsReconstructed:requests.every(r=>r.inputReconstructed),importedTimeReview:config.importHistory===true,sourceTurn:config.turn,batchStart:config.batchStart,importedSourceLogExactlyReconstructable:true,scopeDataDir:core.directory};
  }catch(error){receipt={status:'ERROR',error:error.message,requests:requests.length};}finally{
    await ctx.root.fiber.dispose();await writeFile(join(config.root,'review-requests.json'),JSON.stringify(requests,null,2));await writeFile(join(config.root,'review-receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));process.exit(['PASS','GENERATED_REQUIRES_CONTENT_REVIEW'].includes(receipt.status)?0:1);
  }},50);return()=>{clearInterval(alive);clearTimeout(timer);};});
}
