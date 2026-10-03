import assert from 'node:assert/strict';
import { mkdir,writeFile,readFile,access } from 'node:fs/promises';
import { join } from 'node:path';
import { LlmAdapter,createUserMessage } from '@deepseek-ai/dsh-llm';
import { Session } from '@deepseek-ai/dsh-session';
import {checkClientRpc} from './client-rpc-probe.mjs';
export const name='dsh-rsi-runtime-probe';
export const inject=['rsi','llm','agents','skills','sessions','sessionPersistence','typertGateway'];
const content='---\nname: testing\ndescription: 工作区目标测试流程\n---\n\n先运行目标测试；失败时保留完整日志。';
export function apply(ctx,config) {
  const requests=[],background=[],foreground=[];
  class Fixture extends LlmAdapter {
    async *stream(options) {
      const {signal,...request}=options; requests.push(structuredClone(request));
      const reply=(options.sessionId.startsWith('rsi-')?background:foreground).shift();assert.ok(reply,`Unplanned request ${options.sessionId}: ${JSON.stringify(options.messages).slice(0,600)}`);
      const block=reply.call?{type:'tool-call',...reply.call}:{type:'text',text:reply.text};
      yield {type:'block-start',index:0,blockType:block.type};yield {type:'block-end',index:0,block};yield {type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};yield {type:'finish',reason:{kind:reply.call?'tool-calls':'stop'}};
    }
  }
  ctx.effect(() => ctx.llm.registerAdapter(['rsi-probe'],new Fixture()));
  ctx.effect(() => {
    const alive=setInterval(() => {},1000);
    const timer=setTimeout(async () => {try {
      await ctx.rsi.ready;const cwd=join(config.root,'workspace-a'),other=join(config.root,'workspace-b');await mkdir(cwd,{recursive:true});await mkdir(other,{recursive:true});
      const clientRpc=await checkClientRpc(ctx,cwd);
      const state=()=>ctx.typertGateway.invoke({namespace:'rsi',method:'request',args:{operation:'snapshot',payload:{cwd}}});
      if (config.phase==='restore') { const result=await state();assert.equal(result.skills.find(s=>s.name==='testing').version,4);assert.equal(result.memory.length,1);assert.equal(result.jobs[0].status,'completed');assert.equal(result.jobs.find(j=>j.sourceSessionId==='probe-consumer').status,'interrupted');assert.equal((await ctx.skills.get('rsi-testing',{cwd})).content.includes('preserve complete failure logs'),true);assert.equal(requests.length,0);await writeFile(join(config.root,'restored.json'),JSON.stringify({status:'PASS',memory:1,skillVersions:4,requests:0}));process.exit(0); }
      foreground.push({text:'任务已完成，目标测试通过。'});
      background.push({text:JSON.stringify([{scene_name:'测试流程',message_ids:['source'],memories:[{content:'本工作区的测试流程需要保留完整日志。',type:'instruction',priority:70,source_message_ids:['source'],metadata:{}}]}])},{call:{id:'create',name:'skill_create',arguments:JSON.stringify({name:'testing',content})}},{text:'已保存技能。'});
      const source=await ctx.agents.create({sessionId:'probe-source',meta:{cwd},agentOptions:{provider:'rsi-probe',model:'fixture'}});
      source.agent.followup(createUserMessage({content:[{type:'text',text:'在本工作区遵循测试流程：先运行目标测试，失败时保留完整日志。'}],source:{kind:'user'}}));await source.agent.whenIdle();await ctx.sessions.flush(source.agent.session);
      let snapshot;for(let i=0;i<100;i++){snapshot=await state();if(snapshot.jobs[0]?.status==='completed') break;await new Promise(r=>setTimeout(r,20));}
      assert.equal(snapshot.jobs[0]?.status,'completed',JSON.stringify(snapshot.jobs));assert.equal(snapshot.memory.length,1);assert.equal(snapshot.skills.length,1);
      const skill=snapshot.skills[0];assert.equal((await ctx.skills.get('rsi-testing',{cwd})).content.includes('保留完整日志'),true);assert.equal((await ctx.skills.list({cwd:other})).some(s=>s.provider==='dsh-rsi'),false);
      const native=await ctx.rsi.runtime.core(snapshot.workspace.id);
      background.push({call:{id:'scene',name:'write',arguments:JSON.stringify({path:'测试流程.md',content:'-----META-START-----\ncreated: 2026-10-02T00:00:00Z\nupdated: 2026-10-02T00:00:00Z\nsummary: 保留完整日志\nheat: 1\n-----META-END-----\n\n测试流程要求保留完整日志。'})}},{text:'已写入场景。'},{call:{id:'persona',name:'write',arguments:JSON.stringify({path:'persona.md',content:'用户在本工作区重视完整的测试失败日志。'})}},{text:'已保存画像。'});
      const scene=await native.extractScenes('');assert.equal(scene.skipped,false);await native.generatePersona();assert.ok((await native.profile.readFile('persona.md')).includes('完整'));assert.ok((await ctx.rsi.runtime.recall(cwd,'测试流程')).text.includes('重视完整'),JSON.stringify({r:await native.recall('测试流程'),state:await ctx.rsi.runtime.recall(cwd,'测试流程')}));assert.equal((await ctx.rsi.runtime.recall(other,'测试流程')).text,'');
      const layerSnapshot=await state();assert.deepEqual(layerSnapshot.layers[snapshot.workspace.id],{L0:2,L1:1,L2:1,L3:1});
      for(const layer of ['L0','L1','L2','L3']){const response=await ctx.typertGateway.invoke({namespace:'rsi',method:'request',args:{operation:'memoryLayer',payload:{cwd,layer}}});assert.equal(response.total,layer==='L0'?2:1);assert.ok(response.items.length);if(layer==='L2')assert.equal(response.items[0].content.includes('META-START'),false);}
      await assert.rejects(ctx.rsi.request('memoryLayer',{cwd,layer:'invalid'}));
      await ctx.rsi.request('settings',{cwd,settings:{learningEnabled:false}});
      foreground.push({call:{id:'load',name:'skill',arguments:JSON.stringify({name:'rsi-testing'})}},{text:'按技能执行。'});
      const consumer=await ctx.agents.create({sessionId:'probe-consumer',meta:{cwd},agentOptions:{provider:'rsi-probe',model:'fixture'}});consumer.agent.followup(createUserMessage({content:[{type:'text',text:'请用 rsi-testing 处理这个工作区的测试流程。'}],source:{kind:'user'}}));await consumer.agent.whenIdle();await ctx.sessions.flush(consumer.agent.session);
      const sent=requests.filter(r=>r.sessionId==='probe-consumer');assert.equal(sent.length,2);assert.ok(JSON.stringify(sent[0].messages).includes(snapshot.memory[0].content),JSON.stringify({sent:sent[0].messages,recall:await ctx.rsi.runtime.recall(cwd,'测试流程')}));assert.ok(JSON.stringify(sent[1].messages).includes('先运行目标测试；失败时保留完整日志。'));
      const injected=sent[0].messages.find(m=>m.source?.kind==='dsh-rsi'&&m.source?.form==='memory');assert.ok(injected.source.refs.some(ref=>ref.scope===snapshot.workspace.id&&ref.memories.some(m=>m.id===snapshot.memory[0].id&&m.version===snapshot.memory[0].version&&m.content===snapshot.memory[0].content)),'Missing stored memory identity in actual request');
      const handle=await ctx.sessionPersistence.open('probe-consumer','read');const stored=await handle.read();const header=stored.events.filter(e=>e.type==='request/header')[0];const restored=Session.fromRestore(handle.id,stored.events.slice(0,header.seq+1),handle.header,handle.inheritedEventCount,stored.eventState);assert.deepEqual([...restored.deriveMessages()],sent[0].messages);await handle.close();
      await ctx.rsi.request('disable',{cwd,id:skill.skill_id,disabled:true});assert.equal(await ctx.skills.get('rsi-testing',{cwd}),undefined);await ctx.rsi.request('disable',{cwd,id:skill.skill_id,disabled:false});
      const core=await ctx.rsi.runtime.core(snapshot.workspace.id);await ctx.rsi.request('editSkill',{cwd,id:skill.skill_id,expectedVersion:1,content:content.replace('保留完整日志','只写摘要')});await assert.rejects(ctx.rsi.request('editSkill',{cwd,id:skill.skill_id,expectedVersion:1,content}));
      await ctx.rsi.request('rollback',{cwd,id:skill.skill_id,version:1});assert.equal((await ctx.skills.get('rsi-testing',{cwd})).metadata.version,3);
      const before=requests.length;await ctx.rsi.request('settings',{cwd,settings:{dailyCallBudget:7,learningEnabled:true}});await ctx.rsi.request('learn',{cwd});assert.equal(requests.length,before);const budget=await state();assert.equal(budget.jobs.find(j=>j.sourceSessionId==='probe-consumer').status,'paused');assert.equal(budget.usage.calls,7);
      const edited=await ctx.rsi.request('editMemory',{cwd,id:snapshot.memory[0].id,content:'本工作区测试流程应输出完整失败日志并先验证环境。'});assert.equal(edited.memory.length,1);assert.equal(edited.memory[0].content.includes('先验证环境'),true);assert.ok(edited.profilePending);
      const importedRoot=join(config.root,'original');await mkdir(importedRoot,{recursive:true});await writeFile(join(importedRoot,'data.bin'),Buffer.from([0,255,128,65]));
      ctx.skills.registerProvider(()=>({name:'probe-original',list:()=>[{name:'original',description:'已有资源技能',invocation:{modelInvocable:true,userInvocable:true},provider:'probe-original',source:'probe-original',rank:10,locator:{name:'original'},resourceBase:{kind:'directory',path:importedRoot}}],get:candidate=>({...candidate,content:'读取 data.bin 的二进制内容。'})}));
      await ctx.rsi.request('importSkill',{cwd,name:'original'});const managed=(await state()).skills.find(s=>s.name==='original');assert.equal((await readFile(join(importedRoot,'data.bin'))).toString('hex'),'00ff8041');
      const preview=await ctx.rsi.request('skillFile',{cwd,id:managed.skill_id,path:'data.bin'});assert.equal(preview.encoding,'base64');assert.equal(Buffer.from(preview.content,'base64').toString('hex'),'00ff8041');await assert.rejects(ctx.rsi.request('skillFile',{cwd,id:managed.skill_id,path:'../outside'}));
      const exported=await ctx.rsi.request('export',{cwd});const attachment=exported.skills.find(s=>s.head.name==='original').versions[0].resources[0];assert.equal(Buffer.from(attachment.content,'base64').toString('hex'),'00ff8041');
      await ctx.rsi.request('promote',{cwd,id:managed.skill_id});assert.ok(await ctx.skills.get('rsi-original',{cwd:other}));
      await ctx.rsi.request('settings',{cwd,settings:{learningEnabled:false}});await ctx.rsi.request('clear',{cwd,scope:'global',confirm:'global'});assert.equal(await ctx.skills.get('rsi-original',{cwd:other}),undefined);assert.ok(await ctx.skills.get('rsi-original',{cwd}));
      await assert.rejects(ctx.rsi.runtime.readProfile(other,join(native.profileDir,'scene_blocks','测试流程.md')));assert.equal((await readFile(join(importedRoot,'data.bin'))).toString('hex'),'00ff8041');
      await ctx.rsi.request('settings',{cwd,settings:{dailyCallBudget:100,learningEnabled:false}});
      background.push({text:content.replace('工作区目标测试流程','Workspace test workflow').replace('先运行目标测试；失败时保留完整日志。','Run focused tests first; preserve complete failure logs.')},{text:'Verify the environment before running focused tests; preserve complete failure logs.'});
      await ctx.rsi.request('convertSkill',{cwd,id:skill.skill_id,language:'en'});assert.equal((await ctx.skills.get('rsi-testing',{cwd})).metadata.version,4);assert.ok((await ctx.skills.get('rsi-testing',{cwd})).content.includes('preserve complete failure logs'));
      await ctx.rsi.request('convertMemory',{cwd,id:edited.memory[0].id,language:'en'});assert.ok((await state()).memory[0].content.startsWith('Verify the environment'));
      const conversion=requests.at(-1);assert.ok(JSON.stringify(conversion.messages).includes('en'));assert.equal((await state()).settings.learningEnabled,false);
      assert.throws(()=>new ctx.rsi.runtime.constructor(ctx,{},ctx.rsi.runtime.directory),/另一个插件实例/);
      const paused=ctx.rsi.runtime.state.jobs().find(j=>j.session==='probe-consumer');ctx.rsi.runtime.state.updateJob(paused.id,'running');
      const result={status:'PASS',clientRpc,fixtureDispatches:requests.length,realProviderRequests:0,taskCommandsExecuted:0,memory:1,skillVersions:4,checks:['native-gateway-management-RPC','management-L0-L3-native-reads','skill-edit-version-conflict','resource-preview-binary-and-path-isolation','official-client-RPC-contribution-mount','real-agent-turn-capture','native-L1-and-skill-extractor','native-L2-scene-and-L3-persona-tools','next-task-memory-injection','native-skill-tool-load','durable-injection-reconstruction','workspace-isolation','disable-provider','version-rollback','daily-budget-no-dispatch','memory-correction','import-managed-copy-with-binary-resources','export-version-resources','promote-global-provider','clear-scope-assets','profile-path-isolation','asset-language-conversion-preserves-history','single-owner-store-lock'],limitation:'Fixture integration; no model-quality benchmark, task commands or container isolation validated.'};await writeFile(join(config.root,'result.json'),JSON.stringify(result));console.log(JSON.stringify(result));process.exit(0);
    }catch(error){console.error(error.stack);process.exit(1);}},0);return()=>{clearInterval(alive);clearTimeout(timer);};
  });
}
