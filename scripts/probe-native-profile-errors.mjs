import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {openLocalCore} from '../lib/local-core.js';
import {fixtureEmbedding} from './fixture-embedding.mjs';
const output=process.argv[2];assert.ok(output);
const root=await mkdtemp('/private/tmp/dsh-rsi-profile-errors-'),logger={info(){},warn(){},error(){},debug(){}};
const errors={persona:Object.assign(new Error('FIXTURE_PROFILE_QUOTA'),{code:'BUDGET_EXHAUSTED'}),scene:Object.assign(new Error('FIXTURE_SCENE_ABORT'),{code:'ABORTED'})};
let calls=0,mode='failure';const captured=[];
const runner={run:async(params)=>{calls++;captured.push(params);await new Promise(r=>setTimeout(r,params.taskId==='persona-generation'?8:2));if(mode==='success'){await params.storage.writeFile('persona.md','# 新画像\n本次为夹具写入。');return 'Saved.';}throw params.taskId==='persona-generation'?errors.persona:errors.scene;}};
const core=await openLocalCore(join(root,'assets'),runner,logger,fixtureEmbedding());
try{
 const date=new Date().toISOString();
 await core.profile.writeFile('.metadata/scene_index.json',JSON.stringify([{filename:'fixture.md',summary:'隔离场景',heat:1,created:date,updated:date}]));
 await core.profile.writeFile('scene_blocks/fixture.md','# 隔离场景\n原文明确事件日期 2024-03-01；另一次提到下周但原始消息时间未知。');
 const existing='# 已有画像\n预算失败不可被它遮蔽。';await core.profile.writeFile('persona.md',existing);
 await core.storeMemory({id:'fixture-profile-source',sessionKey:'fixture',sessionId:'fixture',content:'已有画像的更新失败必须保留原始错误。原文明确事件日期 2024-03-01；下周没有原始消息时间锚点。',type:'episodic',priority:70,scene_name:'隔离场景',source_message_ids:['fixture-source'],metadata:{}});
 const before=await core.checkpoint.read();
 // Same physical core, concurrent L2/L3: the two captured errors must not cross operations.
 await Promise.all([assert.rejects(core.generatePersona(true),e=>e===errors.persona),assert.rejects(core.extractScenes(''),e=>e===errors.scene)]);
 assert.equal(await core.profile.readFile('persona.md'),existing);assert.deepEqual(await core.checkpoint.read(),before);assert.equal(calls,2);
 // A genuinely unchanged native profile is false, not a failure or a new dispatch.
 await core.profile.writeFile('.metadata/scene_index.json',JSON.stringify([{filename:'missing.md',summary:'missing',heat:1,created:date,updated:date}]));
 assert.equal(await core.generatePersona(true),false);assert.equal(calls,2);
 await core.profile.writeFile('.metadata/scene_index.json',JSON.stringify([{filename:'fixture.md',summary:'隔离场景',heat:1,created:date,updated:date}]));
 await core.profile.unlink('persona.md');
 await assert.rejects(core.generatePersona(true),e=>e===errors.persona);assert.deepEqual(await core.checkpoint.read(),before);
 mode='success';assert.equal(await core.generatePersona(true),true);assert.ok((await core.profile.readFile('persona.md')).includes('新画像'));assert.notDeepEqual(await core.checkpoint.read(),before);
 const timeInputs=captured.map(params=>{
  const marker='Profile source-time provenance:',offset=params.systemPrompt.lastIndexOf(marker);assert.ok(offset>500);assert.equal(params.systemPrompt.indexOf(marker),offset);assert.ok(params.systemPrompt.includes('do not erase explicit source-supported event dates'));assert.ok(params.prompt.includes('2024-03-01'));assert.ok(params.prompt.includes('下周'));const factualMarker='Profile factual provenance:';assert.ok(params.systemPrompt.indexOf(factualMarker)>offset);assert.equal(params.systemPrompt.indexOf(factualMarker),params.systemPrompt.lastIndexOf(factualMarker));
  return {taskId:params.taskId,nativeSystemPrefixChars:offset,nativeSystemPrefixSha256:createHash('sha256').update(params.systemPrompt.slice(0,offset-1)).digest('hex'),timeGuidanceAppended:true,factualGuidanceAppended:true,explicitSourceDateRetained:true,unanchoredRelativeTimeRetained:true};
 });
 const receipt={status:'PASS_NATIVE_PROFILE_ERROR_CONTROLS',checkedAt:new Date().toISOString(),realModelRequests:0,fixtureRunnerCalls:calls,timeInputs,sourceSha256:createHash('sha256').update(await readFile(new URL('../src/local-core.ts',import.meta.url))).digest('hex'),checks:['existing-persona-preserves-original-budget-error-object','concurrent-L2-preserves-original-abort-error-object','failed-operations-do-not-advance-checkpoint','genuine-native-no-change-remains-false-without-dispatch','first-persona-failure-preserves-original-error','successful-native-generation-still-updates-checkpoint','native-L2-and-L3-time-guidance-appended-after-original-prefix','supplied-explicit-event-date-and-relative-wording-preserved','native-implicit-insights-remain-tentative-host-guidance-delivered'],limits:['Fixture runner proves actual native runner inputs and errors; it does not prove real generated date quality or storage rollback.','Frozen old experiment and old closed-failure policy unchanged.']};
 await writeFile(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{core.close();await rm(root,{recursive:true,force:true});}
