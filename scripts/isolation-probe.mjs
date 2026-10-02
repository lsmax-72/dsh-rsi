import assert from 'node:assert/strict';
import { access, readFile, writeFile } from 'node:fs/promises';
import { LlmAdapter, createUserMessage } from '@deepseek-ai/dsh-llm';

export const name = 'rsi-isolation-probe';
export const inject = ['rsi', 'llm', 'agents', 'tools', 'sessions'];

export function apply(ctx, config) {
  const results = [], requests = [];
  const boundary = `
const {default:assert}=await import('node:assert/strict');
const {default:fs}=await import('node:fs');
const {default:net}=await import('node:net');
const {execFileSync}=await import('node:child_process');
assert.equal(process.getuid(),1000);
for(const path of [${JSON.stringify(config.sentinel)}, '/var/run/docker.sock', '/Users/lsmax/Coder/dsh-rsi/package.json']) assert.equal(fs.existsSync(path),false,path);
assert.throws(()=>fs.writeFileSync('/opt/rsi/lib/index.js','blocked'));
assert.throws(()=>fs.writeFileSync('/etc/rsi-probe','blocked'));
assert.equal(execFileSync('python3',['-c','import os; print(os.getuid())'],{encoding:'utf8'}).trim(),'1000');
await new Promise((resolve,reject)=>{const s=net.connect({host:'1.1.1.1',port:443});s.once('connect',()=>{s.destroy();reject(new Error('External connection unexpectedly allowed'));});s.once('error',()=>resolve());s.setTimeout(1000,()=>{s.destroy();resolve();});});
console.log('BOUNDARY_PASS');`;
  const calls = [
    ['write', {file_path:'/workspace/probe.txt',content:'before\n'}],
    ['read', {file_path:'/workspace/probe.txt'}],
    ['edit', {file_path:'/workspace/probe.txt',old_string:'before',new_string:'after'}],
    ['grep', {pattern:'after',path:'/workspace',include:'*.txt'}],
    ['glob', {pattern:'*.txt',path:'/workspace'}],
    ['bash', {command:`node --input-type=module -e '${boundary.replaceAll("'", "'\\''")}'`,description:'Verify container boundary through official shell'}],
    ['run_code', {code:`${boundary}\nconst fs2=await import('node:fs/promises'); await fs2.writeFile('/workspace/ptc.txt','ptc-child'); return await tools.read({file_path:'/workspace/probe.txt'});`,description:'Verify direct Node operations and nested official tool dispatch'}],
    ['read', {file_path:config.sentinel}, true],
    ['write', {file_path:'/opt/rsi/lib/index.js',content:'blocked'}, true],
  ];
  class Fixture extends LlmAdapter {
    async *stream(options) {
      requests.push({sessionId:options.sessionId,tools:options.tools?.map(t=>t.name)});
      const call=calls[requests.length-1];
      const block=call ? {type:'tool-call',id:`probe-${requests.length}`,name:call[0],arguments:JSON.stringify(call[1])} : {type:'text',text:'隔离检查完成。'};
      assert.ok(requests.length<=calls.length+1,'Unexpected fixture request');
      yield {type:'block-start',index:0,blockType:block.type};
      yield {type:'block-end',index:0,block};
      yield {type:'finish',reason:{kind:call?'tool-calls':'stop'}};
    }
  }
  ctx.effect(()=>ctx.llm.registerAdapter(['isolation-fixture'],new Fixture()));
  ctx.on('tools/result',(exec,result)=>results.push({name:exec.name,callId:exec.callId,...structuredClone(result)}));
  ctx.effect(()=>{
    const alive=setInterval(()=>{},1000);
    const timer=setTimeout(async()=>{
      try {
        await ctx.rsi.ready;
        const agent=await ctx.agents.create({sessionId:'isolation-probe',meta:{cwd:'/workspace'},agentOptions:{provider:'isolation-fixture',model:'fixture'}});
        agent.agent.followup(createUserMessage({content:[{type:'text',text:'检查容器内工具执行。'}],source:{kind:'user'}}));
        await agent.agent.whenIdle(); await ctx.sessions.flush(agent.agent.session);
        const top=results.filter(r=>/^probe-\d+$/.test(r.callId));
        assert.equal(top.length,calls.length,JSON.stringify(results));
        calls.forEach((call,i)=>assert.equal(top[i].isError===true,call[2]===true,JSON.stringify(top[i])));
        assert.equal(await readFile('/workspace/probe.txt','utf8'),'after\n');
        assert.equal(await readFile('/workspace/ptc.txt','utf8'),'ptc-child');
        for(const name of ['bash','run_code']) assert.ok(JSON.stringify(top.find(r=>r.name===name)).includes('BOUNDARY_PASS'));
        await assert.rejects(access(config.sentinel));
        const receipt={status:'PASS',shell:config.shell,node:process.version,platform:process.platform,arch:process.arch,uid:process.getuid(),fixtureDispatches:requests.length,realProviderRequests:0,executedTools:top.map(r=>({name:r.name,isError:r.isError===true})),toolSchemas:requests[0].tools,checks:['real-agent-dispatch','native-file-write-read-edit','native-search-subprocess','official-shell','native-ptc-direct-child-and-nested-tool','host-sentinel-absent','no-docker-socket','non-root-descendants','read-only-harness','network-denied'],limitation:'This no-network fixture proves execution containment, not real-model compatibility or benchmark effectiveness.'};
        await writeFile('/state/receipt.json',JSON.stringify(receipt,null,2));
        console.log(JSON.stringify(receipt)); process.exit(0);
      } catch(error) {console.error(error.stack); console.error(JSON.stringify({requests,results}));process.exit(1);}
    },0);
    return ()=>{clearTimeout(timer);clearInterval(alive);};
  });
}
