import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile,writeFile} from 'node:fs/promises';
import {join,resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {LocalEmbeddingService,buildFtsQuery} from '../lib/core-entry.js';
import {openLocalCore} from '../lib/local-core.js';
import {fileURLToPath} from 'node:url';
const root=await mkdtemp('/private/tmp/dsh-rsi-real-native-embedding-'),logs=[];
const logger={info(m){logs.push(m);},warn(m){logs.push(m);},error(m){logs.push(m);},debug(m){logs.push(m);}};
const modelPath=resolve(process.argv[2] ?? fileURLToPath(new URL('../.artifacts/models/embeddinggemma-300m-qat-Q8_0.gguf',import.meta.url)));
const modelSha256=createHash('sha256').update(await readFile(modelPath)).digest('hex');
assert.equal(modelSha256,'6fa0c02a9c302be6f977521d399b4de3a46310a4f2621ee0063747881b673f67','Probe requires the pinned native model');
const service=new LocalEmbeddingService({provider:'local',modelPath},logger);
let core;
try {
  const started=Date.now();service.startWarmup();await service.waitForReady();assert.equal(service.isReady(),true,logs.join('\n'));
  core=await openLocalCore(join(root,'assets'),{run:async()=>{throw Error('Chat model dispatch forbidden');}},logger,service);
  const vector=await core.embeddingService.embed('Verify the Python environment before running focused tests.');assert.equal(vector.length,768);
  const norm=Math.sqrt(Array.from(vector).reduce((sum,value)=>sum+value*value,0));assert.ok(Math.abs(norm-1)<1e-5);
  const records=[
    {id:'python-environment',content:'Before testing Python changes, verify dependency installation and interpreter version.'},
    {id:'npm-release',content:'Publish the npm package after choosing the version and checking the release manifest.'},
  ];
  for(const row of records)await core.storeMemory({...row,sessionKey:'isolated-fixture',sessionId:'isolated-fixture',type:'instruction',priority:70,scene_name:'development',source_message_ids:['fixture-source'],metadata:{}});
  await core.record({sessionKey:'isolated-fixture',sessionId:'isolated-fixture',rawMessages:[{id:'fixture-source',role:'user',content:'Check the development environment before running checks.',timestamp:Date.now()}]});
  const query='如何检查解释器环境';const fts=core.memory.searchL1Fts(buildFtsQuery(query),8);assert.equal(fts.length,0);
  const queryVector=await core.embeddingService.embed(query);const ranked=core.memory.searchL1Vector(queryVector,8);
  const recalled=await core.recall(query);assert.equal(recalled.recallStrategy,'hybrid');assert.ok(recalled.recalledL1Memories.length>0);assert.ok(recalled.prependContext.includes('interpreter version'));
  const db=core.memory.getRawDb();assert.equal(Number(db.prepare('SELECT COUNT(*) AS count FROM l1_vec').get().count),2);assert.equal(Number(db.prepare('SELECT COUNT(*) AS count FROM l0_vec').get().count),1);
  await core.editMemory('python-environment','Before testing Python changes, verify installed dependencies and record the interpreter version.');
  const metrics=(await readFile(join(root,'assets/diagnostics/embedding.log'),'utf8')).trim().split('\n').map(line=>JSON.parse(line.slice(line.indexOf(' {')+1)));
  const result={status:'PASS',checkedAt:new Date().toISOString(),method:'Native LocalEmbeddingService + native sqlite-vec + native hybrid/RRF in temporary assets; no chat calls or task execution.',chatModelRequests:0,embeddingProvider:'local',modelRepoRevision:'66f974f8cd48cc3b9c41c516b95508e75b4bee64',modelSha256,dimensions:vector.length,norm,keywordHits:fts.length,vectorRanking:ranked.map(row=>({id:row.record_id,score:row.score})),recallStrategy:recalled.recallStrategy,embeddingCalls:metrics.length,embeddingInputChars:metrics.reduce((sum,row)=>sum+row.input_chars,0),tokenUsage:null,durationMs:Date.now()-started,coreBundleSha256:createHash('sha256').update(await readFile(new URL('../lib/local-core.js',import.meta.url))).digest('hex'),checks:['real-native-model-loaded','real-768-dimensional-normalized-embedding','native-L0-and-L1-vector-writes','real-vector-query-with-zero-FTS-hits','native-hybrid-RRF-recall','native-edit-updates-vector'],limitation:'Small integration probe only; not an effect benchmark. Local native input cap remains 512 characters and token usage is unavailable.'};
  if(process.argv[3])await writeFile(process.argv[3],JSON.stringify(result,null,2)+'\n');console.log(JSON.stringify(result,null,2));
}finally{core?.close();service.close();await rm(root,{recursive:true,force:true});}
