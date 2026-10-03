import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {join} from 'node:path';
import {openLocalCore} from '../lib/local-core.js';
import {VectorStore,writeMemory,buildFtsQuery} from '../lib/core-entry.js';
import {fixtureEmbedding} from './fixture-embedding.mjs';
const root=await mkdtemp('/private/tmp/dsh-rsi-native-vectors-'),logs=[],logger={info(message){logs.push(message);},warn(message){logs.push(message);},error(message){logs.push(message);},debug(message){logs.push(message);}};
const runner={run:async params=>{if(params.taskId==='l1-extraction')return JSON.stringify([{scene_name:'验证',message_ids:['fixture-source'],memories:[{content:'遇到失败时先检查测试环境，并保留执行日志。',type:'instruction',priority:70,source_message_ids:['fixture-source'],metadata:{}}]}]);throw Error('Unexpected fixture runner task');}};
let core;
try {
  const legacy=new VectorStore(join(root,'memory.sqlite'),0,logger);legacy.init();
  const record={id:'legacy-memory',sessionKey:'legacy-session',sessionId:'legacy-session',content:'这是需要补建向量的历史记忆。',type:'instruction',priority:70,scene_name:'验证',source_message_ids:['legacy-source'],metadata:{}};
  await writeMemory({memory:record,decision:{record_id:record.id,action:'store',target_ids:[]},baseDir:join(root,'history'),sessionKey:record.sessionKey,sessionId:record.sessionId,vectorStore:legacy,logger});
  assert.ok(legacy.upsertL0({id:'legacy-source',sessionKey:'legacy-session',sessionId:'legacy-session',role:'user',messageText:'历史会话也要重建向量。',recordedAt:new Date().toISOString(),timestamp:Date.now()},undefined));legacy.close();
  const embedding=fixtureEmbedding();core=await openLocalCore(root,runner,logger,embedding);
  const db=core.memory.getRawDb(),count=table=>Number(db.prepare(`SELECT COUNT(*) AS count FROM ${table}`).get().count);
  assert.equal(core.memory.getEmbeddingDimensions(),768);assert.equal(core.memory.isDegraded(),false);assert.equal(count('l1_vec'),1);assert.equal(count('l0_vec'),1);
  const source={sessionKey:'new-session',sessionId:'new-session',rawMessages:[{id:'fixture-source',role:'user',content:'遇到失败时请保留日志。',timestamp:Date.now()}]};await core.record(source);assert.equal(count('l0_vec'),2);
  const extract=await core.extractMemories({messages:source.rawMessages,sessionKey:source.sessionKey,sessionId:source.sessionId});assert.equal(extract.storedCount,1);assert.equal(count('l1_vec'),2);
  const saved=extract.records[0];await core.editMemory(saved.id,'先确认测试环境，再保留执行日志。');assert.equal(count('l1_vec'),2);assert.ok((await core.readMemories()).find(row=>row.id===saved.id).content.includes('确认测试环境'));
  const recalled=await core.recall('测试环境 日志');assert.equal(recalled.recallStrategy,'hybrid');assert.ok(recalled.prependContext.includes('测试环境'));assert.ok(logs.some(message=>message.includes('hybrid-keyword-fts')));assert.ok(logs.some(message=>message.includes('hybrid-embedding')&&message.includes('Got')));
  // A controlled vector-only query proves the native vector path participates, not model quality.
  const vectorOnly='ZZ_NO_LEXICAL_MATCH_92817';assert.equal(core.memory.searchL1Fts(buildFtsQuery(vectorOnly),8).length,0);
  const vectorRecall=await core.recall(vectorOnly);assert.equal(vectorRecall.recallStrategy,'hybrid');assert.ok(vectorRecall.recalledL1Memories.length>0);
  const originalEmbed=embedding.embed;embedding.embed=async()=>{throw new Error('EMBEDDING_FIXTURE_FAILURE');};
  await assert.rejects(core.recall('测试环境'),/EMBEDDING_FIXTURE_FAILURE/);
  await assert.rejects(core.storeMemory({...record,id:'partial-write',content:'故障时不能将缺失向量记为成功。'}),/EMBEDDING_FIXTURE_FAILURE/);
  embedding.embed=originalEmbed;await core.recall('故障');assert.equal(count('l1_vec'),count('l1_records'));
  const upsert=core.memory.upsertL1.bind(core.memory);core.memory.upsertL1=()=>false;
  await assert.rejects(core.storeMemory({...record,id:'index-failure',content:'写入失败不得报告成功。'}),/向量写入不一致/);core.memory.upsertL1=upsert;
  embedding.embed=async()=>new Float32Array(2);await assert.rejects(core.recall('测试环境'),/维度或数值无效/);embedding.embed=originalEmbed;
  const lines=(await readFile(join(root,'diagnostics/embedding.log'),'utf8')).trim().split('\n');const metrics=lines.map(line=>JSON.parse(line.slice(line.indexOf(' {')+1)));assert.ok(metrics.some(row=>row.status==='failed'));assert.ok(metrics.every(row=>row.token_usage===null));
  console.log(JSON.stringify({status:'PASS',checkedAt:new Date().toISOString(),embedding:'Explicit deterministic test double; no semantic/model-quality claim',realModelRequests:0,dimensions:768,legacyReindexed:{L0:1,L1:1},finalVectors:{L0:count('l0_vec'),L1:count('l1_vec')},embeddingCalls:metrics.length,checks:['real-sqlite-vec-extension','native-legacy-reindex-L0-and-L1','L0-write-vector','native-L1-dedup-and-write-vector','edit-updates-vector','native-FTS-plus-vector-RRF','vector-only-query-with-zero-keyword-hits','embedding-error-does-not-silently-fallback','partial-index-recovered-by-native-reindex','index-write-failure-not-success','invalid-output-rejected','embedding-cost-count-chars-time-and-unknown-token']},null,2));
}finally{core?.close();await rm(root,{recursive:true,force:true});}
