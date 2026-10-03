import { AsyncLocalStorage } from 'node:async_hooks';
import { mkdir, writeFile, rm, readdir } from 'node:fs/promises';
import { join,relative,resolve,isAbsolute } from 'node:path';
import { DshModelRunner } from './model-bridge.js';
import { openLocalCore } from './local-core.js';
import { MemoryPipelineManager, parseSkillFile, buildFtsQuery } from './core-entry.js';
import { copyResources,versionResources } from './resources.js';
import { State, workspace, type Settings } from './state.js';
import { listAllSkills, listAllVersions } from './asset-pages.js';
import { fitRecallScope, recallToolGuide } from './recall-context.js';
import { createReadyEmbedding } from './native-embedding.js';
import { FileLogger, withLocalDiagnostics, diagnosticEvent } from '../adapters/local-observability.js';

const ids = (scope: string) => ({ user_id:'local-user', team_id:scope, agent_id:'local-agent' });
const text = (message: any) => (message?.content ?? []).map((block: any) => block.type === 'text' ? block.text : JSON.stringify(block)).join('\n');
const visibleName = (name: string) => `rsi-${name}`;
// The pinned native manager owns five retries; persist its six-attempt ceiling across restarts.
const MAX_JOB_ATTEMPTS = 6;
const retryableJob = (job:any) => job.status === 'failed' && job.stages.failure?.retryable && job.stages.failure.attempts < MAX_JOB_ATTEMPTS;

