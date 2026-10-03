import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {openLocalCore} from '../lib/local-core.js';
import {createStorageTools} from '../lib/core-entry.js';

const root=await mkdtemp('/private/tmp/dsh-rsi-persona-trigger-');
const calls=[];let l1Calls=0;
const logger={info(){},warn(){},error(){},debug(){}};
const runner={async run(params){
  calls.push(params);
  if(params.taskId==='l1-extraction')return JSON.stringify([{scene_name:l1Calls++?'延续工作区测试':'工作区测试',message_ids:['source-user'],memories:l1Calls===1?[{content:'用户在这个工作区要求先运行目标测试，并保留完整的失败执行日志。',type:'instruction',priority:80,source_message_ids:['source-user'],metadata:{}}]:[]}]);
  const tools=createStorageTools(params.storage,params.storagePrefix ?? '',logger);
  if(params.taskId.startsWith('scene-extract-')){
    await tools.write.execute({path:'工作区测试.md',content:'-----META-START-----\ncreated: 2000-01-01T00:00:00Z\nupdated: 2000-01-01T00:00:00Z\nsummary: 保留测试日志\nheat: 1\n-----META-END-----\n\n用户要求先运行目标测试并保留完整失败日志。'});
    return '已保存场景。';
  }
  if(params.taskId==='persona-generation'){await tools.write.execute({path:'persona.md',content:'用户在工作区测试时重视目标测试和完整失败日志。'});return '已保存画像。';}
  throw Error('Unexpected fixture task '+params.taskId);
}};
const core=await openLocalCore(join(root,'assets'),runner,logger);
try {
  assert.equal(await core.generatePersona(),false);assert.equal(calls.length,0);
  const rawMessages=[{id:'source-user',role:'user',content:'在这个工作区先运行目标测试，失败时保留完整日志用于排查。',timestamp:Date.now()},{id:'source-assistant',role:'assistant',content:'会记录目标测试的执行结果，失败时不将任务描述为已经成功。',timestamp:Date.now()+1}];
  const source={sessionKey:'fixture-source',sessionId:'fixture-source',rawMessages};
  const captured=await core.record(source);assert.equal(captured.length,2);assert.equal((await core.record(source)).length,0);assert.equal((await core.checkpoint.read()).total_processed,2);
  const first=await core.extractMemories({messages:captured,sessionKey:'fixture-source',sessionId:'fixture-source'});assert.equal(first.storedCount,1);assert.equal((await core.checkpoint.read()).memories_since_last_persona,1);
  await core.extractMemories({messages:captured,sessionKey:'fixture-source',sessionId:'fixture-source'});
  assert.ok(calls.filter(p=>p.taskId==='l1-extraction')[1].prompt.includes('【上一个情境】：工作区测试'));
  const scene=await core.extractScenes('');assert.equal(scene.skipped,false);assert.equal((await core.checkpoint.read()).scenes_processed,1);assert.equal((await core.layerCounts()).L3,0);
  assert.ok((await core.personaTrigger.shouldGenerate()).reason.includes('冷启动'));
  assert.equal(await core.generatePersona(),true);assert.equal((await core.layerCounts()).L3,1);assert.equal((await core.checkpoint.read()).memories_since_last_persona,0);
  const before=calls.length;assert.equal(await core.generatePersona(),false);assert.equal(calls.length,before);
  assert.equal(await core.generatePersona(true),false);assert.equal(calls.length,before,'Native no-change guard must also survive manual force');
  await core.checkpoint.incrementScenesProcessed();await core.checkpoint.markL1ExtractionComplete('fixture-source',49);assert.equal((await core.personaTrigger.shouldGenerate()).should,false);
  await core.checkpoint.markL1ExtractionComplete('fixture-source',1);assert.ok((await core.personaTrigger.shouldGenerate()).reason.includes('阈值'));
  await core.checkpoint.setPersonaUpdateRequest('明确请求更新');assert.ok((await core.personaTrigger.shouldGenerate()).reason.includes('主动请求'));await core.checkpoint.clearPersonaRequest();
  await core.profile.unlink('persona.md');assert.ok((await core.personaTrigger.shouldGenerate()).reason.includes('恢复'));assert.equal(await core.generatePersona(),true);
  console.log(JSON.stringify({status:'PASS',checkedAt:new Date().toISOString(),realModelRequests:0,fixtureRunnerCalls:calls.length,checks:['empty-profile-no-dispatch','native-L0-capture-cursor-and-count','native-L1-count','previous-scene-continuity','native-L2-count','navigation-only-is-not-L3','native-cold-start','native-no-trigger-no-dispatch','native-no-change-no-dispatch','native-threshold-50','native-explicit-request','native-missing-persona-recovery']},null,2));
}finally{core.close();await rm(root,{recursive:true,force:true});}
