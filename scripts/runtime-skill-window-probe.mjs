import assert from 'node:assert/strict';
import {readFile,writeFile,access} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {openLocalCore} from '../lib/local-core.js';
import {fixtureEmbedding} from './fixture-embedding.mjs';
export const name='runtime-skill-window-probe';
export const inject=['rsi'];
export function apply(ctx,config){
  ctx.effect(()=>{const alive=setInterval(()=>{},1000),timer=setTimeout(async()=>{try{
    await ctx.rsi.ready;
    const Constructor=ctx.rsi.runtime.constructor,logger={info(){},warn(){},error(){},debug(){}};
    const cases=[{name:'default',window:undefined},{name:'expanded',window:{headChars:40000,tailChars:64000}},{name:'partial',window:{headChars:10000}}];
    if(config.phase==='restore'){
      for(const entry of cases){const runtime=new Constructor(ctx,{skillTranscriptWindow:entry.window},join(config.root,entry.name+'-state'));try{assert.equal(runtime.state.jobs('window-scope')[0].status,'completed');assert.deepEqual(runtime.skillTranscriptWindow,entry.window??{});}finally{runtime.state.close();}}
      await writeFile(join(config.root,'restored.json'),JSON.stringify({status:'PASS',restoredCompletedJobs:3,configurationRevalidated:true,modelRequests:0}));process.exit(0);
    }
    const liveSnapshot=await ctx.rsi.request('snapshot',{cwd:config.root});assert.deepEqual(liveSnapshot.skillTranscriptWindow,{});
    const payload=JSON.parse(await readFile(process.env.RSI_WINDOW_SOURCE_PAYLOAD,'utf8'));
    const full=payload.messages.map(m=>`<<past-${m.role}>>\n${m.content}`).join('\n\n')+'\n\n<<end-of-transcript>>\nAbove is the past conversation to review. Now decide, and respond only per the output contract in the system prompt.';
    const signature='params, varargs, varkw, defaults, kwonly, kwonly_defaults, _ = getfullargspec(unwrap(func))';
    const outputs=[];
    for(const entry of cases){
      const cfg={provider:'fixture',model:'fixture',skillTranscriptWindow:entry.window,settings:{learningEnabled:true,dailyCallBudget:40}},runtime=new Constructor(ctx,cfg,join(config.root,entry.name+'-state'));
      let core;const calls=[];
      try {
        core=await openLocalCore(join(config.root,entry.name+'-core'),{async run(params){calls.push(params);return 'Nothing to save.';}},logger,fixtureEmbedding());
        // Only core lookup and the already-completed Memory stages are fixtures; process/SkillExtractor are real.
        runtime.core=async()=>core;
        if(entry.window)cfg.skillTranscriptWindow={headChars:1,tailChars:1};
        runtime.state.enqueue({scope:'window-scope',cwd:config.root,sessionId:'window-source',turn:1,endSeq:1,reason:payload.reason,messages:payload.messages,route:{provider:'fixture',model:'fixture'}});
        const job=runtime.state.jobs('window-scope')[0];runtime.state.updateJob(job.id,'pending',{recorded:true,memory:{stored:0}});
        await runtime.process('window-scope','window-source');assert.equal(runtime.state.jobs('window-scope')[0].status,'completed');assert.equal(calls.length,1);
        const logged=await readFile(join(runtime.directory,'scopes/window-scope/diagnostics/observability.log'),'utf8');
        const line=logged.split('\n').find(line=>line.includes('rsi.skill.review.window '));assert.ok(line);
        const event=JSON.parse(line.split('rsi.skill.review.window ')[1]);assert.deepEqual(event.configured_window,entry.window??{});assert.equal(event.source_messages,payload.messages.length);
        const head=entry.window?.headChars??8000,tail=entry.window?.tailChars??32000;
        const expected=full.length<=head+tail?full:`${full.slice(0,head)}\n\n... [truncated ${full.length-head-tail} chars] ...\n\n${full.slice(-tail)}`;
        assert.ok(calls[0].prompt.endsWith(expected));assert.equal(runtime.state.usage().calls,0);
        outputs.push({name:entry.name,effectiveNativeHeadChars:head,effectiveNativeTailChars:tail,criticalSignatureOccurrences:calls[0].prompt.split(signature).length-1,exactNativeSuffix:true,configurationSnapshotPreserved:true,promptSha256:createHash('sha256').update(calls[0].prompt).digest('hex'),systemSha256:createHash('sha256').update(calls[0].systemPrompt).digest('hex')});
      }finally{core?.close();runtime.state.close();}
    }
    assert.equal(outputs[0].criticalSignatureOccurrences,0);assert.equal(outputs[1].criticalSignatureOccurrences,4);assert.equal(new Set(outputs.map(o=>o.systemSha256)).size,1);
    const invalid=[null,[],{headChars:0},{tailChars:-1},{headChars:1.5},{tailChars:'64000'},{headChars:NaN},{maxTokens:99999}];
    for(const [i,window] of invalid.entries()){
      const path=join(config.root,'invalid-'+i);assert.throws(()=>new Constructor(ctx,{skillTranscriptWindow:window},path),e=>e.code==='INVALID_CONFIG');await assert.rejects(access(join(path,'rsi-state.sqlite')));
    }
    const result={status:'PASS',realProviderRequests:0,taskCommandsExecuted:0,fixtureRunnerCalls:3,nativeSkillRuntimeJobsCompleted:3,sourceMessages:payload.messages.length,fullTranscriptUtf16Chars:full.length,sourcePayloadSha256:createHash('sha256').update(await readFile(process.env.RSI_WINDOW_SOURCE_PAYLOAD)).digest('hex'),cases:outputs,invalidStartupControlsRejectedBeforeStateCreation:invalid.length,unconfiguredNativeDefaultsRetained:true,configuredWindowVisibleInSnapshotAndDiagnostics:true,nativeFormatterAndSystemPromptUnchanged:true,limitation:'Actual Runtime.process and native SkillExtractor are exercised; core lookup, completed Memory stages and model/encoding use explicit fixtures. Not a model quality or effect benchmark.'};
    await writeFile(join(config.root,'result.json'),JSON.stringify(result));console.log(JSON.stringify(result));process.exit(0);
  }catch(error){console.error(error.stack);process.exit(1);}finally{clearInterval(alive);}},0);return()=>{clearInterval(alive);clearTimeout(timer);};});
}
