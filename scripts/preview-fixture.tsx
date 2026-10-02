import React from 'react';
import * as jsxRuntime from 'react/jsx-runtime';
import {createRoot} from 'react-dom/client';
const cwd='/workspace/dsh-rsi',id='fixture-workspace',now='2026-10-02T12:30:00Z';
const snapshot:any={workspace:{id,cwd},workspaces:[cwd,'/workspace/demo'],settings:{enabled:true,learningEnabled:true,language:'zh-CN',dailyCallBudget:100,maxTokens:4096,maxIterations:16,timeoutMs:180000,everyNConversations:2,idleSeconds:30,recallMaxChars:6000},usage:{calls:7,totalTokens:140,unknownUsage:0},layers:{[id]:{L0:4,L1:4,L2:2,L3:1},global:{L0:0,L1:2,L2:0,L3:1}},memory:[
{id:'mem-01',scope:id,scene_name:'插件开发',type:'instruction',content:'自进化技能使用 **独立目录**，以 `rsi-` 作为名称前缀。复制已有技能后，后续更新只写入副本。',sessionId:'plugin-development',updatedAt:now},
{id:'mem-02',scope:id,scene_name:'效果验证',type:'instruction',content:'使用同一题单、模型和调用预算，对完整插件与原始 dsh 进行配对 benchmark。保留请求、判分和失败原因。',sessionId:'evaluation-design',updatedAt:now},
{id:'mem-03',scope:id,scene_name:'任务执行',type:'fact',content:'实验任务应在容器里执行。正式运行前，需要核对文件、shell、子进程和网络入口的隔离边界。',sessionId:'sandbox-review',updatedAt:now},
{id:'mem-04',scope:id,scene_name:'测试流程',type:'experience',content:'先确认运行环境，再执行目标测试。失败时保存 **完整日志**，区分环境错误与任务失败。',sessionId:'test-workflow',updatedAt:now},
{id:'mem-05',scope:'global',scene_name:'语言偏好',type:'persona',content:'资产正文默认使用中文。代码、命令、路径及 API 标识保留原文。',sessionId:'preferences',updatedAt:now},
{id:'mem-06',scope:'global',scene_name:'协作习惯',type:'instruction',content:'持续推进已明确的工作，并记录可检查的实现和验证结果。',sessionId:'preferences',updatedAt:now}],skills:[
{scope:id,skill_id:'skill-testing',name:'testing',visibleName:'rsi-testing',version:3,description:'验证测试环境，执行目标测试，保留失败证据。',disabled:false,updated_at_ms:now},
{scope:id,skill_id:'skill-plugin',name:'plugin-integration',visibleName:'rsi-plugin-integration',version:2,description:'沿宿主真实调用链验证插件加载与资产消费。',disabled:false,updated_at_ms:now},
{scope:'global',skill_id:'skill-review',name:'review-notes',visibleName:'rsi-review-notes',version:1,description:'从任务记录中整理可追溯的经验与纠正。',disabled:true,updated_at_ms:now}],jobs:[{id:'job-1',status:'completed',sourceSessionId:'test-workflow',turn:1,updated:Date.parse(now)}]};
const bodies:any={'skill-testing':`---
name: testing
description: 验证测试环境，执行目标测试，保留失败证据。
---
# 工作区测试流程

在修改完成后验证目标行为，并保存能够复查的测试证据。

## 何时使用

修改代码、修复缺陷或调整插件集成行为之后。

## 执行步骤

1. **确认环境**：检查运行版本、依赖和工作目录。
2. **运行目标测试**：先执行与本次改动直接相关的测试。
3. **分析失败**：区分环境错误和任务行为错误，保留完整日志。
4. **记录结论**：说明测试范围、结果及仍未验证的部分。

\`\`\`bash
npm run build
npm run test:runtime
\`\`\`

## 结果记录

| 情况 | 处理方式 |
| --- | --- |
| 目标测试通过 | 记录实际通过的检查 |
| 环境不可用 | 标记环境问题，保留诊断 |
| 行为不符合预期 | 修复后重新验证目标行为 |

> 测试通过只能证明已覆盖的行为；不能代替真实 benchmark 的效果结论。`,
'skill-plugin':'---\nname: plugin-integration\ndescription: 验证真实调用链\n---\n# 插件集成检查\n\n## 验证链路\n\n- 插件加载与服务挂载\n- 任务结束事件与源日志\n- 原生提炼和资产写入\n- 后续请求实际读取记忆与技能\n',
'skill-review':'---\nname: review-notes\ndescription: 整理任务经验\n---\n# 任务经验整理\n\n保存来源、具体行为与修正依据。'};
const resources=[{path:'references/test-checklist.md',size_bytes:412},{path:'scripts/check-environment.sh',size_bytes:236}];
const ctx:any={inject:(_deps:any,fn:any)=>fn(ctx),effect:(fn:any)=>fn(),locale:{register:()=>()=>{}},slots:{inject:(_name:any,fn:any)=>fn(),register:(spec:any,component:any)=>{if(spec.name!=='plugins.bundle.config'||spec.key!=='dsh-rsi')throw Error('wrong keyed slot');createRoot(document.getElementById('root')!).render(React.createElement(component));return()=>{};}},remote:{$mount:async()=>()=>{},rsi:{request:async(operation:string,payload:any)=>{
 document.getElementById('receipt')!.textContent=JSON.stringify({operation,payload});
 const row=snapshot.skills.find((s:any)=>s.skill_id===payload.id&&s.scope===payload.scope);
 let value:any=snapshot;
 if(operation==='settings')Object.assign(snapshot.settings,payload.settings);
 if(operation==='disable')row.disabled=payload.disabled;
 if(operation==='editMemory')snapshot.memory.find((m:any)=>m.id===payload.id).content=payload.content;
 if(operation==='deleteMemory')snapshot.memory=snapshot.memory.filter((m:any)=>m.id!==payload.id);
 if(operation==='editSkill'){if(row.version!==payload.expectedVersion)return {ok:false,error:{message:'版本冲突，请重新打开技能'}};bodies[payload.id]=payload.content;row.version++;}
 if(operation==='skill')value={...row,content:bodies[payload.id],manifest:payload.id==='skill-testing'?resources:[]};
 if(operation==='versions')value={items:[{version:row.version,content:bodies[payload.id],manifest:resources},{version:1,content:'---\nname: testing\ndescription: 初始测试流程\n---\n# 初始测试流程\n\n运行目标测试并保存日志。',manifest:[],is_expired:false}]};
 if(operation==='skillFile')value={path:payload.path,version:payload.version,size_bytes:412,binary:false,content:payload.path.endsWith('.sh')?'#!/bin/sh\nnode --version\nnpm --version\n':'# 测试检查清单\n\n- 核对工作目录和运行版本\n- 保存完整失败日志\n- 记录测试范围与结果\n'};
 if(operation==='memoryLayer'){
 const items=payload.scope==='global'?payload.layer==='L3'?[{id:'persona',content:'## 语言与协作偏好\n\n默认使用中文，技术标识保持原文。希望工作持续推进，并留下可验证的结果。'}]:[]:payload.layer==='L0'?[
 {record_id:'raw-1',role:'user',message_text:'完成修改后，先检查环境，再运行目标测试。失败时保留完整日志。',session_id:'test-workflow',timestamp:Date.parse(now)-50000},
 {record_id:'raw-2',role:'assistant',message_text:'已确认 Node 与依赖版本。下一步执行目标测试并记录结果。',session_id:'test-workflow',timestamp:Date.parse(now)-40000},
 {record_id:'raw-3',role:'user',message_text:'效果通过完整插件与原始 dsh 的 benchmark 对比验证。',session_id:'evaluation-design',timestamp:Date.parse(now)-30000},
 {record_id:'raw-4',role:'assistant',message_text:'使用相同题单、模型和预算，保留判分与失败原因。',session_id:'evaluation-design',timestamp:Date.parse(now)-20000},
 ].reverse():payload.layer==='L2'?[
 {filename:'测试流程.md',summary:'环境检查与失败日志',heat:4,updated:now,content:'## 目标测试的执行约定\n\n先确认环境，再执行相关测试。\n\n- 保存完整失败日志\n- 区分环境问题与任务失败\n- 明确结论所覆盖的行为'},
 {filename:'插件集成.md',summary:'源日志与资产消费',heat:2,updated:now,content:'## 集成链路\n\n从任务结束事件触发学习，读取持久源日志。生成的记忆与技能必须在后续真实请求中被消费。'}]:payload.layer==='L3'?[{id:'persona',content:'## 工作方式\n\n倾向于先明确产品范围，再持续实现。要求保留原生算法与可追溯的证据。\n\n## 验证偏好\n\n关注完整系统在 benchmark 中是否有效，实验任务使用隔离环境。'}]:[];
 value={items,total:items.length};
 }
 if(operation==='originalSkills')value=[{name:'test-helper',description:'已有测试技能'}];
 if(operation==='export')value={format:'dsh-rsi-preview-fixture',memory:snapshot.memory,skills:snapshot.skills};
 return {ok:true,value:structuredClone(value)};
 }}}};
(window as any).__ModuleLoader__={load:({id,factory}:any)=>{if(id!=='dsh-rsi')throw Error('wrong package');factory((name:string)=>{if(name==='react')return React;if(name==='react/jsx-runtime')return jsxRuntime;throw Error('unexpected external '+name);}).apply(ctx);}};
const script=document.createElement('script');script.src='/client.js';document.body.appendChild(script);
