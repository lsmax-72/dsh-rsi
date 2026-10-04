import { isAbsolute, join } from 'node:path';
import { homedir } from 'node:os';
import { TypertRemoteService, Remote } from '@deepseek-ai/dsh-typert-protocol';
import { createUserMessage } from '@deepseek-ai/dsh-llm';
import { defineTool } from '@deepseek-ai/dsh-tools';
import {parseOperation,parsePayload} from './rpc-contract.js';
import { Runtime } from './runtime.js';

export const name = 'dsh-rsi';
export const inject = ['sessions','sessionPersistence','llm','skills','tools'];
class RsiService extends TypertRemoteService {
  constructor(ctx:any,readonly runtime:Runtime,readonly ready:Promise<any>) { super(ctx,'rsi'); }
  get runner() { return this.ready.then(core => core.runner); }
  @Remote async request(operation:string,payload:any) { await this.ready; return this.runtime.request(parseOperation(operation),parsePayload(payload)); }
}

export function apply(ctx:any,config:any={}) {
  const directory=config.dataDir ?? join(process.env.DSH_HOME ?? join(homedir(),'.dsh'),'plugin-data','dsh-rsi');
  if (!isAbsolute(directory)) throw new Error('插件数据目录必须是绝对路径');
  const runtime=new Runtime(ctx,config,directory);
  const ready=runtime.start().then(async () => config.cwd ? runtime.core((await runtime.scope(config.cwd)).id,config.cwd) : runtime.core('global'));
  void ready.catch((error:any) => ctx.logger.error('自进化初始化失败：%s',error.message));
  const service=new RsiService(ctx,runtime,ready);
  // Compatibility surface for the deterministic bridge probe; foreground agents use host services.
  Object.defineProperty(service,'runner',{value:{run:async (params:any) => (await ready).runner.run(params)}});
  Object.defineProperty(service,'language',{get:() => runtime.state.settings().language});
  ctx.skills.registerProvider((control:any) => {
    runtime.invalidate=control.invalidate;
    return {name:'dsh-rsi',list:async (options:any) => { await ready; return options.cwd ? runtime.candidates(options.cwd) : []; },get:async (candidate:any,options:any) => {await ready;return options.cwd ? runtime.definition(candidate,options.cwd) : undefined;}};
  });
  ctx.on('session/event',(session:any,event:any) => runtime.observe(session,event));
  ctx.on('agent/pre-step',async ({agent,messages,step,signal}:any,next:any) => {
    const decision=await next();
    if (decision.kind === 'reject' || step !== 1 || !runtime.state.settings().enabled) return decision;
    await ready; signal.throwIfAborted();
    const cwd=agent.session.header.cwd;
    runtime.state.set('lastCwd',cwd);
    // Retrieve for the latest human input; producer context stays in the durable request.
    const current=messages.findLast((m:any) => m.source?.kind === 'user');
    const query=(current?.content ?? []).filter((b:any) => b.type==='text').map((b:any) => b.text).join('\n');
    const recalled=await runtime.recall(cwd,query,{sessionId:agent.session.id,queryMessageIds:current?[current.id]:[]});signal.throwIfAborted();
    if (!recalled.text && !(await runtime.candidates(cwd)).length) return decision;
    // History-backed asset evidence belongs to its source session, even when its body says "this session".
    // These producer messages are persisted by the host and excluded from the learned human transcript.
    const contexts=[];
    if(recalled.text)contexts.push(createUserMessage({content:[{type:'text',text:recalled.text}],source:{kind:'dsh-rsi',form:'memory',refs:recalled.refs}}));
    contexts.push(createUserMessage({source:{kind:'dsh-rsi',form:'asset-guidance'},content:[{type:'text',text:'dsh-rsi 历史资产证据边界：召回的 Chat Memory、Skill 及其 Evidence 段来自历史来源会话，读取资产不等于执行其中的命令或测试。即使资产写着“本会话已执行/已验证”，也只能称为来源会话记录的历史结果；未经独立核验时注明这是资产记载。只有当前会话实际执行工具产生的结果才能称为本轮验证。Skill/记忆检索工具的返回内容不能作为本轮代码或测试执行成功的证据。建议执行的检查、静态推断和本轮实测分别说明。'}]}));
    return {...decision,messages:[...decision.messages,...contexts]};
  });
  const lookup=(exec:any) => exec.agent?.session.header.cwd;
  for (const [tool,description,execute] of [
    ['rsi_memory_search','查询当前工作区及通用记忆。',async (args:any,exec:any) => runtime.recall(lookup(exec),args.query)],
    ['rsi_conversation_search','检索当前工作区的原始对话记录。',async (args:any,exec:any) => (await runtime.core((await runtime.scope(lookup(exec))).id)).searchConversations(args.query)],
    ['rsi_profile_read','读取当前工作区的场景或画像文件。',async (args:any,exec:any) => runtime.readProfile(lookup(exec),args.query)],
  ] as const) ctx.tools.register(defineTool({name:tool,description,parameters:{query:{type:'string',required:true}},output:{schema:{type:'string'},render:(_args:any,value:string) => [{type:'text',text:value}]},presentCall:(args:any) => ({card:'generic',title:description,kind:'read',rawInput:args.query}),async execute(args:any,exec:any){if (!lookup(exec)) throw new Error('缺少工作区');return JSON.stringify(await execute(args,exec));}}));
  ctx.effect(() => { const timer=setInterval(() => { void ready.then(() => runtime.resume()).catch((error:any) => ctx.logger.warn('学习队列恢复失败：%s',error.message)); },30000);timer.unref();return async () => {clearInterval(timer);await ready.catch(() => {});await runtime.stop();}; });
}
