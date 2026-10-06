import vm from 'node:vm';
import assert from 'node:assert/strict';
import {readFile,mkdtemp,rm,writeFile} from 'node:fs/promises';
import * as fs from 'node:fs';
import {createHash} from 'node:crypto';
import {dirname,join} from 'node:path';
import {fileURLToPath} from 'node:url';
const repo=dirname(dirname(fileURLToPath(import.meta.url))),output=process.argv[2];assert.ok(output);
const source=await readFile(join(repo,'scripts/personamem-pilot-task.mjs'),'utf8');
const root=await mkdtemp('/private/tmp/dsh-rsi-persona-observer-'),messages=[{role:'user',content:[{type:'text',text:'fixture'}]}];
// This isolates only the observer. Persistent-log restoration is an explicit fixture, not a native claim.
const module=new vm.SourceTextModule(source);const synthetic=values=>new vm.SyntheticModule(Object.keys(values),function(){for(const [key,value] of Object.entries(values))this.setExport(key,value);});
const mapPath=path=>typeof path==='string'&&path.startsWith('/state/pilot/')?root+path.slice('/state/pilot'.length):path;
try {
 await module.link(async name=>{
  if(name==='@deepseek-ai/dsh-session')return synthetic({Session:{fromRestore(){return{deriveMessages(){return messages;}}}}});
  if(name==='@deepseek-ai/dsh-llm')return synthetic({createUserMessage:x=>x,LlmAdapter:class{}});
  if(name==='./personamem-history.mjs')return synthetic({appendPersonaHistory(){},personaHistoryContext(){},importedHistoryTimeNote:'fixture'});
  if(name==='node:fs'){const wrapped={...fs};for(const key of ['mkdirSync','writeFileSync','openSync'])wrapped[key]=(path,...args)=>fs[key](mapPath(path),...args);wrapped.renameSync=(a,b)=>fs.renameSync(mapPath(a),mapPath(b));return synthetic(wrapped);}
  return synthetic(await import(name));
 });await module.evaluate();let interceptor;
 module.namespace.apply({on(name,fn){if(name==='llm/stream')interceptor=fn;},effect(){},sessions:{get(){return null;}},sessionPersistence:{async open(){return{header:{},inheritedEventCount:0,async read(){return{events:[],eventState:{}};},async close(){}};}}},{instanceId:'fixture',dispatchLimit:20,learningDispatchLimit:0});
 const cases=[['stop',20,'RETURNED',true],['tool-calls',20,'RETURNED',true],['stop',0,'RETURNED',false],['aborted',0,'INCOMPLETE',false],['max-tokens',null,'INCOMPLETE',false],['error',-1,'INCOMPLETE',false],[null,null,'INCOMPLETE',false],['stop',NaN,'RETURNED',false],['stop',Infinity,'RETURNED',false],['stop','20','RETURNED',false]];
 for(const [kind,total,status,known] of cases){
  for await(const _ of interceptor({sessionId:'persona-fixture',messages},async function*(){yield{type:'text-delta',index:0,text:'retained partial output'};if(total!==null)yield{type:'usage',usage:{totalTokens:total}};if(kind)yield{type:'finish',reason:{kind}};})){}
  const rows=JSON.parse(await readFile(root+'/fixture/model-requests.json','utf8')),row=rows.at(-1);assert.equal(row.status,status);assert.equal(row.finish?.kind,kind??undefined);assert.equal(row.responseBlocks['0'],'retained partial output');assert.equal(module.namespace.hasKnownPersonaUsage(row),known);
 }
 await assert.rejects(async()=>{for await(const _ of interceptor({sessionId:'persona-fixture',messages},async function*(){throw Error('observer transport fixture');})){};},/observer transport fixture/);
 const cancellationControls=[];
 // A native question timeout closes the async generator before its post-loop assignment.
 for(const [closeAfter,total,expectedStatus] of [['text-delta',null,'INCOMPLETE'],['usage',20,'INCOMPLETE'],['finish',null,'RETURNED']]){
  let providerFinally=false;
  const iterator=interceptor({sessionId:'persona-fixture',messages},async function*(){try{yield{type:'text-delta',index:0,text:'retained cancellation output'};if(total!==null)yield{type:'usage',usage:{totalTokens:total}};yield{type:'finish',reason:{kind:'stop'}};}finally{providerFinally=true;}});
  while((await iterator.next()).value?.type!==closeAfter){}
  await iterator.return();
  const row=JSON.parse(await readFile(root+'/fixture/model-requests.json','utf8')).at(-1);
  assert.ok(providerFinally);assert.equal(row.status,expectedStatus);assert.ok(row.finishedAt>=row.observedAt);assert.equal(row.responseBlocks['0'],'retained cancellation output');assert.equal(row.finish?.kind,closeAfter==='finish'?'stop':undefined);assert.equal(module.namespace.hasKnownPersonaUsage(row),total!==null);
  cancellationControls.push({closeAfter,status:row.status,knownUsage:total!==null,finishedAtRecorded:true,providerGeneratorClosed:true});
 }
 const rows=JSON.parse(await readFile(root+'/fixture/model-requests.json','utf8'));assert.equal(rows[10].status,'ERROR');assert.equal(rows.length,14);assert.equal(rows.filter(module.namespace.hasKnownPersonaUsage).length,3);
 const receipt={status:'PASS_PERSONAMEM_OBSERVER_CONTROLS',driverSha256:createHash('sha256').update(source).digest('hex'),controls:cases.map(([kind,total,status,known])=>({kind,total:Number.isFinite(total)?total:typeof total==='string'?total:null,status,knownUsage:known})),cancellationControls,transportErrorPreserved:true,partialTextRetained:true,knownTokens:rows.reduce((n,r)=>n+(module.namespace.hasKnownPersonaUsage(r)?r.usage.totalTokens:0),0),unknownUsageEntries:rows.filter(r=>!module.namespace.hasKnownPersonaUsage(r)).length,fixtureStreamInvocations:14,realModelRequests:0,persistenceRestorationFixture:true,scope:'Only observer finish/usage/partial-output accounting; native durable-log proof is recorded separately.'};
 await writeFile(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify({status:receipt.status,knownTokens:receipt.knownTokens,unknownUsageEntries:receipt.unknownUsageEntries,realModelRequests:0}));
}finally{await rm(root,{recursive:true,force:true});}
