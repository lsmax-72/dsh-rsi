import assert from 'node:assert/strict';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {LlmAdapter,createUserMessage} from '@deepseek-ai/dsh-llm';
import {Session} from '@deepseek-ai/dsh-session';
export const name='runtime-skill-budget-probe';
export const inject=['rsi','llm','agents','sessions','sessionPersistence','skills'];
const make=(name,body)=>`---\nname: ${name}\ndescription: 自动提炼预算夹具\n---\n\n${body}`;
const compact='# 流程\n保留必要决策与失败分支。\n\n## 证据\n以下仅为夹具，不是真实任务经验。\n\n## 资源\n详细数据见 notes/fact.txt。';
const resource='这是逐项证据夹具数据，不执行脚本。\n'.repeat(100);
export function apply(ctx,config){
 const rows=[];let skillCalls=0;
 ctx.on('llm/stream',async function*(options,next){
  const session=ctx.sessions.get(options.sessionId);if(session)await ctx.sessions.flush(session);
  const h=await ctx.sessionPersistence.open(options.sessionId,'read'),stored=await h.read();
  assert.deepEqual([...Session.fromRestore(options.sessionId,stored.events,h.header,h.inheritedEventCount,stored.eventState).deriveMessages()],options.messages);await h.close();
  rows.push({sessionId:options.sessionId,matches:true});yield* next();
 });
 class Fixture extends LlmAdapter {
  async *stream(options){
   const system=options.messages.filter(m=>m.role==='system').flatMap(m=>m.content).map(b=>b.text??'').join('\n');let block;
   if(!options.sessionId.startsWith('rsi-'))block={type:'text',text:'显式夹具完成。'};
   else if(!system.includes('You are the Skill Review Agent'))block={type:'text',text:'[]'};
   else{
    skillCalls++;const text=options.messages.filter(m=>m.role==='tool').at(-1)?.content.filter(b=>b.type==='text').map(b=>b.text).join('');
    if(skillCalls===1)block={type:'tool-call',id:'budget-create-over',name:'skill_create',arguments:JSON.stringify({name:'budget-over',content:make('budget-over','长内容'.repeat(600))})};
    else if(skillCalls===2){assert.match(text,/RSI_SKILL_BODY_BUDGET_EXCEEDED/);block={type:'tool-call',id:'budget-create-small',name:'skill_create',arguments:JSON.stringify({name:'budget-small',content:make('budget-small',compact)})};}
    else if(skillCalls===3){const prior=JSON.parse(text);assert.ok(prior.ok);block={type:'tool-call',id:'budget-resource',name:'skill_files_write',arguments:JSON.stringify({skill_id:prior.skill_id,expected_version:prior.version,path:'notes/fact.txt',content:resource})};}
    else{assert.equal(skillCalls,4);assert.ok(JSON.parse(text).ok);block={type:'text',text:'Created budget-small with notes/fact.txt.'};}
   }
   yield{type:'block-start',index:0,blockType:block.type};yield{type:'block-end',index:0,block};yield{type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};yield{type:'finish',reason:{kind:block.type==='tool-call'?'tool-calls':'stop'}};
  }
 }
 ctx.effect(()=>ctx.llm.registerAdapter(['rsi-probe'],new Fixture()));
 ctx.effect(()=>{const alive=setInterval(()=>{},1000),timer=setTimeout(async()=>{try{
  await ctx.rsi.ready;const cwd=join(config.root,'workspace');await mkdir(cwd,{recursive:true});
  if(config.phase==='restore'){
   const state=await ctx.rsi.request('snapshot',{cwd});assert.equal(state.jobs[0].status,'completed');assert.equal(state.skills.find(s=>s.name==='budget-small').version,2);const asset=await ctx.skills.get('rsi-budget-small',{cwd});assert.equal(asset.content,compact);assert.equal(await readFile(join(asset.resourceBase.path,'notes/fact.txt'),'utf8'),resource);assert.equal(rows.length,0);
   await writeFile(join(config.root,'restored.json'),JSON.stringify({status:'PASS',restoredNativeVersion:2,restoredResourceComplete:true,realModelRequests:0}));process.exit(0);
  }
  const agent=await ctx.agents.create({sessionId:'budget-source',meta:{cwd},agentOptions:{provider:'rsi-probe',model:'fixture'}});
  const protocol='BUDGET_PROBE_PROTOCOL_NOT_A_LEARNED_PREFERENCE';agent.agent.inject(createUserMessage({source:{kind:'benchmark-protocol',form:'instructions'},content:[{type:'text',text:protocol}]}));
  agent.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:'保存当前工作区的测试流程，保留失败结果与逐项来源。'}]}));await agent.agent.whenIdle();await ctx.sessions.flush(agent.agent.session);
  let state;for(let i=0;i<400;i++){state=await ctx.rsi.request('snapshot',{cwd});if(state.jobs[0]?.status==='completed')break;await new Promise(r=>setTimeout(r,20));}
  assert.equal(state.jobs[0]?.status,'completed',JSON.stringify(state.jobs));assert.equal(skillCalls,4);
  assert.equal(state.skills.length,1);assert.equal(state.skills[0].name,'budget-small');assert.equal(state.skills[0].version,2);
  assert.ok(!JSON.stringify(ctx.rsi.runtime.state.jobs(state.workspace.id)[0].payload.messages).includes(protocol));
  const asset=await ctx.skills.get('rsi-budget-small',{cwd});assert.equal(asset.content,compact);assert.equal(await readFile(join(asset.resourceBase.path,'notes/fact.txt'),'utf8'),resource);
  const exported=await ctx.rsi.request('export',{cwd});const head=exported.skills.find(s=>s.head.name==='budget-small');assert.equal(head.versions.length,2);const latest=head.versions.find(v=>v.version===2);assert.equal(latest.resources.length,1);assert.equal(Buffer.from(latest.resources[0].content,'base64').toString('utf8'),resource);
  const result={status:'PASS',nativeJobCompleted:true,nativeRejectedThenCorrectedWithinSameReview:true,nativeModelBridgeAndFormatSeamScopePreserved:true,skillReviewFixtureCalls:skillCalls,allActualFixtureInputsDurablyReconstructed:rows.every(r=>r.matches),fixtureDispatchCount:rows.length,protocolExcludedFromLearning:true,storedBodyChars:[...asset.content].length,resourceChars:[...resource].length,actualProviderResourceDirectoryResolved:true,nativeVersionedExportContainsFullResource:true,realModelRequests:0,resourceScriptsExecuted:false,modelAndEncodingFixtures:true,qualityOrEffectClaim:false,limitation:'Installed DSH default turn/capture/process, model bridge and native skill mutation/resource/provider/export contracts are exercised using explicit fixtures. No true model generation or content quality claim.'};
  await writeFile(join(config.root,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));process.exit(0);
 }catch(error){console.error(error.stack);process.exit(1);}finally{clearInterval(alive);}},0);return()=>{clearTimeout(timer);clearInterval(alive);};});
}
