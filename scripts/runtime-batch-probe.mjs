import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {LlmAdapter} from '@deepseek-ai/dsh-llm';
export const name='rsi-runtime-batch-probe';
export const inject=['rsi','llm'];
export function apply(ctx,config){
  const calls=[];let extractions=0;
  class Fixture extends LlmAdapter{
    async *stream(options){
      const prompt=options.messages.flatMap(m=>m.content).filter(b=>b.type==='text').map(b=>b.text).join('\n');
      const extraction=prompt.includes('【待提取的新消息】');
      calls.push({extraction,newIds:extraction?[...prompt.split('【待提取的新消息】').at(-1).matchAll(/\[(batch-\d+)\]/g)].map(m=>m[1]):[]});
      if(extraction)extractions++;
      yield{type:'block-start',index:0,blockType:'text'};
      yield{type:'block-end',index:0,block:{type:'text',text:extraction?'[]':'Nothing to save.'}};
      yield{type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};
      yield{type:'finish',reason:{kind:extraction&&extractions===2?'max-tokens':'stop'}};
    }
  }
  ctx.effect(()=>ctx.llm.registerAdapter(['rsi-probe'],new Fixture()));
  ctx.effect(()=>{
    const alive=setInterval(()=>{},1000);const timer=setTimeout(async()=>{try{
      await ctx.rsi.ready;const runtime=ctx.rsi.runtime,cwd=join(config.root,'batch-workspace');await mkdir(cwd,{recursive:true});const scope=(await runtime.scope(cwd)).id;
      if(config.phase==='restore'){
        const job=runtime.state.jobs(scope)[0];assert.equal(job.status,'completed');assert.equal(job.stages.memoryBatches.next,27);assert.equal(calls.length,0);
        await writeFile(join(config.root,'restored.json'),JSON.stringify({status:'PASS',completedCursor:27,modelRequests:0}));process.exit(0);
      }
      const messages=Array.from({length:27},(_,i)=>({id:`batch-${i}`,role:i%2?'assistant':'user',content:`批次 ${i} 的原始消息：本工作区需要独立保存错误日志，并依据实际执行结果判断修改是否通过验证。`,timestamp:new Date(Date.now()+i).toISOString()}));
      messages.splice(11,0,{id:'filtered',role:'assistant',content:'??',timestamp:new Date().toISOString()});
      runtime.state.enqueue({scope,sessionId:'batch-source',turn:1,endSeq:28,cwd,messages,route:{provider:'rsi-probe',model:'fixture'},reason:{kind:'completed'}});
      const job=runtime.state.jobs(scope)[0];runtime.state.updateJob(job.id,'pending',{recorded:true});
      await assert.rejects(runtime.process(scope,'batch-source'),e=>e.code==='OUTPUT_TRUNCATED');
      const failed=runtime.state.jobs(scope)[0];assert.equal(failed.stages.memoryBatches.next,10);assert.equal(failed.stages.memory,undefined);assert.equal(failed.stages.skills,undefined);
      await runtime.process(scope,'batch-source');const complete=runtime.state.jobs(scope)[0];assert.equal(complete.status,'completed');assert.equal(complete.stages.memoryBatches.next,27);
      const batches=calls.filter(c=>c.extraction).map(c=>c.newIds);assert.deepEqual(batches,[messages.filter(m=>m.id!=='filtered').slice(0,10).map(m=>m.id),messages.filter(m=>m.id!=='filtered').slice(10,20).map(m=>m.id),messages.filter(m=>m.id!=='filtered').slice(10,20).map(m=>m.id),messages.filter(m=>m.id!=='filtered').slice(20).map(m=>m.id)]);
      assert.equal(calls.filter(c=>!c.extraction).length,1);
      await writeFile(join(config.root,'result.json'),JSON.stringify({status:'PASS',realModelRequests:0,fixtureRequests:calls.length,qualifiedSourceMessages:27,rawSourceMessages:28,newMessageBatchSizes:batches.map(b=>b.length),completedCursor:27,failedBatchRetriedWithoutReplayingPrefix:true,shortTailDoesNotRelabelBackgroundAsNew:true,skillWaitsForCompleteMemoryStage:true,limitation:'Synthetic responses verify native batching and durable retry; no model quality or natural scheduler claim.'}));process.exit(0);
    }catch(error){console.error(error.stack);process.exit(1);}},0);return()=>{clearInterval(alive);clearTimeout(timer);};
  });
}
