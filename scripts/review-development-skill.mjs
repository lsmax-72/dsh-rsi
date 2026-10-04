import assert from 'node:assert/strict';
import {readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {Session} from '@deepseek-ai/dsh-session';
export const name='review-development-skill';
export const inject=['rsi','agents','sessions','sessionPersistence','llm'];
export function apply(ctx,config){
 const requests=[];
 const save=()=>writeFile(join(config.root,'review-requests.json'),JSON.stringify(requests,null,2));
 ctx.on('llm/stream',async function*(options,next){
  assert.ok(requests.length<config.callLimit,'Fixed native Skill review budget exceeded');
  const handle=await ctx.sessionPersistence.open(options.sessionId,'read');const saved=await handle.read();const restored=Session.fromRestore(options.sessionId,saved.events,handle.header,handle.inheritedEventCount,saved.eventState);await handle.close();assert.deepEqual([...restored.deriveMessages()],options.messages,'Skill model input differs from the durable log');
  const row={sessionId:options.sessionId,messages:structuredClone(options.messages),usage:null,status:'DISPATCHING',inputReconstructed:true};requests.push(row);await save();
  try{for await(const chunk of next()){if(chunk.type==='usage'){row.usage=chunk.usage;await save();}yield chunk;}row.status='RETURNED';}catch(error){row.status='ERROR';row.error=error.message;throw error;}finally{await save();}
 });
 ctx.effect(()=>{const alive=setInterval(()=>{},1000),wall=setTimeout(()=>ctx.rsi.runtime.abort.abort(new Error('Fixed development Skill review wall budget expired')),240000),timer=setTimeout(async()=>{let receipt;try{
  await ctx.rsi.ready;
  const original=(await readFile(config.source,'utf8')).trim().split('\n').map(JSON.parse);const events=original.filter(row=>Number.isSafeInteger(row.seq));const payload=JSON.parse(await readFile(config.payload,'utf8'));
  const id=config.sourceReviewId??'development-skill-source-review';const handle=await ctx.agents.create({sessionId:id,meta:{cwd:config.root},seed:events,agentOptions:{provider:'qwen',model:'qwen3.8-27b'}});await ctx.sessions.flush(handle.agent.session);
  const stored=await ctx.sessionPersistence.open(id,'read');const data=await stored.read();assert.deepEqual([...Session.fromRestore(id,data.events,stored.header,stored.inheritedEventCount,data.eventState).deriveMessages()],[...handle.agent.session.deriveMessages()]);await stored.close();
  const scope=await ctx.rsi.runtime.scope(config.cwd??config.root),core=await ctx.rsi.runtime.core(scope.id);
  const result=await ctx.rsi.runtime.within(scope.id,()=>core.createSkillExtractor('zh-CN').extract({team_id:scope.id,user_id:'local-user',agent_id:'local-agent',session_id:id,task_id:'development-skill-review',messages:payload.messages,reason:`记录的轮次结果：${JSON.stringify(payload.reason)}${config.reviewReason?'\n'+config.reviewReason:''}`}),{route:{provider:'qwen',model:'qwen3.8-27b'},sessionId:id,manual:true});
  const assets=await ctx.rsi.request('export',{cwd:config.cwd??config.root});await writeFile(join(config.root,'review-assets.json'),JSON.stringify(assets,null,2));
  receipt={status:'GENERATED_REQUIRES_CONTENT_REVIEW',sourceSessionId:payload.sessionId,sourceMessages:payload.messages.length,sourceRoles:payload.messages.reduce((r,m)=>(r[m.role]=(r[m.role]??0)+1,r),{}),sourceLogReconstructed:true,result,skillCount:assets.skills.length,actualRequests:requests.length,knownTokens:requests.reduce((n,r)=>n+(r.usage?.totalTokens??0),0),unknownActualUsage:requests.filter(r=>!r.usage).length,taskSolverRequests:0,taskCommandsExecuted:0,scorerRead:false,independentEffectClaim:false};
 }catch(error){receipt={status:'ERROR',error:error.message,actualRequests:requests.length,knownTokens:requests.reduce((n,r)=>n+(r.usage?.totalTokens??0),0),unknownActualUsage:requests.filter(r=>!r.usage).length};}finally{
  clearTimeout(wall);await ctx.root.fiber.dispose();await writeFile(join(config.root,'review-requests.json'),JSON.stringify(requests,null,2));await writeFile(join(config.root,'review-receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));process.exit(receipt.status==='ERROR'?1:0);
 }},50);return()=>{clearInterval(alive);clearTimeout(timer);clearTimeout(wall);};});
}