/** Host adaptation: durable work, physical scopes, budgets and official consumers. */
export class Runtime {
  readonly state: State;
  readonly abort = new AbortController();
  readonly context = new AsyncLocalStorage<any>();
  readonly cores = new Map<string,Promise<any>>();
  readonly diagnosticSinks = new Map<string,FileLogger>();
  readonly pipelines = new Map<string,any>();
  readonly active = new Set<Promise<any>>();
  readonly notified = new Set<string>();
  readonly blockedScopes = new Set<string>();
  embeddingPromise?:Promise<any>;
  stopping = false;
  invalidate = () => {};
  captureQueue: Promise<any> = Promise.resolve();
  constructor(readonly ctx: any, readonly config: any, readonly directory: string, readonly suppliedEmbedding?:any) {
    this.state = new State(directory, config.settings);
  }
  tracked<T>(promise: Promise<T>): Promise<T> { this.active.add(promise); void promise.finally(() => this.active.delete(promise)).catch(() => {}); return promise; }
  route(scope: string) { return this.config.provider && this.config.model ? { provider:this.config.provider, model:this.config.model } : this.context.getStore()?.route ?? this.state.get(`route:${scope}`); }
  async core(scope: string, cwd?: string) {
    if (this.blockedScopes.has(scope)) throw new Error('所选资产正在维护');
    if (!this.cores.has(scope)) {
      const directory = join(this.directory,'scopes',scope);
      const runner = {
        run: (params: any) => {
          if (this.stopping || this.blockedScopes.has(scope)) return Promise.reject(new Error('插件正在关闭'));
          const settings = this.state.settings();
          const origin = this.context.getStore();
          const bridge = new DshModelRunner(this.ctx, {
            cwd:cwd ?? this.config.cwd ?? this.directory,
            resolveRoute:() => { const route = this.route(scope); if (!route) throw Object.assign(new Error('尚无会话模型配置'), { code:'MISSING_ROUTE' }); return route; },
            maxTokens:settings.maxTokens, timeoutMs:settings.timeoutMs, maxIterations:settings.maxIterations,
            language:() => origin?.language ?? this.state.settings().language,
            onSession:async (sessionId,taskId,sourceSessionId) => {
              const root = join(this.directory,'learning-runs'); await mkdir(root,{ recursive:true });
              await writeFile(join(root,`${sessionId}.json`),JSON.stringify({ sessionId,taskId,sourceSessionId,jobId:origin?.jobId,scope,createdAt:Date.now() })+'\n',{ flag:'wx',mode:0o600 });
            },
            beforeRequest:(id,task) => this.state.reserve(id,scope,task,!!origin?.manual),
            afterRequest:(id,usage,status) => this.state.settle(id,usage,status),
          });
          return this.tracked(bridge.run({ ...params, sessionId:params.sessionId ?? origin?.sessionId, abortSignal:AbortSignal.any([this.abort.signal,...(params.abortSignal?[params.abortSignal]:[])]),
            maxTokens:Math.min(params.maxTokens ?? settings.maxTokens,settings.maxTokens), maxIterations:Math.min(params.maxIterations ?? settings.maxIterations,settings.maxIterations),timeoutMs:Math.min(params.timeoutMs ?? settings.timeoutMs,settings.timeoutMs) }));
        },
      };
      this.embeddingPromise ??= this.suppliedEmbedding?Promise.resolve(this.suppliedEmbedding):createReadyEmbedding(this.config.embedding,this.directory,this.ctx.logger);
      const promise = this.embeddingPromise.then(embedding=>openLocalCore(directory,runner,this.ctx.logger,embedding)).then(core => ({ ...core,runner,scope,directory }));
      this.cores.set(scope,promise);
      void promise.catch(() => this.cores.delete(scope));
    }
    return this.cores.get(scope)!;
  }
  async scope(cwd: string) {
    const entry = workspace(cwd);
    this.state.set(`scope:${entry.id}`,entry);
    await this.core(entry.id,entry.cwd);
    if (!this.pipelines.has(entry.id)) await this.createPipeline(entry.id);
    return entry;
  }
  async within<T>(scope: string, operation: () => Promise<T>, origin: any = {}) {
    if(!this.diagnosticSinks.has(scope))this.diagnosticSinks.set(scope,new FileLogger({path:join(this.directory,'scopes',scope,'diagnostics'),filename:'observability.log',rotateSizeBytes:100*1024*1024,rotateBackupLimit:10}));
    return withLocalDiagnostics(this.diagnosticSinks.get(scope)!,{scope,source_session_id:origin.sessionId,job_id:origin.jobId},()=>this.context.run({route:this.state.get(`route:${scope}`),...origin},operation));
  }
  async createPipeline(scope: string) {
    const settings = this.state.settings();
    const pipeline = new MemoryPipelineManager({ everyNConversations:settings.everyNConversations,enableWarmup:true,
      l1:{ idleTimeoutSeconds:settings.idleSeconds },l2:{ delayAfterL1Seconds:this.config.l2DelaySeconds ?? 30,minIntervalSeconds:300,maxIntervalSeconds:3600,sessionActiveWindowHours:24 } },this.ctx.logger);
    this.pipelines.set(scope,pipeline);
    pipeline.setL1Runner(async ({sessionKey}: any) => this.within(scope,() => this.process(scope,sessionKey)));
    pipeline.setL2Runner(async (_key: string,cursor: string) => this.tracked(this.within(scope,async () => {
      const core = await this.core(scope);
      const invalid=!!this.state.get(`profile-invalid:${scope}`);if(invalid)await rm(join(core.directory,'profile'),{recursive:true,force:true});
      const result = await core.extractScenes(invalid?'':cursor);
      const global = await this.core('global');
      const globalInvalid=!!this.state.get('profile-invalid:global');if(globalInvalid)await rm(join(global.directory,'profile'),{recursive:true,force:true});
      const globalResult = await global.extractScenes(globalInvalid?'':(this.state.get('global-l2-cursor') ?? ''));
      if (!globalResult.skipped) { await global.generatePersona(); this.state.set('global-l2-cursor',globalResult.latestCursor);this.state.set('profile-invalid:global',0); }
      return result;
    })));
    pipeline.setL3Runner(async () => this.tracked(this.within(scope,async () => {
      const started = Date.now(); const generated=await (await this.core(scope)).generatePersona();
      if (generated && (this.state.get<number>(`profile-invalid:${scope}`) ?? 0) <= started) this.state.set(`profile-invalid:${scope}`,0);
      this.invalidate();
    })));
    pipeline.setPersister(async (states: any) => this.state.set(`pipeline:${scope}`,states));
    pipeline.start(this.state.get(`pipeline:${scope}`));
  }
  async start() {
    await this.core('global');
    for (const source of this.state.sources()) await this.captureStored(source.id,source.cwd).catch(error => this.ctx.logger.warn('会话恢复暂不可用：%s',error.message));
    await this.resume(true);
  }
  async resume(recoverFailures = false) {
    const settings = this.state.settings();
    if (!settings.enabled || !settings.learningEnabled || this.stopping || Number(this.state.usage().calls) >= settings.dailyCallBudget) return;
    for (const job of this.state.jobs().filter(job => ['pending','paused','interrupted'].includes(job.status) || (recoverFailures && retryableJob(job)))) {
      const entry = await this.scope(job.payload.cwd);
      if (this.notified.has(job.id) || !(job.payload.route ?? this.route(entry.id))) continue;
      this.notified.add(job.id);this.state.updateJob(job.id,'pending');
      this.pipelines.get(entry.id).notifyConversation(job.session,job.payload.messages.filter((m:any) => ['user','assistant'].includes(m.role)));
    }
  }
  observe(session: any,event: any) {
    if (this.stopping || session.id.startsWith('rsi-') || !this.state.settings().enabled) return;
    if (event.type !== 'turn/end' || !['completed','error','max-tokens','blocked'].includes(event.data.reason.kind)) return;
    const cwd = session.header.cwd;
    this.state.rememberSource(session.id,cwd);
    // Observer callbacks cannot reenter Session.append. Persistence reads run after publication.
    this.captureQueue = this.captureQueue.then(async () => {
      await this.ctx.sessions.flush(session);
      await this.captureStored(session.id,cwd);
    }).catch(error => this.ctx.logger.error('任务轨迹保存失败：%s',error.message));
  }
  async captureStored(sessionId: string,cwd: string) {
    const handle = await this.ctx.sessionPersistence.open(sessionId,'read');
    try {
      const { events } = await handle.read();
      const entry = await this.scope(cwd);
      const source = this.state.sources().find(row => row.id === sessionId);
      let start = -1, route: any;
      for (let index=0;index<events.length;index++) {
        const event = events[index];
        if (event.type === 'request/header') route = event.data.header.config;
        if (event.type === 'turn/start') start = index;
        if (event.type !== 'turn/end' || start < 0 || event.seq <= (source?.cursor ?? -1)) continue;
        if (!['completed','error','max-tokens','blocked'].includes(event.data.reason.kind)) continue;
        const trace = events.slice(start,index+1);
        if (!trace.some((e:any) => e.type === 'user/message' && e.data.source?.kind === 'user')) continue;
        const messages: any[] = [];
        for (const e of trace) {
          if (e.type === 'user/message' && e.data.source?.kind === 'user') messages.push({ id:e.data.id,role:'user',content:text(e.data),timestamp:new Date(e.time).toISOString() });
          if (e.type === 'assistant/message') {
            messages.push({ id:e.data.message.id,role:'assistant',content:text(e.data.message),timestamp:new Date(e.time).toISOString() });
          }
          if (e.type === 'tool/call') messages.push({role:'tool_call',content:JSON.stringify(e.data),timestamp:new Date(e.time).toISOString()});
          if (e.type === 'tool/result') messages.push({role:'tool_result',content:text(e.data.message),timestamp:new Date(e.time).toISOString()});
        }
        if (!messages.some(m => m.role === 'user' && m.content.trim())) continue;
        const selected = this.config.provider && this.config.model ? {provider:this.config.provider,model:this.config.model} : route;
        if (selected) {const chosen={provider:selected.provider,model:selected.model,reasoningEffort:selected.reasoningEffort};this.state.set(`route:${entry.id}`,chosen);this.state.set('route:global',chosen);}
        const added = this.state.enqueue({scope:entry.id,cwd:entry.cwd,sessionId,turn:event.data.turn,endSeq:event.seq,reason:event.data.reason,route:selected,messages,events:trace});
        if (added && this.state.settings().learningEnabled) { this.notified.add(`${sessionId}:${event.data.turn}`); await this.pipelines.get(entry.id).notifyConversation(sessionId,messages.filter(m => ['user','assistant'].includes(m.role))); }
        start = -1;
      }
    } finally { await handle.close(); }
  }
  async process(scope: string,sessionId: string) {
    const core = await this.core(scope);
    const sessionJobs = this.state.jobs(scope).filter(job => job.session === sessionId);
    const jobs = sessionJobs.filter(job => ['pending','paused','interrupted'].includes(job.status) || retryableJob(job));
    if (!jobs.length) {
      const blocked = sessionJobs.find(job => job.status !== 'completed');
      if (blocked) throw Object.assign(new Error(blocked.error ?? '学习任务等待手动重试'),{code:blocked.stages.failure?.code ?? 'RETRY_LIMIT'});
      return {processedCount:0,profileScopes:[]};
    }
    for (const job of jobs) {
      this.state.updateJob(job.id,'running');
      this.notified.delete(job.id);const stages = job.stages;
      try {
        const settings=this.state.settings();
        if(this.stopping)throw Object.assign(new Error('插件正在关闭'),{code:'INTERRUPTED'});
        if(!settings.enabled || !settings.learningEnabled)throw Object.assign(new Error('自动学习已暂停'),{code:'LEARNING_PAUSED'});
        if(Number(this.state.usage().calls)>=settings.dailyCallBudget)throw Object.assign(new Error('今日学习调用预算已用完'),{code:'BUDGET_EXHAUSTED'});
        if(!(job.payload.route ?? this.route(scope)))throw Object.assign(new Error('尚无会话模型配置'),{code:'MISSING_ROUTE'});
        stages.failure={...stages.failure,attempts:(stages.failure?.attempts ?? 0)+1};
        this.state.updateJob(job.id,'running',stages);
        await this.within(scope,async () => {
          if (!stages.recorded) {
            const rawMessages = job.payload.messages.filter((m:any) => ['user','assistant'].includes(m.role)).map((m:any) => ({...m,timestamp:Date.parse(m.timestamp)}));
            await core.record({sessionKey:sessionId,sessionId,rawMessages});
            stages.recorded=true; this.state.updateJob(job.id,'running',stages);
          }
          if (!stages.memory) {
            const messages = job.payload.messages.filter((m:any) => ['user','assistant'].includes(m.role)).map((m:any) => ({...m,timestamp:Date.parse(m.timestamp)}));
            const result = await core.extractMemories({messages,sessionKey:sessionId,sessionId});
            const global = await this.core('global');
            for (const record of result.records.filter((r:any) => r.type === 'persona')) {
              const saved=await global.storeMemory(record);if (!saved || !(await global.readMemories()).some((row:any)=>row.id===saved.id)) throw new Error('全局偏好写入失败');
              core.memory.deleteL1Batch([record.id]);
            }
            stages.memory={stored:result.storedCount}; this.state.updateJob(job.id,'running',stages);
          }
          if (!stages.skills) {
            const result = await core.createSkillExtractor(this.state.settings().language).extract({...ids(scope),session_id:sessionId,task_id:job.id,messages:job.payload.messages,reason:`记录的轮次结果：${JSON.stringify(job.payload.reason)}`});
            stages.skills={candidates:result.candidates}; this.state.updateJob(job.id,'running',stages);
          }
          diagnosticEvent('INFO','rsi.learning.completed',{memory_stored:stages.memory?.stored,skill_candidates:stages.skills?.candidates?.length});
        },{route:job.payload.route ?? this.route(scope),sessionId,jobId:job.id});
        delete stages.failure;
        this.state.updateJob(job.id,'completed',stages); this.invalidate();
      } catch (error:any) {
        const paused = ['LEARNING_PAUSED','BUDGET_EXHAUSTED','MISSING_ROUTE'].includes(error.code) || !this.state.settings().learningEnabled || !this.state.settings().enabled || Number(this.state.usage().calls) >= this.state.settings().dailyCallBudget;
        stages.failure={...stages.failure,code:error.code ?? 'EXTRACTION_FAILED',retryable:!paused && !this.stopping && !['INVALID_LIMIT','UNSUPPORTED_TOOL','INVALID_CONFIG'].includes(error.code)};
        this.state.updateJob(job.id,this.stopping ? 'interrupted' : paused ? 'paused' : 'failed',stages,error.message);
        await this.within(scope,async()=>diagnosticEvent('ERROR','rsi.learning.failed',{status:this.stopping?'interrupted':paused?'paused':'failed',code:stages.failure.code,retryable:stages.failure.retryable,attempts:stages.failure.attempts},error),{sessionId,jobId:job.id});
        if (!paused && !this.stopping) this.ctx.logger.error('后台学习失败：%s',error.message);
        // Reject so the native manager restores its buffer and does not advance L2.
        throw error;
      }
    }
    return {processedCount:jobs.length,profileScopes:[scope]};
  }
  async learnNow(cwd: string) {
    const entry = await this.scope(cwd);
    const jobs = this.state.jobs(entry.id).filter(job => job.status !== 'completed');
    for (const job of jobs) { delete job.stages.failure; this.state.updateJob(job.id,'pending',job.stages); await this.pipelines.get(entry.id).notifyConversation(job.session,job.payload.messages.filter((m:any) => ['user','assistant'].includes(m.role))); }
    for (const session of new Set(jobs.map(job => job.session))) await this.pipelines.get(entry.id).flushSession(session);
    return this.snapshot(cwd);
  }
  async recall(cwd:string,query:string,origin:any={}) {
    const entry=await this.scope(cwd),settings=this.state.settings();
    if (!settings.enabled) return {text:'',refs:[]};
    const recalled:any[]=[];
    // Native L1 budgeting leaves room for stable profiles, scope labels and tool guidance.
    for (const scope of [entry.id,'global']) {
      const core=await this.core(scope),result=await this.within(scope,()=>core.recall(query,Math.max(1,Math.floor(settings.recallMaxChars/4))),origin);
      if(result)recalled.push({scope,core,result});
    }
    if(!recalled.length)return {text:'',refs:[]};
    const guide=recallToolGuide(recalled[0].result),guideText=guide.length<settings.recallMaxChars?guide:'';
    const available=settings.recallMaxChars-guideText.length-2;
    const parts:string[]=[],refs:any[]=[];
    for(const {scope,core,result} of recalled){
      const fitted=fitRecallScope(result,scope,core.profileDir,Math.floor(available/recalled.length),!this.state.get(`profile-invalid:${scope}`));
      if(fitted.text)parts.push(fitted.text);
      if(fitted.memories.length){
        const stored=await core.readMemories();
        const memories=fitted.memories.map((memory:any)=>{
          const matches=stored.filter((row:any)=>row.content===memory.content && row.type===memory.type);
          return matches.length===1?{...memory,id:matches[0].id,version:matches[0].version}:memory;
        });
        refs.push({scope,memories});
      }
    }
    if(parts.length && guideText)parts.push(guideText);
    const delivered=parts.join('\n');
    await this.within(entry.id,async()=>diagnosticEvent('INFO','rsi.recall.delivery',{query,query_message_ids:origin.queryMessageIds ?? [],delivered_chars:delivered.length,refs}),origin);
    return {text:delivered,refs};
  }
  async readProfile(cwd:string,path:string) {
    if(typeof path!=='string')throw new Error('场景路径无效');
    const entry=await this.scope(cwd);
    for(const scope of [entry.id,'global']){
      const core=await this.core(scope),key=isAbsolute(path)?relative(core.profileDir,resolve(path)):path;
      if(/^(?:scene_blocks\/[^/]+\.md|persona\.md|\.metadata\/scene_index\.json)$/.test(key)){
        const content=await core.profile.readFile(key);if(content!==null)return content;
      }
    }
    throw new Error('场景文件不存在或不属于当前工作区');
  }
  async candidates(cwd:string) {
    const entry=await this.scope(cwd), result:any[]=[];
    if (!this.state.settings().enabled) return result;
    for (const scope of [entry.id,'global']) {
      const core=await this.core(scope),list=await listAllSkills(core.skills,ids(scope));
      for (const skill of list.items) if (!this.state.disabled(scope,skill.skill_id)) result.push({name:visibleName(skill.name),description:skill.description,invocation:{modelInvocable:true,userInvocable:true},source:'dsh-rsi',provider:'dsh-rsi',rank:scope === entry.id ? 290 : 295,locator:{scope,id:skill.skill_id},metadata:{scope,id:skill.skill_id,version:skill.version},resourceBase:{kind:'directory',path:join(core.resourceDir,'skills',skill.skill_id,`v${skill.version}`,'files')}});
    }
    return result;
  }
  async definition(candidate:any,cwd:string) {
    const entry=await this.scope(cwd),{scope,id}=candidate.locator;
    if (![entry.id,'global'].includes(scope) || this.state.disabled(scope,id) || !this.state.settings().enabled) return;
    const core=await this.core(scope),skill=await core.skills.get({...ids(scope),skill_id:id});
    const parsed=parseSkillFile(skill.content);
    return {...candidate,content:parsed.body,metadata:{...candidate.metadata,version:skill.version},resourceBase:{kind:'directory',path:join(core.resourceDir,'skills',id,`v${skill.version}`,'files')}};
  }
  async snapshot(cwd:string) {
    const entry=await this.scope(cwd), memory:any[]=[],skills:any[]=[],layers:any={};
    for (const scope of [entry.id,'global']) {
      const core=await this.core(scope);
      layers[scope]=await core.layerCounts();
      memory.push(...(await core.readMemories()).map((row:any) => ({...row,scope})));
      skills.push(...(await listAllSkills(core.skills,ids(scope))).items.map((row:any) => ({...row,scope,visibleName:visibleName(row.name),disabled:this.state.disabled(scope,row.skill_id)})));
    }
    return {workspace:entry,settings:this.state.settings(),usage:this.state.usage(),memory,skills,layers,jobs:this.state.jobs(entry.id).map(({payload,...job}:any) => ({...job,sourceSessionId:payload.sessionId,reason:payload.reason})),workspaces:this.state.db.prepare("SELECT value FROM kv WHERE key LIKE 'scope:%'").all().map(row => JSON.parse(row.value as string).cwd).filter((value,index,array) => array.indexOf(value) === index),profilePending:!!this.state.get(`profile-invalid:${entry.id}`)||!!this.state.get('profile-invalid:global')};
  }
  async request(operation:string,payload:any) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('请求格式无效');
    if(['versions','skill','skillFile','editSkill','disable','rollback','editMemory','deleteMemory','promote','convertSkill','convertMemory'].includes(operation) && (typeof payload.id!=='string' || !payload.id))throw new Error('资产标识无效');
    if(operation==='rollback' && (!Number.isSafeInteger(payload.version)||payload.version<1))throw new Error('版本号无效');
    const cwd=payload.cwd ?? this.state.get('lastCwd') ?? this.config.cwd ?? process.cwd();
    const entry=await this.scope(cwd),scope=payload.scope ?? entry.id;
    if (![entry.id,'global'].includes(scope)) throw new Error('资产不属于所选工作区');
    const core=await this.core(scope);
    if (operation === 'snapshot') return this.snapshot(cwd);
    if (operation === 'settings') { const before=this.state.settings(); const after=this.state.configure(payload.settings); if (before.everyNConversations !== after.everyNConversations || before.idleSeconds !== after.idleSeconds) { for (const [key,pipeline] of this.pipelines) { await pipeline.destroy(); this.pipelines.delete(key); await this.createPipeline(key); } } this.invalidate(); await this.resume(); return this.snapshot(cwd); }
    if (operation === 'learn') return this.learnNow(cwd);
    if (operation === 'versions') return listAllVersions(core.skills,{...ids(scope),skill_id:payload.id});
    if (operation === 'skill') return core.skills.get({...ids(scope),skill_id:payload.id,version:payload.version});
    if (operation === 'memoryLayer') {
      if(!['L0','L1','L2','L3'].includes(payload.layer))throw new Error('未知记忆层级');
      if(payload.offset!==undefined&&(!Number.isSafeInteger(payload.offset)||payload.offset<0))throw new Error('分页参数无效');
      return core.readLayer(payload.layer,payload.offset??0);
    }
    if (operation === 'skillFile') {
      if(typeof payload.path!=='string'||!payload.path)throw new Error('资源路径无效');
      const skill=await core.skills.get({...ids(scope),skill_id:payload.id,version:payload.version});
      const item=skill.manifest.find((row:any)=>row.path===payload.path);
      if(!item)throw new Error('资源不属于所选版本');
      if(item.size_bytes>1048576)throw new Error('资源超过 1 MB，请从导出文件中查看');
      const file=await core.skills.readFile({...ids(scope),skill_id:payload.id,version:payload.version,path:payload.path,encoding:'base64'});
      if(file.size_bytes>1048576)throw new Error('资源超过 1 MB，请从导出文件中查看');
      return file;
    }
    if (operation === 'editSkill') {
      if(this.active.size||this.state.jobs().some(job=>job.status==='running'))throw new Error('请暂停学习并等待当前任务结束后编辑');
      if(!Number.isSafeInteger(payload.expectedVersion)||payload.expectedVersion<1)throw new Error('版本号无效');
      if(typeof payload.content!=='string'||!payload.content.trim())throw new Error('技能正文不能为空');
      await core.skills.update({...ids(scope),skill_id:payload.id,expected_version:payload.expectedVersion,content:payload.content});
      this.invalidate();return this.snapshot(cwd);
    }
    if (operation === 'disable') { if (typeof payload.disabled !== 'boolean') throw new Error('禁用设置无效'); await core.skills.get({...ids(scope),skill_id:payload.id}); this.state.disable(scope,payload.id,payload.disabled); this.invalidate(); return this.snapshot(cwd); }
    if (operation === 'rollback') {
      const current=await core.skills.get({...ids(scope),skill_id:payload.id}),old=await core.skills.get({...ids(scope),skill_id:payload.id,version:payload.version});
      const files=await versionResources(core,old);
      await core.versioning.appendNextVersion(current,ids(scope),{content:old.content,name:old.name,description:old.description,resourcesToWrite:files,resourcesToRemove:current.manifest.filter((f:any) => !old.manifest.some((x:any) => x.path === f.path)).map((f:any) => f.path),metadata_json:JSON.stringify({...JSON.parse(current.metadata_json || '{}'),rollbackFrom:old.version})});
      this.invalidate();return this.snapshot(cwd);
    }
    if (operation === 'editMemory' || operation === 'deleteMemory') {
      if(this.active.size || this.state.jobs().some(job => job.status === 'running')) throw new Error('请暂停学习并等待当前任务结束后编辑');
      if (operation === 'editMemory') { if (typeof payload.content !== 'string' || !payload.content.trim()) throw new Error('记忆正文不能为空'); await core.editMemory(payload.id,payload.content); }
      else if (!core.memory.deleteL1Batch([payload.id])) throw new Error('记忆删除失败');
      this.state.set(`profile-invalid:${scope}`,Date.now()); this.invalidate();return this.snapshot(cwd);
    }
    if (operation === 'importSkill') {
      if (typeof payload.name !== 'string') throw new Error('请选择已有技能');
      const original=await this.ctx.skills.get(payload.name,{cwd});
      if (!original || original.provider === 'dsh-rsi') throw new Error('已有技能不可导入');
      const content=`---\nname: ${payload.name}\ndescription: ${JSON.stringify(original.description)}\n---\n\n${original.content}`;
      await core.skills.create({...ids(scope),name:payload.name,content,resources:await copyResources(original.resourceBase),metadata:{importedFrom:{name:payload.name,provider:original.provider,path:original.path},copiedAt:Date.now()}});
      this.invalidate();return this.snapshot(cwd);
    }
    if (operation === 'promote') {
      if (scope === 'global') throw new Error('技能已经是通用技能');
      const skill=await core.skills.get({...ids(scope),skill_id:payload.id}),global=await this.core('global'),files=await versionResources(core,skill);
      await global.skills.create({...ids('global'),name:skill.name,content:skill.content,resources:files,metadata:{promotedFrom:{scope,id:skill.skill_id,version:skill.version}}});
      this.invalidate();return this.snapshot(cwd);
    }
    if (operation === 'export') {
      const skills=[];
      for (const head of (await listAllSkills(core.skills,ids(scope))).items) {
        const versions=await listAllVersions(core.skills,{...ids(scope),skill_id:head.skill_id});
        const contents=[]; for(const version of versions.items) contents.push({...version,resources:await versionResources(core,version)});skills.push({head,versions:contents});
      }
      const profileFiles=await copyResources({kind:'directory',path:core.profileDir}).catch((error:any)=>{if(error.code==='ENOENT')return [];throw error;});
      return {profileFiles,format:'dsh-rsi-export-v1',createdAt:new Date().toISOString(),scope,settings:this.state.settings(),memory:await core.readMemories(),memoryHistory:await core.readMemoryHistory(),skills,jobs:this.state.jobs(scope)};
    }
    if (operation === 'clear') {
      if (payload.confirm !== scope) throw new Error('清理确认与所选范围不一致');
      if (this.active.size || this.state.jobs(scope).some(job => job.status === 'running')) throw new Error('请先暂停学习并等待当前任务结束');
      if(this.state.settings().learningEnabled) throw new Error('请先暂停学习再清理资产');
      this.blockedScopes.add(scope);
      try {
        const pipeline=this.pipelines.get(scope);if(pipeline)await pipeline.destroy();
        this.pipelines.delete(scope);core.close();this.cores.delete(scope);
        await rm(core.directory,{recursive:true,force:true});
        this.state.db.prepare('DELETE FROM jobs WHERE scope=?').run(scope);
        this.state.db.prepare('DELETE FROM skill_controls WHERE scope=?').run(scope);
        this.state.db.prepare('DELETE FROM kv WHERE key=? OR key=? OR key=?').run(`pipeline:${scope}`,`profile-invalid:${scope}`,`l2-cursor:${scope}`);
        if(scope==='global') this.state.db.prepare("DELETE FROM kv WHERE key='global-l2-cursor'").run();
      } finally {this.blockedScopes.delete(scope);}
      this.invalidate();return this.snapshot(cwd);
    }
    if (operation === 'rebuildProfile') {
      if(this.state.settings().learningEnabled || this.active.size || this.state.jobs().some(job => job.status === 'running'))throw new Error('请暂停学习并等待当前任务结束后重建');
      if(!this.route(scope))throw new Error('尚无会话模型配置');
      await rm(join(core.directory,'profile'),{recursive:true,force:true});this.state.set(`profile-invalid:${scope}`,Date.now());
      await this.within(scope,async()=>{const result=await core.extractScenes('');if(!result.skipped)await core.generatePersona(true);},{manual:true});this.state.set(`profile-invalid:${scope}`,0);
      return this.snapshot(cwd);
    }
    if (operation === 'convertSkill' || operation === 'convertMemory') {
      if(this.active.size || this.state.jobs().some(job => job.status === 'running'))throw new Error('请暂停学习并等待当前任务结束后转换');
      const language=payload.language ?? this.state.settings().language;
      if(!['zh-CN','zh-TW','en','ja','ko'].includes(language))throw new Error('语言设置无效');
      if(operation==='convertSkill') {
        const source=await core.skills.get({...ids(scope),skill_id:payload.id});
        const content=await this.within(scope,()=>core.runner.run({taskId:'skill-language-conversion',systemPrompt:'Translate only natural-language prose in this SKILL.md. Keep the name, YAML keys, code, commands, paths and API identifiers unchanged. Return only the full SKILL.md with valid frontmatter.',prompt:source.content,enableTools:false}),{manual:true,language});
        const parsed=parseSkillFile(content);if(parsed.frontmatter.name!==source.name)throw new Error('转换结果更改了技能标识');
        await core.skills.update({...ids(scope),skill_id:payload.id,expected_version:source.version,content,metadata:{...JSON.parse(source.metadata_json||'{}'),convertedFrom:source.version,language}});
      }else{
        const source=(await core.readMemories()).find((row:any)=>row.id===payload.id);if(!source)throw new Error('记忆不存在');
        const content=await this.within(scope,()=>core.runner.run({taskId:'memory-language-conversion',systemPrompt:'Translate the memory prose without changing its meaning, commands, code, paths or identifiers. Return only translated text.',prompt:source.content,enableTools:false}),{manual:true,language});
        if(!content.trim())throw new Error('转换结果为空');await core.editMemory(payload.id,content);this.state.set(`profile-invalid:${scope}`,Date.now());
      }
      this.invalidate();return this.snapshot(cwd);
    }
    if (operation === 'originalSkills') return (await this.ctx.skills.list({cwd})).filter((skill:any) => skill.provider !== 'dsh-rsi');
    if (operation === 'searchConversations') return core.searchConversations(payload.query ?? '');
    throw new Error('未知管理操作');
  }
  async stop() {
    this.stopping=true; this.abort.abort(new Error('插件已关闭'));
    await this.captureQueue;
    await Promise.allSettled([...this.pipelines.values()].map(pipeline => pipeline.destroy()));
    await Promise.allSettled([...this.active]);
    for (const core of await Promise.allSettled([...this.cores.values()])) if (core.status === 'fulfilled') core.value.close();
    if(this.embeddingPromise){const result=await Promise.allSettled([this.embeddingPromise]);if(result[0].status==='fulfilled')await result[0].value.close?.();}
    for(const sink of this.diagnosticSinks.values())sink.close();this.diagnosticSinks.clear();
    this.state.close();
  }
}
