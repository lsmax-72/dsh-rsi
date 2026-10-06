// Data-only quality diagnostic: uses the production bridge and native L0/L1/L2/L3 APIs.
import assert from 'node:assert/strict';
import {readFile,writeFile,rename} from 'node:fs/promises';
import {join} from 'node:path';
import {Session} from '@deepseek-ai/dsh-session';
import {appendPersonaHistory} from './personamem-history.mjs';
import {hasKnownPersonaUsage} from './personamem-pilot-task.mjs';
export const name='review-profile-time';
export const inject=['rsi','agents','sessions','sessionPersistence','llm'];
export function apply(ctx,config){
 const requests=[],stages=[];let phase='import';
 const save=async(name,value)=>{const p=join(config.root,name);await writeFile(p+'.tmp',JSON.stringify(value,null,2)+'\n');await rename(p+'.tmp',p);};
 ctx.on('llm/stream',async function*(options,next){
  assert.equal(config.dryRun,false,'Dry run must never dispatch');
  assert.ok(requests.length<config.callLimit,'Fixed actual call cap exceeded');
  assert.ok(options.sessionId.startsWith('rsi-'),'No task solver allowed');
  assert.equal(options.provider,'qwen');assert.equal(options.model,'qwen3.8-27b');
  for(const tool of options.tools??[])assert.ok(['read','write','edit'].includes(tool.name),'Only native asset storage tools allowed');
  const h=await ctx.sessionPersistence.open(options.sessionId,'read'),r=await h.read();
  const restored=Session.fromRestore(options.sessionId,r.events,h.header,h.inheritedEventCount,r.eventState);await h.close();
  assert.deepEqual([...restored.deriveMessages()],options.messages);
  const row={sessionId:options.sessionId,phase,messages:structuredClone(options.messages),tools:structuredClone(options.tools??[]),usage:null,responseBlocks:{},status:'DISPATCHING',inputReconstructed:true,prefixEndSeq:r.events.at(-1)?.seq,observedAt:Date.now()};
  requests.push(row);await save('requests.json',requests);
  try{
   for await(const c of next()){
    if(c.type==='usage')row.usage=c.usage;
    if(c.type==='text-delta')row.responseBlocks[c.index]=(row.responseBlocks[c.index]??'')+c.text;
    if(c.type==='block-end') {row.blocks??=[];row.blocks.push(structuredClone(c.block));if(c.block.type==='text')row.responseBlocks[c.index]=c.block.text;}
    if(c.type==='finish')row.finish=structuredClone(c.reason);yield c;
   }
   row.status=['stop','tool-calls'].includes(row.finish?.kind)?'RETURNED':'INCOMPLETE';
  }catch(e){row.status='ERROR';row.error=e.message;throw e;}
  finally{if(row.status==='DISPATCHING')row.status=['stop','tool-calls'].includes(row.finish?.kind)?'RETURNED':'INCOMPLETE';row.finishedAt=Date.now();await save('requests.json',requests);}
 });
 ctx.effect(()=>{
  const alive=setInterval(()=>{},1000),wall=setTimeout(()=>ctx.rsi.runtime.abort.abort(new Error('Fixed profile review wall expired')),config.wallMs);
  const timer=setTimeout(async()=>{let receipt,scope,core;
   try{
    await ctx.rsi.ready;const history=JSON.parse(await readFile(config.history,'utf8'));
    scope=await ctx.rsi.runtime.scope(config.cwd);core=await ctx.rsi.runtime.core(scope.id);
    assert.deepEqual(await core.layerCounts(),{L0:0,L1:0,L2:0,L3:0},'Fresh native library required');
    const session=ctx.sessions.prepare('synthetic-profile-time-history',{meta:{cwd:config.cwd}});
    const imported=await appendPersonaHistory(session,history,{sourceLabel:'synthetic-profile-time-v1'});
    const h=await ctx.agents.create({sessionId:session.id,meta:{cwd:config.cwd},seed:imported.events,agentOptions:{provider:'qwen',model:'qwen3.8-27b'}});await ctx.sessions.flush(h.agent.session);
    const derived=[...h.agent.session.deriveMessages()];assert.deepEqual(derived.map(m=>({role:m.role,content:m.content.map(b=>b.text).join('')})),history);
    const reader=await ctx.sessionPersistence.open(session.id,'read'),stored=await reader.read();
    const durable=Session.fromRestore(session.id,stored.events,reader.header,reader.inheritedEventCount,stored.eventState);await reader.close();assert.deepEqual([...durable.deriveMessages()],derived);
    await save('source-events.json',stored.events);
    const messages=derived.filter(m=>['user','assistant'].includes(m.role)).map(m=>{
     const event=imported.events.find(e=>e.type==='user/message'?e.data.id===m.id:e.type==='assistant/message'&&e.data.message.id===m.id);assert.ok(event);
     return {id:m.id,role:m.role,content:m.content.map(b=>b.text).join(''),timestamp:event.time,timestampKind:'imported-unknown'};
    });
    await save('source-messages.json',messages);
    phase='L0';const captured=await core.record({sessionKey:session.id,sessionId:session.id,rawMessages:messages});
    assert.deepEqual(captured.map(m=>({id:m.id,role:m.role,content:m.content})),messages.map(m=>({id:m.id,role:m.role,content:m.content})));stages.push({phase,success:true,count:captured.length});await save('stages.json',stages);
    if(!config.dryRun){
     await ctx.rsi.runtime.within(scope.id,async()=>{
      phase='L1';const result=await core.extractMemories({sessionKey:session.id,sessionId:session.id,messages,newMessageCount:messages.length});stages.push({phase,success:true,result});await save('stages.json',stages);
      phase='L2';const scenes=await core.extractScenes('');stages.push({phase,success:true,result:scenes});await save('stages.json',stages);
      phase='L3';const generated=await core.generatePersona();stages.push({phase,success:true,result:generated,trigger:await core.personaTrigger.shouldGenerate()});await save('stages.json',stages);
     },{route:{provider:'qwen',model:'qwen3.8-27b'},sessionId:session.id,manual:true});
    }
    receipt={status:config.dryRun?'NO_DISPATCH_PREFLIGHT_PASSED':'NATIVE_OUTPUT_REQUIRES_CONTENT_REVIEW',sourceMessages:messages.length,sourceProseMatchesDurableLog:true,layers:await core.layerCounts()};
   }catch(e){stages.push({phase,success:false,error:e.message,code:e.code});receipt={status:'ERROR',phase,error:e.message,code:e.code};}
   finally{
    clearTimeout(wall);
    if(scope)try{await save('assets.json',await ctx.rsi.request('export',{cwd:config.cwd}));await save('snapshot.json',await ctx.rsi.request('snapshot',{cwd:config.cwd}));}catch(e){receipt.exportError=e.message;}
    if(core)for(const layer of ['L0','L1','L2','L3'])try{await save(layer+'.json',await core.readLayer(layer));}catch(e){receipt[layer+'ReadError']=e.message;}
    // Preserve native ends and executed storage results, including terminal failed calls.
    for(const id of [...new Set(requests.map(r=>r.sessionId))])try{const h=await ctx.sessionPersistence.open(id,'read'),s=await h.read();await h.close();await save(id+'.events.json',s.events);}catch(e){receipt.sessionReadError=e.message;}
    await ctx.root.fiber.dispose();clearInterval(alive);await save('requests.json',requests);await save('stages.json',stages);
    receipt={...receipt,actualRequests:requests.length,knownTokens:requests.reduce((n,r)=>n+(hasKnownPersonaUsage(r)?r.usage.totalTokens:0),0),unknownActualUsage:requests.filter(r=>!hasKnownPersonaUsage(r)).length,embeddingTokenUsage:null,taskSolverCalls:0,taskCommands:0,consumerCalls:0,scorerRead:false,independentEffectClaim:false,triggerMode:'manual native sequence, not automatic scheduler validation'};
    await save('receipt.json',receipt);console.log(JSON.stringify(receipt));process.exit(receipt.status==='ERROR'?1:0);
   }
  },50);
  return()=>{clearInterval(alive);clearTimeout(wall);clearTimeout(timer);};
 });
}
