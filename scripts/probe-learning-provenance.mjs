import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {openLocalCore} from '../lib/local-core.js';
import {SKILL_REVIEW_PROMPT} from '../lib/core-entry.js';
import {fixtureEmbedding} from './fixture-embedding.mjs';
const output=process.argv[2];assert.ok(output,'New receipt path required');
const root=await mkdtemp('/private/tmp/dsh-rsi-learning-provenance-'),calls=[];
const logger={info(){},warn(){},error(){},debug(){}};
let core,release,entered;
const enteredPromise=new Promise(r=>entered=r),resume=new Promise(r=>release=r);
const runner={async run(p){
 calls.push(structuredClone({...p,tools:undefined}));
 if(p.traceName==='skill.extract'){
  assert.ok(p.systemPrompt.startsWith(SKILL_REVIEW_PROMPT));
  assert.ok(p.systemPrompt.includes('assistant behavior and absence of user correction are not evidence'));
  if(p.taskId==='skill-extract-import-concurrent'){entered();await resume;}
  if(p.taskId==='skill-extract-import-failure')throw new Error('FIXTURE_REVIEW_FAILURE');
  return 'Nothing to save.';
 }
 if(p.taskId==='l1-extraction')return JSON.stringify([{scene_name:'园艺',message_ids:['fixture-source'],memories:[{content:'用户明确在2020年5月1日参与社区园艺，后来又参加了活动但未给出日期。',type:'episodic',priority:75,source_message_ids:['fixture-source'],metadata:{activity_start_time:'2020-05-01T00:00:00.000Z'}}]}]);
 assert.equal(p.taskId,'l1-conflict-detection');assert.ok(p.systemPrompt.includes('Candidate memory timestamps are persistence/recording metadata'));
 const id=p.prompt.match(/### 第 \d+ 条新记忆 \(record_id: ([^)]+)\)/)[1];
 return JSON.stringify([{record_id:id,action:'merge',target_ids:['fixture-existing'],merged_content:'用户明确在2020年5月1日参与社区园艺，后来再次参与但原始时间未知。',merged_type:'episodic',merged_priority:75,merged_timestamps:['2020-05-01T00:00:00.000Z']}]);
}};
try {
 core=await openLocalCore(root,runner,logger,fixtureEmbedding());
 const ids={team_id:'provenance-scope',user_id:'local-user',agent_id:'local-agent'},base={...ids,session_id:'fixture-review',messages:[{role:'user',content:'上个月做过园艺。'}]},unknown={...base,messages:base.messages.map(m=>({...m,timestampKind:'imported-unknown'}))};
 const extractor=core.createSkillExtractor();
 const imported=extractor.extract({...unknown,task_id:'import-concurrent'});await enteredPromise;
 await extractor.extract({...base,task_id:'normal-concurrent'});release();await imported;
 await assert.rejects(extractor.extract({...unknown,task_id:'import-failure'}),/FIXTURE_REVIEW_FAILURE/);
 await extractor.extract({...base,task_id:'normal-after-failure'});
 const reviews=calls.filter(x=>x.traceName==='skill.extract');
 assert.equal(reviews.length,4);assert.equal(reviews[0].prompt,reviews[1].prompt);
 for(const i of [0,2])assert.ok(reviews[i].systemPrompt.includes('This transcript was imported without original message times'));
 for(const i of [1,3])assert.ok(!reviews[i].systemPrompt.includes('This transcript was imported without original message times'));
 assert.equal(reviews[1].systemPrompt,reviews[3].systemPrompt);
 const session='fixture-memory';await core.storeMemory({id:'fixture-existing',sessionKey:session,sessionId:session,content:'用户2020年5月1日在社区园艺。',type:'episodic',priority:75,scene_name:'园艺',source_message_ids:['fixture-earlier'],metadata:{}});
 await core.extractMemories({sessionKey:session,sessionId:session,messages:[{id:'fixture-source',role:'user',content:'我在2020年5月1日参加过园艺，上个月又去了。',timestamp:Date.UTC(2026,9,6),timestampKind:'imported-unknown'}]});
 const extraction=calls.find(x=>x.taskId==='l1-extraction'),merge=calls.find(x=>x.taskId==='l1-conflict-detection');
 assert.ok(extraction.prompt.includes('[original_time:unknown; recorded_at:2026-10-06T00:00:00.000Z]'));assert.ok(extraction.prompt.includes('2020年5月1日'));
 assert.ok(merge.systemPrompt.includes('imported history without original message dates'));assert.ok(merge.prompt.includes('2020'));
 const rows=await core.readMemories();assert.ok(rows.some(r=>r.content.includes('2020年5月1日')));
 const result={status:'PASS_NATIVE_LEARNING_PROVENANCE_BOUNDARIES',realModelRequests:0,fixtureRunnerCalls:calls.length,nativePromptPrefixSha256:createHash('sha256').update(SKILL_REVIEW_PROMPT).digest('hex'),nativeSkillUserPromptUnchanged:true,importedSkillTimeNoteOnlyInImportedScope:true,concurrentNormalAndPostFailureReviewUnaffected:true,userPreferenceSourceRuleDelivered:true,unknownRecordingTimeExplicitlyLabelledAtNativeL1Source:true,explicit2020SourceDatePreserved:true,nativeConflictPromptUnchangedWithAdditionalSystemProvenance:true,nativeMergePersistenceAndVectorCheckPassed:true,fixtureOutputsAreNotGeneratedQualityEvidence:true,probeSha256:createHash('sha256').update(await readFile(fileURLToPath(import.meta.url))).digest('hex')};
 await writeFile(output,JSON.stringify(result,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(result));
}finally{release?.();core?.close();await rm(root,{recursive:true,force:true});}
