import vm from 'node:vm';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdtemp,rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
const repo=process.env.RSI_PROBE_PROJECT??dirname(dirname(fileURLToPath(import.meta.url)));
const output=process.argv[2];assert.ok(output,'Diagnostic output path required');
const path=join(repo,'scripts/review-development-skill.mjs');const source=await readFile(path,'utf8');
const module=new vm.SourceTextModule(source);
const messages=[{role:'user',content:[{type:'text',text:'fixture source'}]}];
await module.link(async name=>{if(name==='@deepseek-ai/dsh-session'){const stub=new vm.SyntheticModule(['Session'],function(){this.setExport('Session',{fromRestore(){return{deriveMessages(){return messages;}}}});});return stub;}const imported=await import(name);return new vm.SyntheticModule(Object.keys(imported),function(){for(const key of Object.keys(imported))this.setExport(key,imported[key]);});});await module.evaluate();
const root=await mkdtemp('/private/tmp/dsh-rsi-finish-audit-');let interceptor;let closed=0;const ctx={on(_name,fn){interceptor=fn;},effect(){},sessionPersistence:{async open(){return{header:{},inheritedEventCount:0,async read(){return{events:[],eventState:{}};},async close(){closed++;}};}}};module.namespace.apply(ctx,{root,callLimit:10});
const cases=[['stop','RETURNED'],['tool-calls','RETURNED'],['error','INCOMPLETE'],['aborted','INCOMPLETE'],['max-tokens','INCOMPLETE'],[null,'INCOMPLETE']];
try {
 for(const [kind,status] of cases){const stream=interceptor({sessionId:'rsi-fixture',messages},async function*(){if(kind)yield{type:'finish',reason:{kind,...(kind==='error'?{failure:{code:'MISSING_CREDENTIAL'}}:{})}};});for await(const _ of stream){};const rows=JSON.parse(await readFile(root+'/review-requests.json','utf8'));assert.equal(rows.at(-1).status,status);assert.equal(rows.at(-1).finishReason?.kind,kind??undefined);}
 await assert.rejects(async()=>{for await(const _ of interceptor({sessionId:'rsi-fixture',messages},async function*(){throw Error('transport fixture failure');})){};},/transport fixture failure/);
 let rows=JSON.parse(await readFile(root+'/review-requests.json','utf8'));assert.equal(rows.at(-1).status,'ERROR');assert.equal(rows.at(-1).error,'transport fixture failure');
 await assert.rejects(async()=>{for await(const _ of interceptor({sessionId:'pilot-task',messages},async function*(){throw Error('should not dispatch');})){};},/must not dispatch a task solver/);
 assert.equal(JSON.parse(await readFile(root+'/review-requests.json','utf8')).length,7);assert.equal(closed,7);
 const receipt={status:'PASS_NATIVE_REVIEW_FINISH_DIAGNOSTICS',reviewPluginSha256:createHash('sha256').update(source).digest('hex'),finishControls:cases.map(([kind,status])=>({kind,status})),thrownTransportErrorRetained:true,taskSolverSessionRejectedBeforeDispatch:true,realModelRequests:0,fixtureStreamInvocations:7,sessionPersistenceFixture:true,productionBridgeChanged:false};await writeFile(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{await rm(root,{recursive:true,force:true});}
