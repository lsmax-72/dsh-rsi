import {fixtureEmbedding} from './fixture-embedding.mjs';
import assert from 'node:assert/strict';
import {mkdtemp,readFile,rm} from 'node:fs/promises';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {openLocalCore} from '../lib/local-core.js';
import {FileLogger,withLocalDiagnostics} from '../lib/core-entry.js';
const root=await mkdtemp('/private/tmp/dsh-rsi-native-diagnostics-'),logger={info(){},warn(){},error(){},debug(){}},cores=[];
let fixtureRunnerCalls=0;
try {
  const cases=await Promise.all(['workspace-a','workspace-b'].map(async scope=>{
    const dir=join(root,scope),sink=new FileLogger({path:join(dir,'diagnostics'),filename:'observability.log',rotateSizeBytes:100*1024*1024,rotateBackupLimit:10});
    const runner={run:async()=>{fixtureRunnerCalls++;await new Promise(r=>setTimeout(r,scope==='workspace-a'?8:2));return 'Nothing to save.';}};
    const core=await openLocalCore(dir,runner,logger,fixtureEmbedding());cores.push(core);
    const input={user_id:'local-user',team_id:scope,agent_id:'local-agent',session_id:`session-${scope}`,task_id:`job-${scope}`,messages:[{role:'user',content:'验证一次原生结构化事件，不生成资产。'},{role:'assistant',content:'Nothing to save.'}]};
    await withLocalDiagnostics(sink,{scope,source_session_id:input.session_id,job_id:input.task_id},()=>core.createSkillExtractor().extract(input));
    const failCore=await openLocalCore(join(dir,'failure'),{run:async()=>{fixtureRunnerCalls++;throw Object.assign(new Error('DIAGNOSTIC_FIXTURE_FAILURE'),{code:'BUDGET_EXHAUSTED'});}},logger,fixtureEmbedding());cores.push(failCore);
    await withLocalDiagnostics(sink,{scope,source_session_id:input.session_id,job_id:input.task_id},async()=>{
      await assert.rejects(failCore.createSkillExtractor().extract(input),/DIAGNOSTIC_FIXTURE_FAILURE/);
      await assert.rejects(failCore.extractMemories({sessionKey:input.session_id,sessionId:input.session_id,messages:[{id:'fixture',role:'user',content:'需要保留错误代码。',timestamp:Date.now()}]}),e=>e.code==='BUDGET_EXHAUSTED');
    });
    const lines=(await readFile(join(dir,'diagnostics/observability.log'),'utf8')).trim().split('\n');
    const events=lines.map(line=>({level:line.match(/\]\[([^\]]+)\]/)[1],event:line.slice(line.indexOf('] ',line.indexOf(']['))+2,line.indexOf(' {')),attrs:JSON.parse(line.slice(line.indexOf(' {')+1))}));
    assert.ok(events.some(e=>e.level==='INFO'&&e.event==='skill.extractor.extract'&&e.attrs.prompt_chars>0));
    assert.ok(events.some(e=>e.level==='WARN'&&e.attrs.err_msg==='DIAGNOSTIC_FIXTURE_FAILURE'));
    assert.ok(events.some(e=>e.level==='TRACE'&&e.attrs.success===false));assert.ok(events.some(e=>e.level==='TRACE'&&e.attrs.success===true));
    assert.ok(events.some(e=>e.level==='METRIC'&&e.attrs.metric==='skill.extract.candidates'));
    assert.ok(events.every(e=>e.attrs.scope===scope&&e.attrs.job_id===input.task_id&&e.attrs.source_session_id===input.session_id));
    return {scope,eventCount:events.length,levels:[...new Set(events.map(e=>e.level))]};
  }));
  console.log(JSON.stringify({status:'PASS',checkedAt:new Date().toISOString(),realModelRequests:0,fixtureRunnerCalls,cases,checks:['native-extractor-info-and-warning-persisted','native-trace-success-and-failure-persisted','native-metric-persisted','concurrent-scope-job-session-isolation','L1-native-failure-restores-model-error-code'],distributedSpanExport:false},null,2));
}finally{for(const core of cores)core.close();await rm(root,{recursive:true,force:true});}
