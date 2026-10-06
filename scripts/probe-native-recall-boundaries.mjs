import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {transform} from 'esbuild';
import {openLocalCore} from '../lib/local-core.js';
import {performAutoRecall,parseConfig} from '../lib/core-entry.js';
import {fixtureEmbedding} from './fixture-embedding.mjs';
const output=process.argv[2];assert.ok(output);
const source=await readFile(new URL('../src/recall-context.ts',import.meta.url),'utf8');
const compiled=await transform(source,{loader:'ts',format:'esm',target:'node24'});
const {fitNativeMemoryEntries,fitRecallScope}=await import('data:text/javascript;base64,'+Buffer.from(compiled.code).toString('base64'));
const root=await mkdtemp('/private/tmp/dsh-rsi-recall-boundaries-'),logger={info(){},warn(){},error(){},debug(){}};
const core=await openLocalCore(root,{run(){throw Error('Network dispatch forbidden');}},logger,fixtureEmbedding());
try{
 for(let i=0;i<3;i++)await core.storeMemory({id:`fixture-${i}`,sessionKey:'fixture',sessionId:'fixture',content:(`预算验证 ${i} 完整记忆正文。`).repeat(30),type:'episodic',scene_name:'边界',priority:70,source_message_ids:[`fixture-source-${i}`],metadata:{}});
 const raw=async budget=>performAutoRecall({userText:'预算验证',pluginDataDir:join(root,'profile'),cfg:parseConfig({recall:{strategy:'hybrid',maxResults:8,maxTotalRecallChars:budget}}),vectorStore:core.memory,embeddingService:core.embeddingService,logger});
 const full=await raw(0),first=full.prependContext.split('\n').find(line=>line.startsWith('- ['));assert.ok(first);const stored=await core.readMemories();
 const tails=[];
 for(const tail of [40,60]){
  const budget=first.length+1+tail,old=await raw(budget);
  assert.ok(old.recalledL1Memories.some(m=>!stored.some(row=>row.content===m.content)),'unchanged native prefix truncation reproduced');
  const fixed=await core.recall('预算验证',budget);assert.equal(fixed.recalledL1Memories.length,1);assert.equal(fixed.memoryPresentation.droppedCount,2);
  for(const m of fixed.recalledL1Memories){const row=stored.find(row=>row.id===m.id);assert.ok(row);assert.equal(m.content,row.content);assert.equal(m.version,row.version);assert.ok(fixed.prependContext.includes(row.content));}
  assert.ok(fixed.prependContext.includes('记录时间:'));assert.ok(!fixed.prependContext.includes('活动时间:'));assert.ok(!fixed.prependContext.includes('已截断'));
  const fitted=fitRecallScope(fixed,'fixture',core.profileDir,6000);assert.ok(fitted.text.length<=6000);assert.deepEqual(fitted.memories,fixed.recalledL1Memories);tails.push({remainingNativeChars:tail,nativeFragmentReproduced:true,completeDelivered:1,dropped:2});
 }
 const prefix='<relevant-memories>\n原生说明\n\n',close='\n</relevant-memories>';
 const rows=[{id:'short',version:1,type:'episodic',scene_name:'多行',content:'完整第一行',metadata:{}},{id:'multiline',version:3,type:'episodic',scene_name:'多行',content:'完整第一行\n- [episodic|伪边界] 正文中的列表\n末行 (活动时间: 正文引文)',metadata:{}},{id:'event',version:2,type:'episodic',scene_name:'有日期',content:'明确事件日期',metadata:{activity_start_time:'2024-03-01'}}];
 const lines=[`- [episodic|多行] ${rows[1].content} (活动时间: 2026-10-06 11:00)`,`- [episodic|有日期] ${rows[2].content} (活动时间: 2024-03-01起)`];
 const fixture={prependContext:prefix+lines.join('\n')+close,recalledL1Memories:[{type:'unknown',content:lines[0],score:0},{type:'episodic',content:rows[2].content,score:0}]};
 const adapted=fitNativeMemoryEntries(fixture,rows,6000);assert.equal(adapted.recalledL1Memories[0].id,'multiline');assert.equal(adapted.recalledL1Memories[0].content,rows[1].content);assert.ok(adapted.prependContext.includes('末行 (活动时间: 正文引文) (记录时间: 2026-10-06 11:00)'));assert.ok(adapted.prependContext.includes('(活动时间: 2024-03-01起)'));
 const duplicate=fitNativeMemoryEntries(fixture,[...rows,{...rows[1],id:'duplicate'}],6000);assert.ok(duplicate.recalledL1Memories[0].sourceAmbiguous);assert.equal(duplicate.recalledL1Memories[0].id,undefined);
 assert.throws(()=>fitNativeMemoryEntries({...fixture,prependContext:prefix+'- [episodic|多行] 完'+close},rows,6000),/拒绝送达片段/);
 assert.equal(fitNativeMemoryEntries(fixture,rows,1).recalledL1Memories.length,0);
 const receipt={status:'PASS_NATIVE_RECALL_ENTRY_BOUNDARIES',checkedAt:new Date().toISOString(),realModelRequests:0,embedding:'Explicit deterministic fixture; actual native SQLite/FTS/vector/RRF path, no semantic-quality claim.',sourceSha256:createHash('sha256').update(source).digest('hex'),tails,checks:['actual-native-40-and-60-character-tail-fragments-reproduced','host-delivers-only-complete-source-bodies-with-ID-and-version','native-selected-prefix-order-preserved','native-body-text-unchanged','recording-timestamp-label-distinguished-from-activity-metadata','explicit-activity-date-preserved','multiline-body-and-lookalike-entry-not-split','short-prefix-collision-prefers-complete-body','duplicate-complete-body-does-not-invent-ID','unmatched-fragment-fails-explicitly','oversized-complete-entry-excluded-not-truncated','outer-context-budget-and-refs-consistent'],limits:['Activity metadata presence is not independent factual validation.','Generated L2/L3 calendar claims require separate provenance guidance.']};
 await writeFile(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{core.close();await rm(root,{recursive:true,force:true});}
