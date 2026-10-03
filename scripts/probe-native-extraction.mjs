import assert from 'node:assert/strict';
import {mkdtemp,rm,readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';
import {openLocalCore} from '../lib/local-core.js';
import {SKILL_REVIEW_PROMPT} from '../lib/core-entry.js';

const root=await mkdtemp('/private/tmp/dsh-rsi-native-extraction-');
const calls=[];
const runner={async run(params){calls.push(params);return 'Nothing to save.';}};
const logger={info(){},warn(){},error(){},debug(){}};
const core=await openLocalCore(join(root,'assets'),runner,logger);
try {
  const result=await core.createSkillExtractor('zh-CN').extract({user_id:'local-user',team_id:'fixture',agent_id:'local-agent',task_id:'fixture-review',session_id:'fixture-source',messages:[{role:'user',content:'请检查本次失败的测试，保留执行日志，不要把计划描述为已经成功。'},{role:'assistant',content:'本次目标检查仍然失败，应继续排查环境和代码。'},{role:'tool_result',content:'exit_code=1; test failed'}]});
  const review=calls.find(p=>p.taskId==='skill-extract-fixture-review');assert.ok(review);
  assert.ok(review.systemPrompt.startsWith(SKILL_REVIEW_PROMPT+'\n'));
  assert.equal(review.systemPrompt.slice(0,SKILL_REVIEW_PROMPT.length),SKILL_REVIEW_PROMPT);
  for(const marker of ['<<past-user>>','<<past-assistant>>','<<past-tool_result>>','<<end-of-transcript>>'])assert.ok(review.prompt.includes(marker),marker);
  assert.ok(review.systemPrompt.includes('Write asset prose in zh-CN'));
  assert.deepEqual(result.candidates,[]);
  const manifest=JSON.parse(await readFile(fileURLToPath(new URL('../vendor/core/manifest.json',import.meta.url)),'utf8'));
  console.log(JSON.stringify({status:'PASS',checkedAt:new Date().toISOString(),sourceRevision:manifest.revision,sourceFileSha256:manifest.files.find(f=>f.path==='core/skill/prompts/skill-review-prompt.ts').sha256,configuredNativePromptSha256:createHash('sha256').update(review.systemPrompt.slice(0,SKILL_REVIEW_PROMPT.length)).digest('hex'),nativePromptChars:SKILL_REVIEW_PROMPT.length,nativeProductionPromptDelivered:true,transcriptRolesPreserved:true,noChangeContract:true,fixtureRunnerCalls:calls.length,realModelRequests:0},null,2));
}finally{core.close();await rm(root,{recursive:true,force:true});}
