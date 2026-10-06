// Reuses the previous isolated review driver; no solver or parallel skill algorithm.
import assert from 'node:assert/strict';
import {readFile,writeFile,rename} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {Session} from '@deepseek-ai/dsh-session';
import {hasKnownPersonaUsage} from './personamem-pilot-task.mjs';
export const name='review-development-skill';
export const inject=['rsi','agents','sessions','sessionPersistence','llm'];
export function apply(ctx,config){
 const requests=[];let assetsBefore,core,scope;
 const durable=async(name,data)=>{const p=join(config.root,name);await writeFile(p+'.tmp',JSON.stringify(data,null,2)+'\n');await rename(p+'.tmp',p);};
 const save=()=>durable('review-requests.json',requests);
 ctx.on('llm/stream',async function*(options,next){
  assert.ok(requests.length<config.callLimit,'Fixed native Skill review budget exceeded');
  assert.ok(options.sessionId.startsWith('rsi-'),'Native review must not dispatch a task solver');
  const h=await ctx.sessionPersistence.open(options.sessionId,'read');const saved=await h.read();const restored=Session.fromRestore(options.sessionId,saved.events,h.header,h.inheritedEventCount,saved.eventState);await h.close();assert.deepEqual([...restored.deriveMessages()],options.messages,'Skill model input differs from the durable log');
  if(!requests.length){
   const body=options.messages.find(m=>m.role==='user').content.filter(b=>b.type==='text').map(b=>b.text).join('\n');
   assert.equal(createHash('sha256').update(body).digest('hex'),config.expectedFirstUserPromptSha256,'Preserve the original failed native source/inventory input');
  }
  const row={sessionId:options.sessionId,messages:structuredClone(options.messages),usage:null,responseBlocks:{},status:'DISPATCHING',inputReconstructed:true,observedAt:Date.now()};requests.push(row);await save();
  try{for await(const c of next()){if(c.type==='usage'){row.usage=c.usage;await save();}if(c.type==='text-delta')row.responseBlocks[c.index]=(row.responseBlocks[c.index]??'')+c.text;if(c.type==='block-end'&&c.block.type==='text')row.responseBlocks[c.index]=c.block.text;if(c.type==='finish')row.finish=structuredClone(c.reason);yield c;}row.status=['stop','tool-calls'].includes(row.finish?.kind)?'RETURNED':'INCOMPLETE';}catch(error){row.status='ERROR';row.error=error.message;throw error;}finally{row.finishedAt=Date.now();await save();}
 });
 ctx.effect(()=>{const alive=setInterval(()=>{},1000),wall=setTimeout(()=>ctx.rsi.runtime.abort.abort(new Error('Fixed development Skill review wall budget expired')),config.wallMs??240000),timer=setTimeout(async()=>{let receipt;try{
  await ctx.rsi.ready;
  const original=(await readFile(config.source,'utf8')).trim().split('\n').map(JSON.parse),events=original.filter(e=>Number.isSafeInteger(e.seq)),payload=JSON.parse(await readFile(config.payload,'utf8'));
  scope=await ctx.rsi.runtime.scope(config.cwd);core=await ctx.rsi.runtime.core(scope.id);
  assert.equal((await core.skills.list({team_id:scope.id,user_id:'local-user',agent_id:'local-agent',limit:50})).items.length,0,'Development library must start empty');
  const initial=JSON.parse(await readFile(config.initialSkill,'utf8'));
  await core.skills.create({team_id:scope.id,user_id:'local-user',agent_id:'local-agent',name:initial.name,content:initial.content});
  assetsBefore=await ctx.rsi.request('export',{cwd:config.cwd});await durable('initial-assets.json',assetsBefore);
  assert.equal(assetsBefore.skills.length,1);assert.equal(assetsBefore.skills[0].content,initial.content,'Native copy changed the source body');
  const id=payload.sessionId,handle=await ctx.agents.create({sessionId:id,meta:{cwd:config.cwd},seed:events,agentOptions:{provider:'qwen',model:'qwen3.8-27b'}});await ctx.sessions.flush(handle.agent.session);
  const h=await ctx.sessionPersistence.open(id,'read');const data=await h.read();assert.deepEqual([...Session.fromRestore(id,data.events,h.header,h.inheritedEventCount,data.eventState).deriveMessages()],[...handle.agent.session.deriveMessages()]);await h.close();
  const result=await ctx.rsi.runtime.within(scope.id,()=>core.createSkillExtractor('zh-CN').extract({team_id:scope.id,user_id:'local-user',agent_id:'local-agent',session_id:id,task_id:'development-skill-review',messages:payload.messages,reason:`记录的轮次结果：${JSON.stringify(payload.reason)}`}),{route:{provider:'qwen',model:'qwen3.8-27b'},sessionId:id,manual:true});
  receipt={status:'GENERATED_REQUIRES_CONTENT_REVIEW',sourceSessionId:id,sourceMessages:payload.messages.length,sourceLogReconstructed:true,result,originalUserPromptExact:true,nativeAssignedCopyVersion:assetsBefore.skills[0].version,originalSkillVersion:initial.version,taskSolverRequests:0,taskCommandsExecuted:0,scorerRead:false,independentEffectClaim:false};
 }catch(error){receipt={status:'ERROR',error:error.message};}finally{
  if(scope){try{await durable('review-assets.json',await ctx.rsi.request('export',{cwd:config.cwd}));}catch(error){receipt.exportError=error.message;}}
  clearTimeout(wall);await ctx.root.fiber.dispose();await save();receipt={...receipt,actualRequests:requests.length,knownTokens:requests.reduce((n,r)=>n+(hasKnownPersonaUsage(r)?r.usage.totalTokens:0),0),unknownActualUsage:requests.filter(r=>!hasKnownPersonaUsage(r)).length};await durable('review-receipt.json',receipt);console.log(JSON.stringify(receipt));process.exit(receipt.status==='ERROR'?1:0);
 }},50);return()=>{clearInterval(alive);clearTimeout(timer);clearTimeout(wall);};});
}
