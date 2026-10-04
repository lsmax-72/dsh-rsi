import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {Session} from '@deepseek-ai/dsh-session';
export const name='review-development-memory';
export const inject=['rsi','agents','sessions','sessionPersistence','llm'];
export function apply(ctx,config){
  const requests=[];
  ctx.on('llm/stream',async function*(options,next){assert.ok(requests.length<1,'One-call review budget exceeded');const request={sessionId:options.sessionId,status:'DISPATCHING',usage:null,messages:structuredClone(options.messages)};requests.push(request);try{for await(const chunk of next()){if(chunk.type==='usage')request.usage=chunk.usage;yield chunk;}request.status='RETURNED';}catch(error){request.status='ERROR';request.error=error.message;throw error;}});
  ctx.effect(()=>{const alive=setInterval(()=>{},1000),timer=setTimeout(async()=>{let receipt;try{
    await ctx.rsi.ready;
    const lines=(await readFile(config.source,'utf8')).trim().split('\n').map(JSON.parse),events=lines.filter(row=>Number.isSafeInteger(row.seq));
    const id='development-source-review',handle=await ctx.agents.create({sessionId:id,meta:{cwd:config.root},seed:events,agentOptions:{provider:'qwen',model:'qwen3.8-27b'}});await ctx.sessions.flush(handle.agent.session);
    const stored=await ctx.sessionPersistence.open(id,'read');const data=await stored.read();const restored=Session.fromRestore(id,data.events,stored.header,stored.inheritedEventCount,data.eventState);assert.deepEqual([...restored.deriveMessages()],[...handle.agent.session.deriveMessages()]);await stored.close();
    // Same native L1 input boundary; original tool results stay in the imported log, not prose evidence.
    const messages=[];
    for(const event of data.events){
      const message=event.type==='user/message'&&event.data.source.kind==='user'?event.data:event.type==='assistant/message'?event.data.message:null;
      if(message)messages.push({id:message.id,role:message.role,content:message.content.map(b=>b.type==='text'?b.text:JSON.stringify(b)).join('\n'),timestamp:event.time});
    }
    const scope=await ctx.rsi.runtime.scope(config.root),core=await ctx.rsi.runtime.core(scope.id);
    const result=await ctx.rsi.runtime.within(scope.id,()=>core.extractMemories({messages,sessionKey:id,sessionId:id}),{route:{provider:'qwen',model:'qwen3.8-27b'},sessionId:id,manual:true});
    const records=await core.readMemories();
    const oneOffRules=records.filter(r=>r.type==='instruction'&&/get_inlines|ModelAdmin/.test(r.content));
    receipt={status:oneOffRules.length?'FAIL':'PASS',checkedAt:new Date().toISOString(),method:'One native L1 development replay into fresh assets; no task solver, Skill review, scorer input or effect claim.',sourceMessages:messages.length,storedCount:result.storedCount,records,oneOffRules:oneOffRules.map(r=>r.id),realModelRequests:requests.length,knownTokens:requests.reduce((sum,r)=>sum+(r.usage?.totalTokens??0),0),unknownUsage:requests.filter(r=>!r.usage).length,importedSourceLogExactlyReconstructable:true,scopeDataDir:core.directory};
  }catch(error){receipt={status:'ERROR',error:error.message,requests:requests.length};}finally{
    await ctx.root.fiber.dispose();await writeFile(join(config.root,'review-requests.json'),JSON.stringify(requests,null,2));await writeFile(join(config.root,'review-receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));process.exit(receipt.status==='PASS'?0:1);
  }},50);return()=>{clearInterval(alive);clearTimeout(timer);};});
}
