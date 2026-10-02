import assert from 'node:assert/strict';
import { readFile, writeFile } from 'node:fs/promises';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
export const name = 'rsi-model-probe';
export const inject = ['rsi', 'agents', 'llm', 'sessions', 'tools'];

export function apply(ctx) {
  const requests=[],results=[];
  ctx.on('llm/stream',async function*(options,next){
    requests.push({provider:options.provider,model:options.model,sessionId:options.sessionId});
    for await (const chunk of next()) yield chunk;
  });
  ctx.on('tools/result',(exec,result)=>results.push({name:exec.name,isError:result.isError}));
  ctx.effect(()=>{
    const alive=setInterval(()=>{},1000);
    const timer=setTimeout(async()=>{
      try {
        await ctx.rsi.ready;
        const handle=await ctx.agents.create({sessionId:'model-compatibility',meta:{cwd:'/workspace'},agentOptions:{provider:'qwen',model:'qwen3.8-27b',maxTokens:4096}});
        handle.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:'Use the write tool to create /workspace/model-check.txt containing exactly MODEL_TOOL_PASS. Then use the read tool to read that file and finish. Do not use Bash or run_code. This checks tool compatibility, not a coding task.'}]}));
        await handle.agent.whenIdle();await ctx.sessions.flush(handle.agent.session);
        assert.equal(await readFile('/workspace/model-check.txt','utf8'),'MODEL_TOOL_PASS');
        for(const tool of ['write','read']) assert.ok(results.some(r=>r.name===tool&&!r.isError),JSON.stringify(results));
        const receipt={status:'PASS',model:'qwen3.8-27b',provider:'qwen',requests:requests.length,tools:results,limitation:'Real-model tool compatibility only; no benchmark task or effectiveness conclusion.'};
        await writeFile('/state/model-probe.json',JSON.stringify(receipt));console.log(JSON.stringify(receipt));process.exit(0);
      } catch(error) {console.error(error.stack);console.error(JSON.stringify({requests,results}));process.exit(1);}
    },0);
    return()=>{clearInterval(alive);clearTimeout(timer);};
  });
}
