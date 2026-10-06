// Uses the isolated review observer and the production native memory entry point.
import assert from 'node:assert/strict';
import {readFile,writeFile,rename} from 'node:fs/promises';
import {join} from 'node:path';
import {Session} from '@deepseek-ai/dsh-session';
import {hasKnownPersonaUsage} from './personamem-pilot-task.mjs';
export const name='review-development-memory';
export const inject=['rsi','agents','sessions','sessionPersistence','llm'];
export function apply(ctx,config){
 const requests=[];
 const save=async(name,value)=>{const p=join(config.root,name);await writeFile(p+'.tmp',JSON.stringify(value,null,2)+'\n');await rename(p+'.tmp',p);};
 ctx.on('llm/stream',async function*(options,next){
  assert.ok(requests.length<config.callLimit,'Fixed actual call bound exceeded');assert.ok(options.sessionId.startsWith('rsi-'),'No task solver allowed');
  const h=await ctx.sessionPersistence.open(options.sessionId,'read'),r=await h.read();const restored=Session.fromRestore(options.sessionId,r.events,h.header,h.inheritedEventCount,r.eventState);await h.close();assert.deepEqual([...restored.deriveMessages()],options.messages);
  const row={sessionId:options.sessionId,messages:structuredClone(options.messages),usage:null,responseBlocks:{},status:'DISPATCHING',inputReconstructed:true};requests.push(row);await save('review-requests.json',requests);
  try{for await(const c of next()){if(c.type==='usage')row.usage=c.usage;if(c.type==='text-delta')row.responseBlocks[c.index]=(row.responseBlocks[c.index]??'')+c.text;if(c.type==='block-end'&&c.block.type==='text')row.responseBlocks[c.index]=c.block.text;if(c.type==='finish')row.finish=structuredClone(c.reason);yield c;}row.status=['stop','tool-calls'].includes(row.finish?.kind)?'RETURNED':'INCOMPLETE';}catch(e){row.status='ERROR';row.error=e.message;throw e;}finally{await save('review-requests.json',requests);}
 });
 ctx.effect(()=>{const alive=setInterval(()=>{},1000),wall=setTimeout(()=>ctx.rsi.runtime.abort.abort(new Error('Fixed development wall expired')),config.wallMs),timer=setTimeout(async()=>{let receipt,scope;
  try{
   await ctx.rsi.ready;const payload=JSON.parse(await readFile(config.payload,'utf8')),raw=(await readFile(config.source,'utf8')).trim().split('\n').map(JSON.parse),events=raw.filter(x=>Number.isSafeInteger(x.seq));
   scope=await ctx.rsi.runtime.scope(config.cwd);const core=await ctx.rsi.runtime.core(scope.id);assert.equal((await core.readMemories()).length,0,'Start with an empty native candidate library');
   const h=await ctx.agents.create({sessionId:payload.sessionId,meta:{cwd:config.cwd},seed:events,agentOptions:{provider:'qwen',model:'qwen3.8-27b'}});await ctx.sessions.flush(h.agent.session);
   const derived=[...h.agent.session.deriveMessages()];for(const m of payload.messages){const original=derived.find(x=>x.id===m.id);assert.ok(original);assert.equal(original.content.filter(b=>b.type==='text').map(b=>b.text).join('\n'),m.content);}
   const result=await ctx.rsi.runtime.within(scope.id,()=>core.extractMemories({...payload,sessionKey:payload.sessionId}),{route:{provider:'qwen',model:'qwen3.8-27b'},sessionId:payload.sessionId,manual:true});
   receipt={status:'NATIVE_MEMORY_GENERATED_REQUIRES_CONTENT_REVIEW',sourceMessages:payload.messages.length,sourceProseMatchesImportedLog:true,result,taskSolverCalls:0,taskCommands:0,scorerRead:false,consumerCalls:0,independentEffectClaim:false};
  }catch(e){receipt={status:'ERROR',error:e.message};}finally{
   if(scope)try{await save('review-assets.json',await ctx.rsi.request('export',{cwd:config.cwd}));}catch(e){receipt.exportError=e.message;}
   clearTimeout(wall);await ctx.root.fiber.dispose();await save('review-requests.json',requests);receipt={...receipt,actualRequests:requests.length,knownTokens:requests.reduce((n,r)=>n+(hasKnownPersonaUsage(r)?r.usage.totalTokens:0),0),unknownActualUsage:requests.filter(r=>!hasKnownPersonaUsage(r)).length};await save('review-receipt.json',receipt);console.log(JSON.stringify(receipt));process.exit(receipt.status==='ERROR'?1:0);
  }
 },50);return()=>{clearInterval(alive);clearTimeout(wall);clearTimeout(timer);};});
}
