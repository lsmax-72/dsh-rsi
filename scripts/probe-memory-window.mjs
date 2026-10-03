import {fixtureEmbedding} from './fixture-embedding.mjs';
import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {openLocalCore} from '../lib/local-core.js';
const directory=await mkdtemp(join(tmpdir(),'rsi-memory-window-'));
const content='以后讨论本项目的测试方案时，请保留完整失败日志并用中文说明局限。';
const messages=[{id:'user-requirement',role:'user',content,timestamp:Date.now()},
 ...Array.from({length:16},(_,i)=>({id:`assistant-${i}`,role:'assistant',content:`第 ${i+1} 步已经检查了测试入口与命令参数，继续核对相关代码。`,timestamp:Date.now()+i+1}))];
let calls=0;
const runner={async run(params){
 calls++;
 const pending=params.prompt.split('【待提取的新消息】')[1];
 assert.ok(pending?.includes('[user-requirement] [user]'), 'Original user input was dropped or treated only as background');
 assert.ok(pending.includes(content));
 assert.ok(pending.includes('[assistant-15]'));
 return JSON.stringify([{scene_name:'中文测试流程约定',message_ids:['user-requirement'],memories:[{content,type:'instruction',priority:70,source_message_ids:['user-requirement'],metadata:{}}]}]);
}};
let core;
try{
 core=await openLocalCore(directory,runner,{debug(){},info(){},warn(){},error(){}},fixtureEmbedding());
 await core.record({sessionKey:'window-regression',sessionId:'window-regression',rawMessages:messages});
 const result=await core.extractMemories({sessionKey:'window-regression',sessionId:'window-regression',messages});
 assert.equal(result.storedCount,1);const saved=await core.readMemories();assert.equal(saved[0].content,content);assert.deepEqual(saved[0].source_message_ids,['user-requirement']);assert.equal(calls,1);
 console.log(JSON.stringify({status:'PASS',sourceMessages:messages.length,retainedUserId:'user-requirement',storedMemories:1,fixtureRequests:calls,realModelRequests:0}));
}finally{core?.close();await rm(directory,{recursive:true,force:true});}
