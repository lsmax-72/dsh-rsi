import assert from 'node:assert/strict';
import {mkdtemp,readFile,writeFile,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {join} from 'node:path';
import {openLocalCore} from '../lib/local-core.js';
import {parseSkillFile} from '../lib/core-entry.js';
import {fixtureEmbedding} from './fixture-embedding.mjs';
const output=process.argv[2];assert.ok(output,'Receipt path required');
const root=await mkdtemp('/private/tmp/dsh-rsi-native-body-budget-');
const ids={team_id:'budget-scope',user_id:'local-user',agent_id:'local-agent'};
const file=(name,body)=>`---\nname: ${name}\ndescription: 原生预算验证夹具\n---\n\n${body}`;
const short='# 流程\n\n保留触发和决策。\n\n## 证据\n只验证夹具写入，不代表真实经验。\n\n## 资源\n详细内容见 notes/evidence.txt。';
const long='# 详细流程\n'+'详细知识'.repeat(600),resource='逐项来源与未验证脚本作为数据保留。\n'.repeat(800);
let phase='oversize-create',callCount=0,start,release;
const entered=new Promise(resolve=>start=resolve),resume=new Promise(resolve=>release=resolve);
let core;const results=[];
const logger={info(){},warn(){},error(){},debug(){}};
try {
 core=await openLocalCore(root,{async run(params){
  callCount++;assert.ok(params.systemPrompt.includes('1500 Unicode characters'));
  const execute=async(name,args)=>JSON.parse(await params.tools[name].execute(args));
  if(phase==='oversize-create'){
   start();await resume;
   const result=await execute('skill_create',{name:'oversize-generated',content:file('oversize-generated',long)});
   assert.match(result.message,/RSI_SKILL_BODY_BUDGET_EXCEEDED/);assert.equal(result.error,'SKILL_FRONTMATTER_INVALID');results.push({control:'oversize-create',rejected:true});
  }else if(phase==='native-version-resource'){
   const created=await execute('skill_create',{name:'compact-generated',content:file('compact-generated',short)});assert.ok(created.ok);
   const written=await execute('skill_files_write',{skill_id:created.skill_id,expected_version:created.version,path:'notes/evidence.txt',content:resource});assert.ok(written.ok);assert.equal(written.version,2);
   const rejected=await execute('skill_update',{skill_id:created.skill_id,expected_version:2,content:file('compact-generated',long)});assert.match(rejected.message,/RSI_SKILL_BODY_BUDGET_EXCEEDED/);
   const badPatch=await execute('skill_patch',{skill_id:created.skill_id,expected_version:2,old_string:'保留触发和决策。',new_string:long});assert.match(badPatch.message,/RSI_SKILL_BODY_BUDGET_EXCEEDED/);
   const stale=await execute('skill_update',{skill_id:created.skill_id,expected_version:1,content:file('compact-generated',long)});assert.equal(stale.error,'SKILL_VERSION_STALE');
   const noMatch=await execute('skill_patch',{skill_id:created.skill_id,expected_version:2,old_string:'ABSENT_FIXTURE_MARKER',new_string:long});assert.equal(noMatch.error,'SKILL_PATCH_NOT_UNIQUE');
   let current=await core.skills.get({...ids,skill_id:created.skill_id,include_content:true,include_manifest:true});assert.equal(current.version,2);assert.equal(parseSkillFile(current.content).body,short);
   const changed=await execute('skill_patch',{skill_id:created.skill_id,expected_version:2,old_string:'保留触发和决策。',new_string:'保留触发、决策与失败分支。'});assert.ok(changed.ok);assert.equal(changed.version,3);
   current=await core.skills.get({...ids,skill_id:created.skill_id,include_content:true,include_manifest:true});assert.equal(current.version,3);assert.equal(current.manifest.length,1);
   const actual=await core.resources.readResource(created.skill_id,3,'notes/evidence.txt','utf-8');assert.equal(actual.content,resource);
   const older=await core.skills.get({...ids,skill_id:created.skill_id,version:1,include_content:true,include_manifest:true});assert.equal(older.version,1);assert.equal(older.manifest.length,0);
   results.push({control:'native-version-resource',updateAndPatchOversizeRejectedBeforeNewVersion:true,nativeStaleAndPatchErrorsPreserved:true,versions:[1,2,3],oldVersionRetained:true,resourceChars:[...resource].length,resourceSha256:createHash('sha256').update(actual.content).digest('hex'),resourceNotTruncated:true,bodyChars:[...parseSkillFile(current.content).body].length});
  }else if(phase==='unicode-boundary'){
   const exact=await execute('skill_create',{name:'exact-unicode-budget',content:file('exact-unicode-budget','😀'.repeat(1500))});assert.ok(exact.ok);
   const tooLong=await execute('skill_create',{name:'over-unicode-budget',content:file('over-unicode-budget','😀'.repeat(1501))});assert.match(tooLong.message,/RSI_SKILL_BODY_BUDGET_EXCEEDED/);results.push({control:'unicode-boundary',exact1500Accepted:true,unicode1501Rejected:true});
  }else throw Error('fixture review runner failure');
  return 'Nothing to save.';
 }},logger,fixtureEmbedding());
 const input={...ids,session_id:'source-fixture',task_id:'body-budget-fixture',messages:[{role:'user',content:'Explicit development fixture; no model or task execution.'}]};
 const review=core.createSkillExtractor().extract(input);await entered;
 const manual=await core.skills.create({...ids,name:'human-long-concurrent',content:file('human-long-concurrent',long)});assert.ok(manual.skill_id);release();await review;
 const listed=await core.skills.list({...ids,limit:50});assert.equal(listed.items.length,1);assert.equal(listed.items[0].name,'human-long-concurrent');
 phase='native-version-resource';await core.createSkillExtractor().extract(input);
 phase='unicode-boundary';await core.createSkillExtractor().extract(input);
 phase='fixture-throw';await assert.rejects(core.createSkillExtractor().extract(input),/fixture review runner failure/);
 const after=await core.skills.create({...ids,name:'human-long-after-failure',content:file('human-long-after-failure',long)});assert.ok(after.skill_id);
 const receipt={status:'PASS_NATIVE_REVIEW_BODY_BUDGET',controls:results,concurrentHumanNativeLongBodyAccepted:true,ordinaryMutationAfterReviewFailureAccepted:true,realModelRequests:0,fixtureReviewRunnerCalls:callCount,embeddingFixture:true,nativeSkillCoreToolsSqliteVersionResourcesUsed:true,resourceScriptsExecuted:false,contentQualityOrEffectClaim:false,scope:'Review-only write budget and native mutation/resource contract. Actual generated semantics and consumer loading need real validation.'};
 await writeFile(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{release?.();core?.close();await rm(root,{recursive:true,force:true});}
