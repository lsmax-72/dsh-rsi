import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {mkdtemp,readFile,writeFile,mkdir,rm} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {dirname,join} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';

const repo=dirname(dirname(fileURLToPath(import.meta.url)));
const root=await mkdtemp('/private/tmp/dsh-rsi-capability-audit-');
const logger={info(){},warn(){},error(){},debug(){}};
const req=createRequire(join(repo,'package.json'));
const original=await readFile(join(repo,'lib/index.js'),'utf8');
// Expose the existing built Runtime for an offline audit; its methods are unchanged.
const instrumented=original.replace(/from "([^"]+)"/g,(_,id)=>`from ${JSON.stringify(id.startsWith('node:')?id:pathToFileURL(id.startsWith('.')?join(repo,'lib',id):req.resolve(id)).href)}`)+'\nexport {Runtime};\n';
await writeFile(join(root,'runtime.mjs'),instrumented);
const {Runtime}=await import(pathToFileURL(join(root,'runtime.mjs')));
const cwd=join(root,'workspace');await mkdir(cwd);
const runtime=new Runtime({logger,llm:{prepareCall(){throw Error('Network dispatch forbidden in this audit');}}},{cwd,settings:{learningEnabled:false},l2DelaySeconds:86400},join(root,'assets'));
const entry=await runtime.scope(cwd),core=await runtime.core(entry.id),global=await runtime.core('global');
const ids={team_id:entry.id,user_id:'local-user',agent_id:'local-agent'};
const content=name=>`---\nname: ${name}\ndescription: 离线审计技能\n---\n\n运行离线审计并保留记录。`;
const evidence={checkedAt:new Date().toISOString(),head:process.argv[2],method:'Existing build, Runtime export instrumentation only; temporary databases and fixtures; no model or task commands.',buildIndexSha256:createHash('sha256').update(original).digest('hex'),modelRequests:0};
try {
  let oldest;
  for(let i=0;i<51;i++){const skill=await core.skills.create({...ids,name:`audit-${i}`,content:content(`audit-${i}`)});if(i===0)oldest=skill;}
  const all=await core.skills.list({...ids,pagination:{limit:1000}});
  const candidates=await runtime.candidates(cwd),snapshot=await runtime.snapshot(cwd),exported=await runtime.request('export',{cwd});
  assert.equal(all.total,51);assert.equal(candidates.length,51);assert.equal(snapshot.skills.length,51);assert.equal(exported.skills.length,51);
  const oldestCandidate=candidates.find(c=>c.locator.id===oldest.skill_id);assert.ok(oldestCandidate);assert.ok((await runtime.definition(oldestCandidate,cwd)).content.includes('离线审计'));
  evidence.skillPagination={stored:all.total,candidates:candidates.length,management:snapshot.skills.length,export:exported.skills.length,omittedSkillIds:all.items.filter(s=>!candidates.some(c=>c.locator.id===s.skill_id)).map(s=>s.skill_id)};
  let head=oldest;
  for(let i=1;i<=50;i++)head=await core.skills.update({...ids,skill_id:head.skill_id,expected_version:head.version,content:content(head.name)+`\n审计修订 ${i}`});
  const versions=await runtime.request('versions',{cwd,id:head.skill_id});
  const exportWithVersions=await runtime.request('export',{cwd});
  const exportedVersions=exportWithVersions.skills.find(s=>s.head.skill_id===head.skill_id).versions;
  assert.equal(versions.total,51);assert.equal(versions.items.length,51);assert.equal(exportedVersions.length,51);assert.ok(exportedVersions.some(v=>v.version===oldest.version));
  evidence.versionPagination={stored:versions.total,management:versions.items.length,export:exportedVersions.length,oldestVersion:oldest.version,oldestVersionExported:exportedVersions.some(v=>v.version===oldest.version)};
  const marker='WORKSPACE_AUDIT_MEMORY';
  await core.storeMemory({id:'audit-memory',sessionKey:'audit-source',sessionId:'audit-source',taskId:'audit-source-task',content:`${marker} 这个工作区需要先检查测试环境并保留完整失败日志。`,type:'instruction',priority:90,scene_name:'审计',source_message_ids:['fixture-source'],metadata:{}});
  const nativeWorkspace=await core.recall(marker,3000);assert.ok(nativeWorkspace.prependContext.includes(marker));
  await global.profile.writeFile('persona.md','GLOBAL_PERSONA_AUDIT '+ '通用画像正文。'.repeat(1200));
  const merged=await runtime.recall(cwd,marker);assert.equal(merged.text.length,6000);assert.ok(!merged.text.includes(marker));assert.ok(merged.refs.some(r=>r.scope===entry.id&&r.memories.some(m=>m.content.includes(marker))));
  evidence.contextTruncation={nativeWorkspaceContainsMemory:true,deliveredTextContainsWorkspaceMemory:false,provenanceStillContainsWorkspaceMemory:true,deliveredChars:merged.text.length,personaClosingTagPresent:merged.text.includes('</user-persona>'),profileReadGuidePresent:merged.text.includes('参数 query 为上述完整路径')};
  const job=runtime.state.enqueue({scope:entry.id,cwd,sessionId:'audit-failure',turn:1,endSeq:1,reason:{kind:'completed'},route:{provider:'fixture',model:'fixture'},messages:[{role:'user',content:'检查一次可恢复的离线提炼错误。',timestamp:new Date().toISOString()}],events:[]});
  assert.ok(job);
  const queued=runtime.state.jobs(entry.id).find(j=>j.session==='audit-failure');runtime.state.updateJob(queued.id,'pending',{recorded:true});
  const extract=core.extractMemories;core.extractMemories=async()=>{throw new Error('AUDIT_FIXTURE_EXTRACTION_FAILURE');};
  runtime.state.configure({learningEnabled:true});
  const result=await runtime.process(entry.id,'audit-failure');core.extractMemories=extract;
  runtime.state.configure({learningEnabled:false});
  const failed=runtime.state.jobs(entry.id).find(j=>j.id===queued.id);assert.equal(failed.status,'failed');
  evidence.pipelineFailure={jobStatus:failed.status,runnerRejected:false,runnerReturned:result,error:failed.error,explanation:'A non-budget extraction error is caught by process(), which fulfills the native pipeline runner rather than invoking its rejection retry path.'};
  evidence.status='PAGINATION_REPAIR_VERIFIED_OTHER_DEFECTS_REPRODUCED';
  console.log(JSON.stringify(evidence,null,2));
} finally {await runtime.stop();await rm(root,{recursive:true,force:true});}
