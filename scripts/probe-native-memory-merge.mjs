import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {openLocalCore} from '../lib/local-core.js';
import {fixtureEmbedding} from './fixture-embedding.mjs';
const root=await mkdtemp('/private/tmp/dsh-rsi-native-merge-');
const logger={info(){},warn(){},error(){},debug(){}};
const sessionKey='fixture-merge-session',sessionId=sessionKey;
const content='用户通过管理多个社交平台提升线上存在感，但感到疲惫和分心。';
let calls=0,decisionsSeen=0,ids;
const runner={async run(params){
  calls++;
  if(params.taskId==='l1-extraction')return JSON.stringify([{scene_name:'营销',message_ids:['fixture-source'],memories:[content,'用户怀疑多平台营销策略分散了精力，开始重新考虑是否值得。'].map(text=>({content:text,type:'episodic',priority:75,source_message_ids:['fixture-source'],metadata:{}}))}]);
  assert.equal(params.taskId,'l1-conflict-detection');
  ids=[...params.prompt.matchAll(/### 第 \d+ 条新记忆 \(record_id: ([^)]+)\)/g)].map(match=>match[1]);
  assert.equal(ids.length,2);decisionsSeen++;
  // Exercise the native parser/writer behavior observed in the real failed batch.
  return JSON.stringify([{record_id:ids[0],action:'store',target_ids:[]},{record_id:ids[1],action:'merge',target_ids:[ids[0]],merged_content:content+' 用户认为多平台策略分散了精力。',merged_type:'episodic',merged_priority:75,merged_timestamps:[]}]);
}};
let core;
try {
  core=await openLocalCore(root,runner,logger,fixtureEmbedding());
  await core.storeMemory({id:'fixture-existing-candidate',sessionKey,sessionId,content,type:'episodic',priority:75,scene_name:'营销',source_message_ids:['fixture-seed'],metadata:{}});
  const input={sessionKey,sessionId,messages:[{id:'fixture-source',role:'user',content:content+' 请记住我正在重新评估这些营销活动。',timestamp:Date.now()}]};
  const result=await core.extractMemories(input);
  assert.equal(decisionsSeen,1);assert.equal(result.storedCount,2);
  const db=core.memory.getRawDb();
  assert.equal(db.prepare('SELECT record_id FROM l1_records WHERE record_id=?').get(ids[0]),undefined);
  assert.equal(db.prepare('SELECT record_id FROM l1_vec WHERE record_id=?').get(ids[0]),undefined);
  const live=db.prepare('SELECT m.content,m.updated_time,v.updated_time AS vector_updated FROM l1_records m JOIN l1_vec v ON m.record_id=v.record_id WHERE m.record_id=?').get(ids[1]);
  assert.equal(live.content,result.records[1].content);assert.equal(live.updated_time,live.vector_updated);
  assert.equal(db.prepare('SELECT COUNT(*) AS n FROM l1_records').get().n,db.prepare('SELECT COUNT(*) AS n FROM l1_vec').get().n);
  const originalUpsert=core.memory.upsertL1.bind(core.memory);
  core.memory.upsertL1=()=>false;
  await assert.rejects(core.extractMemories(input),/记忆正文与向量写入不一致/);
  core.memory.upsertL1=originalUpsert;
  assert.equal(typeof core.memory.deleteL1Batch(['nonexistent']), 'boolean');
  console.log(JSON.stringify({status:'PASS',realModelRequests:0,fixtureRunnerCalls:calls,checks:['native-same-batch-store-then-merge','intermediate-record-removed-from-native-head-and-vector','live-head-content-and-vector-timestamp-match','failed-upsert-still-rejected','native-delete-return-remains-synchronous-boolean']},null,2));
} finally {core?.close();await rm(root,{recursive:true,force:true});}
