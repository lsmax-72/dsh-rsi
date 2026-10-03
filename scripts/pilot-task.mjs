import assert from 'node:assert/strict';
import { cp, mkdir, readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import { Session } from '@deepseek-ai/dsh-session';

export const name='rsi-pilot-task';
export const inject=['rsi','llm','agents','sessions','sessionPersistence','skills','tools'];
export function apply(ctx,config) {
  const requests=[],results=[];let foreground=0,deadline;
  const dispatchLimit=config.dispatchLimit??50;
  const wallTimeMs=config.wallTimeMs??1200000;
  ctx.on('llm/stream',async function*(options,next){
    if(!options.sessionId.startsWith('rsi-')){if(foreground>=dispatchLimit)throw new Error('Pilot foreground dispatch limit reached');foreground++;}
    const request={sessionId:options.sessionId,messages:structuredClone(options.messages)};
    requests.push(request);
    for await(const chunk of next()){if(chunk.type==='usage')request.usage=chunk.usage;yield chunk;}
  });
  ctx.on('tools/result',(exec,result)=>results.push({name:exec.name,args:exec.arguments,isError:result.isError}));
  ctx.effect(()=>{
    const alive=setInterval(()=>{},1000);
    const timer=setTimeout(async()=>{
      let handle;
      const dir='/state/pilot/'+config.instanceId;
      try{
        await mkdir(dir,{recursive:true});
        await cp('/opt/task-source','/workspace',{recursive:true});
        const git=(...args)=>execFileSync('git',args,{cwd:'/workspace',encoding:'utf8'});
        git('init');git('config','user.name','lsmax');git('config','user.email','liushuai072002@163.com');
        git('add','-A');git('commit','-m','Pilot task baseline');const baseline=git('rev-parse','HEAD').trim();
        await ctx.rsi.ready;
        const before=await ctx.rsi.request('snapshot',{cwd:'/workspace'});
        assert.equal(before.settings.dailyCallBudget,config.learningCallBudget??30,'Pilot learning budget does not match effective settings');
        const problem=await readFile('/opt/rsi/task.json','utf8');
        const task=JSON.parse(problem);
        handle=await ctx.agents.create({sessionId:'pilot-'+config.instanceId,meta:{cwd:'/workspace'},agentOptions:{provider:'qwen',model:'qwen3.8-27b',maxTokens:8192}});
        deadline=setTimeout(()=>handle.agent.cancel({kind:'hook',reason:'Pilot wall time limit reached'}),wallTimeMs);
        const prompt=`修复以下 Django 仓库问题。工作区为 /workspace，测试环境已离线准备，python 来自官方 testbed 环境。先检查本工作区已有的相关经验和技能；先验证环境，再运行聚焦测试，保留失败原因。禁止联网检索答案。完成后用中文说明修改、测试及局限。\n\n${task.problem_statement}`;
        handle.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:prompt}]}));
        await handle.agent.whenIdle();await ctx.sessions.flush(handle.agent.session);clearTimeout(deadline);
        git('add','-A');const patch=git('diff','--cached','--binary',baseline);
        await writeFile(dir+'/prediction.patch',patch);
        const outcomeHandle=await ctx.sessionPersistence.open(handle.agent.session.id,'read');
        const outcome=await outcomeHandle.read();await outcomeHandle.close();
        const stopReason=outcome.events.filter(e=>e.type==='turn/end').at(-1)?.data.reason;
        // Let the native queued learner settle; do not feed grader outcomes or answer patches back.
        let after;
        for(let i=0;stopReason?.kind!=='aborted'&&i<360;i++){
          after=await ctx.rsi.request('snapshot',{cwd:'/workspace'});
          const job=after.jobs.find(j=>j.sourceSessionId===handle.agent.session.id);
          if(job&&['completed','failed','paused'].includes(job.status))break;
          await new Promise(r=>setTimeout(r,1000));
        }
        await new Promise(r=>setTimeout(r,2000));
        after=await ctx.rsi.request('snapshot',{cwd:'/workspace'});
        const persistence=await ctx.sessionPersistence.open(handle.agent.session.id,'read');
        const stored=await persistence.read();await persistence.close();
        const header=stored.events.find(e=>e.type==='request/header');
        const restored=Session.fromRestore(handle.agent.session.id,stored.events.slice(0,header.seq+1),persistence.header,persistence.inheritedEventCount,stored.eventState);
        assert.deepEqual([...restored.deriveMessages()],requests.find(r=>r.sessionId===handle.agent.session.id).messages);
        const injections=stored.events.filter(e=>e.type==='user/message'&&e.data.source?.kind==='dsh-rsi');
        const usage=requests.map(r=>({sessionId:r.sessionId,usage:r.usage??null}));
        // Runtime exit success does not establish task completion or official resolution.
        const status=stopReason?.kind==='completed'?'TURN_COMPLETED':stopReason?.kind==='max-tokens'?'TOKEN_LIMIT':stopReason?.kind==='aborted'?'ABORTED':'TURN_FAILED';
        const receipt={status,runnerStatus:'COMPLETED',instanceId:config.instanceId,provider:'qwen',model:'qwen3.8-27b',
          taskDispatches:foreground,backgroundDispatches:requests.length-foreground,patchBytes:Buffer.byteLength(patch),
          before:{memory:before.memory.length,skills:before.skills.length,layers:before.layers},
          after:{memory:after.memory.length,skills:after.skills.length,layers:after.layers,jobs:after.jobs},
          memoryInjections:injections.map(e=>e.data.source),skillLoads:results.filter(r=>r.name==='skill'),
          stopReason,usage,toolResults:results,limits:{dispatchLimit,wallTimeMs,learningCallBudget:before.settings.dailyCallBudget,learningMaxTokens:before.settings.maxTokens},
          logReconstructionMatches:true,toolSchemas:ctx.tools.schemas().map(t=>t.name),
          limitation:'Two-task integration pilot only; no paired benchmark or product-effect claim.'};
        await writeFile(dir+'/receipt.json',JSON.stringify(receipt,null,2));
        await writeFile(dir+'/source-events.json',JSON.stringify(stored.events));
        await writeFile(dir+'/model-requests.json',JSON.stringify(requests));
        await writeFile(dir+'/assets.json',JSON.stringify(await ctx.rsi.request('export',{cwd:'/workspace'})));
        await ctx.root.fiber.dispose();
        console.log(JSON.stringify(receipt));process.exit(0);
      }catch(error){
        clearTimeout(deadline);await writeFile(dir+'/failure.json',JSON.stringify({status:'INFRA',error:error.message,requests:requests.length,results}));
        console.error(error.stack);process.exit(1);
      }
    },0);
    return()=>{clearInterval(alive);clearTimeout(timer);clearTimeout(deadline);};
  });
}
