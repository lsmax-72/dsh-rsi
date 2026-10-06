import { DatabaseSync } from 'node:sqlite';
import { AsyncLocalStorage } from 'node:async_hooks';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { createReadyEmbedding, guardedEmbedding, withEmbeddingIntegrity, verifyVectorCoverage } from './native-embedding.js';
import { fitNativeMemoryEntries } from './recall-context.js';
import { FileLogger } from '../adapters/local-observability.js';
import {
  SkillCore, SqliteSkillStore, SkillResourceStore, SkillVersioning, SkillExtractor, SKILL_REVIEW_PROMPT,
  StorageAdapter, LocalStorageBackend, extractL1Memories, VectorStore,
  queryMemoryRecords, readAllMemoryRecords, recordConversation, SceneExtractor, PersonaGenerator, PersonaTrigger, CheckpointManager, stripSceneNavigation,
  performAutoRecall, parseConfig, writeMemory, buildFtsQuery, readSceneIndex, parseSceneBlock,
} from './core-entry.js';
import { withinSkillReviewBudget, GENERATED_SKILL_BODY_MAX_CHARS, GENERATED_SKILL_BODY_DRAFT_CHARS } from './skill-review-budget.js';

const PROFILE_TIME_PROVENANCE='Profile source-time provenance: memory created_at and recording timestamps, scene META created/updated, and the current runtime date are processing metadata, not historical activity dates. Preserve calendar event claims only when supported by original source facts. Keep unanchored relative times relative; use unknown date or relative order for Evolution when no source date is established. Existing generated scenes/personas are derived summaries, not independent evidence for their inherited calendar claims. Keep native file META and profile update timestamps as recording/update metadata; do not erase explicit source-supported event dates.';

const PROFILE_FACT_PROVENANCE='Profile factual provenance: do not invent actions, techniques or outcomes beyond supplied source statements. Keep native implicit insights explicitly tentative, not established facts, standing preferences or mandatory interaction rules. Hypotheses in derived scenes/personas remain hypotheses when reused. Preserve explicit preference qualifications and changes, including prior preferences and exceptions.';

/** Validate host configuration before any learning dispatch; source selection remains native. */
export function validateSkillTranscriptWindow(value:any={}) {
  if(!value || typeof value!=='object' || Array.isArray(value))throw Object.assign(new Error('Skill 来源窗口必须是原生参数对象'),{code:'INVALID_CONFIG'});
  for(const [key,limit] of Object.entries(value))if(!['headChars','tailChars'].includes(key) || !Number.isSafeInteger(limit) || Number(limit)<=0)throw Object.assign(new Error('Skill 来源窗口必须使用原生正整数字符上限'),{code:'INVALID_CONFIG'});
  return Object.freeze({...value}) as {headChars?:number;tailChars?:number};
}

/** Each physical scope owns its native asset stores; no team service is mounted. */
export async function openLocalCore(dataDir: string, runner: any, logger: any, suppliedEmbedding?:any) {
  await mkdir(dataDir, { recursive: true });
  const baseEmbedding=suppliedEmbedding ?? await createReadyEmbedding(undefined,dataDir,logger);
  const embeddingService=guardedEmbedding(baseEmbedding,new FileLogger({path:join(dataDir,'diagnostics'),filename:'embedding.log',rotateSizeBytes:100*1024*1024,rotateBackupLimit:10}));
  const db = new DatabaseSync(join(dataDir, 'skills.sqlite'));
  const memory = new VectorStore(join(dataDir, 'memory.sqlite'), embeddingService.getDimensions(), logger);
  try {
    const initialized=memory.init(embeddingService.getProviderInfo());
    if(memory.isDegraded() || !memory.getCapabilities().vectorSearch)throw new Error('原生向量索引不可用');
    const before=verifyVectorCoverage(memory);
    if(initialized.needsReindex || before.missingL1 || before.missingL0)await withEmbeddingIntegrity(()=>memory.reindexAll(text=>embeddingService.embed(text)));
    const after=verifyVectorCoverage(memory);
    if(after.missingL1 || after.missingL0)throw new Error('已有资产向量重建不完整');
    if (!memory.isFtsAvailable()) throw new Error('记忆全文索引不可用');
    const assertIndexed=(record:any)=>{if(!record)return;const indexed=memory.getRawDb().prepare('SELECT m.content,m.updated_time,v.updated_time AS vector_updated FROM l1_records m JOIN l1_vec v ON v.record_id=m.record_id WHERE m.record_id=?').get(record.id);if(!indexed || indexed.content!==record.content || indexed.vector_updated!==indexed.updated_time)throw new Error('记忆正文与向量写入不一致');};
    // Native extraction returns intermediate writes; later merges can remove them in the same call.
    // Exempt only deletions actually performed by that extraction, never arbitrary missing rows.
    const extractionDeletes=new AsyncLocalStorage<Set<string>>();
    const findHead=memory.getRawDb().prepare('SELECT record_id FROM l1_records WHERE record_id=?');
    const nativeDelete=memory.deleteL1Batch.bind(memory);
    memory.deleteL1Batch=(ids,filter)=>{
      const audit=extractionDeletes.getStore();
      if(!audit)return nativeDelete(ids,filter);
      const existing=ids.filter(id=>findHead.get(id));
      const success=nativeDelete(ids,filter);
      if(success)for(const id of existing)if(!findHead.get(id))audit.add(id);
      return success;
    };
    const ensureVectors=async()=>{const missing=verifyVectorCoverage(memory);if(missing.missingL1 || missing.missingL0){await withEmbeddingIntegrity(()=>memory.reindexAll(text=>embeddingService.embed(text)));const remaining=verifyVectorCoverage(memory);if(remaining.missingL1 || remaining.missingL0)throw new Error('记忆向量修复不完整');}};
    db.exec('PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;');
    const resourceDir = join(dataDir, 'skill-assets');
    const storage = new StorageAdapter(new LocalStorageBackend(resourceDir));
    const history = new StorageAdapter(new LocalStorageBackend(join(dataDir, 'history')));
    const profileBaseDir=join(dataDir,'profile');
    const profileDir=join(profileBaseDir,'profiles',encodeURIComponent('team:default|agent:default'));
    const profileBase=new StorageAdapter(new LocalStorageBackend(profileBaseDir));
    const profile = new StorageAdapter(new LocalStorageBackend(profileDir));
    const store = new SqliteSkillStore({ db, dimensions: 0, logger });
    store.init();
    const resources = new SkillResourceStore({ storage });
    const versioning = new SkillVersioning({ store, resources, storage, logger });
    const skills = new SkillCore({ store, resources, versioning });
    // Native profile APIs hide runner failures in false/success=false. Keep their algorithms,
    // but restore the original error per invocation, including when an old persona exists.
    const profileErrors=new AsyncLocalStorage<{error?:unknown}>();
    const profileRunner={run:async(params:any)=>{
      try{return await runner.run({...params,systemPrompt:`${params.systemPrompt ?? ''}\n${PROFILE_TIME_PROVENANCE}\n${PROFILE_FACT_PROVENANCE}`});}
      catch(error){const operation=profileErrors.getStore();if(operation)operation.error=error;throw error;}
    }};
    const profileOperation=async<T>(operation:()=>Promise<T>)=>{
      const captured:{error?:unknown}={};
      const result=await profileErrors.run(captured,operation);
      if(Object.hasOwn(captured,'error'))throw captured.error;
      return result;
    };
    const scene = new SceneExtractor({ dataDir: profileDir, config: {}, storage: profile, llmRunner: profileRunner, logger });
    const persona = new PersonaGenerator({ dataDir: profileDir, config: {}, storage: profile, llmRunner: profileRunner, logger });
    const checkpoint = new CheckpointManager(profileDir,logger,profile);
    const personaTrigger = new PersonaTrigger({dataDir:profileDir,interval:parseConfig({}).persona.triggerEveryN,logger,storage:profile});
    return {
      skills, resources, versioning, memory, embeddingService, resourceDir, profile,profileDir,checkpoint,personaTrigger,
      async layerCounts(){return {L0:memory.countL0(),L1:(await queryMemoryRecords(memory)).length,L2:(await readSceneIndex(profileDir,profile)).length,L3:stripSceneNavigation(await profile.readFile('persona.md') ?? '').trim()?1:0};},
      async readLayer(layer:string,offset=0){
        if(layer==='L0'){const result=memory.queryL0Paginated({limit:50,offset});return {items:result.rows,total:result.total};}
        if(layer==='L1'){const items=await this.readMemories();return {items,total:items.length};}
        if(layer==='L2'){const entries=await readSceneIndex(profileDir,profile),items=[];for(const entry of entries){if(!/^[^/\\\\]+\.md$/.test(entry.filename))continue;const raw=await profile.readFile(`scene_blocks/${entry.filename}`);if(raw!==null)items.push({...entry,...parseSceneBlock(raw,entry.filename)});}return {items,total:items.length};}
        if(layer==='L3'){const content=await profile.readFile('persona.md');return {items:content?[{id:'persona',content}]:[],total:content?1:0};}
        throw new Error('未知记忆层级');
      },
      createSkillExtractor(language = 'zh-CN', transcriptWindow: {headChars?:number;tailChars?:number} = {}) {
        // Delegate source coverage to the native extractor; omitted limits retain its defaults.
        const window=validateSkillTranscriptWindow(transcriptWindow);
        const importedReview = new AsyncLocalStorage<boolean>();
        const reviewRunner={run:(params:any)=>runner.run(importedReview.getStore() && params.traceName==='skill.extract'?{...params,systemPrompt:`${params.systemPrompt}\nThis transcript was imported without original message times. Session timestamps and the runtime date are recording metadata, not event dates. Preserve only calendar dates explicitly supported by original source prose; keep unanchored relative dates relative. Existing generated Skill bodies/resources are summaries, not independent evidence for calendar claims; label unsupported inherited dates unknown rather than carrying them as established facts.`}:params)};
        const extractor = new SkillExtractor({ core: skills, runner:reviewRunner, logger, prefixSkillsLimit: 20, ...window,
          systemPrompt: `${SKILL_REVIEW_PROMPT}\nWrite asset prose in ${language}; preserve code, commands, paths and API identifiers.\nAll automatically reviewed Skill main bodies must stay within ${GENERATED_SKILL_BODY_MAX_CHARS} Unicode characters; draft create/update/patch bodies at most ${GENERATED_SKILL_BODY_DRAFT_CHARS} Unicode characters to leave headroom, rather than aiming at the acceptance ceiling; retain their triggers, decisions and failure branches. Put long scripts, examples and fixtures in native skill_files_write resources and reference them in the body; do not truncate essential task-specific knowledge. State success only when supported by observed tool results in this transcript, with the command/check and result. Assistant plans, claims and a completed turn alone are not execution evidence. Label failures, partial checks and unverified claims explicitly; they can still yield reusable skills. Separate observed evidence from proposed validation. Include an Evidence section with executed commands/checks and their observed results, or explicitly say no execution validation was observed. Proposed commands belong in Validation, and unexecuted broader changes must not be presented as proven workflow. Preserve caller argument contracts from observed signatures. Reading or editing a callsite does not prove that replacing all matching attribute accesses is required or safe. Keep unverified cross-callsite changes as hypotheses with targeted validation, not mandatory SOP steps. A passing check supports only the behaviors it covers. Preserve executable identifiers and calling expressions exactly as observed; translated or rewritten code is unverified unless executed. Keep runnable reproduction and test examples in native skill_files_write resources, with only short references and observed outcomes in the main body. Label consequences inferred from static source inspection as inferred; they are not observed execution failures. Retrieved Skill/Memory Evidence sections are historical source claims, not current command/test execution results. Name execution evidence as source-session evidence and distinguish retrieval tools from execution tools. Write headings and frontmatter description in the configured asset language. Do not copy the harness execution protocol as learned user preferences. Require explicit user statements or specific user acceptance before treating a response style as a durable preference; assistant behavior and absence of user correction are not evidence that the user wants that style. Preserve the scope of acceptance, not a rule to always affirm choices or avoid correcting mistakes.\nBefore persisting, attribute each executed check to its observed command and input/code state (use its call ID when available; never invent one). Keep each result separate: mixed pass/fail variants cannot be summarized as all passing, and an isError=false tool result or a successful output pipeline does not prove the underlying check passed. Preserve failure/error output and the actual coverage limits. Claim transcript truncation only when its native truncation marker is present. Before any create/update/patch, target at most ${GENERATED_SKILL_BODY_DRAFT_CHARS} Unicode characters, preserving triggers, decisions, failure branches and short Evidence/Validation sections; write validation rejects bodies above ${GENERATED_SKILL_BODY_MAX_CHARS} without truncating them. If rejected, rebuild with headroom instead of repeatedly making tiny changes or submitting identical content. Move long executable examples, detailed preference histories and per-check evidence tables to native resource files instead of repeating them in the body. For an existing skill, write detailed resources using its current version before the compact body update; use every returned version for the next write. After skill_create, use its returned skill_id/version for skill_files_write and use each returned version for further writes; include relative resource references and finish only after their writes succeed.` });
        const extract = extractor.extract.bind(extractor);
        extractor.extract = input => importedReview.run(input.messages.some((m:any)=>m.timestampKind==='imported-unknown'),()=>withinSkillReviewBudget(() => extract(input)));
        return extractor;
      },
      async record(input:any) {
        let captured:any[]=[];
        await checkpoint.captureAtomically(input.sessionKey,undefined,async afterTimestamp=>{
          captured=await recordConversation({...input,afterTimestamp,baseDir:join(dataDir,'history'),storage:history,logger});
          // Index before advancing the native capture cursor; a failed write must remain retryable.
          for(const message of captured)if(!await memory.upsertL0({id:message.id,sessionKey:input.sessionKey,sessionId:input.sessionId,role:message.role,messageText:message.content,recordedAt:new Date().toISOString(),timestamp:message.timestamp},await embeddingService.embed(message.content)))throw new Error('原始会话索引写入失败');
          return captured.length?{maxTimestamp:Math.max(...captured.map(message=>message.timestamp)),messageCount:captured.length}:null;
        });
        return captured;
      },
      async extractMemories(input: any) {
        await ensureVectors();
        const previous=checkpoint.getRunnerState(await checkpoint.read(),input.sessionKey).last_scene_name;
        let runnerError:any;
        // Annotate only IDs the native formatter actually delivered; its source/window logic stays native.
        const timeProvenance=(params:any)=>{
          const ids=input.messages.filter((message:any)=>message.timestampKind==='imported-unknown' && params.prompt.includes(`[${message.id}]`)).map((message:any)=>message.id);
          return ids.length?`\nHistorical time provenance for message IDs ${JSON.stringify(ids)}: their displayed timestamps are import/recording times only; original message times are unknown. Do not treat these timestamps, the current runtime date, or another imported timestamp as historical event dates. Preserve explicit dates in source prose. For relative dates without a source-supported calendar anchor, preserve the relative wording and omit inferred absolute activity_start_time/activity_end_time and calendar claims in content. Other messages retain normal native timestamp semantics.`:'';
        };
        const extractionRunner={run:async (params:any)=>{try{
          let annotated=params;
          if(params.taskId==='l1-extraction'){
            // Native timestamps are capture cursors; label imported recording times at their actual source line.
            let prompt=params.prompt;
            for(const message of input.messages.filter((m:any)=>m.timestampKind==='imported-unknown')){
              const nativeLabel=`[${message.id}] [${message.role}] [${new Date(message.timestamp).toISOString()}]:`;
              prompt=prompt.replace(nativeLabel,`[${message.id}] [${message.role}] [original_time:unknown; recorded_at:${new Date(message.timestamp).toISOString()}]:`);
            }
            annotated={...params,prompt,systemPrompt:`${params.systemPrompt}\nThese memory inputs contain user/assistant prose, without tool execution results. Do not convert assistant claims or plans into verified success. Attribute such outcomes as assistant-reported/unverified, retain the source message IDs, and never invent successful tests. Instruction memories are standing rules or reusable operating conventions; a one-off feature/fix request is not a rule for future unrelated tasks. Capture useful task-specific history as episodic context instead, without inventing success. Preserve durable user facts and preferences. For preference changes retain explicitly stated past/current preferences and exception qualifiers, rather than only a current generalization.${timeProvenance(params)}`};
          }else if(params.taskId==='l1-conflict-detection'){
            annotated={...params,systemPrompt:`${params.systemPrompt}\nCandidate memory timestamps are persistence/recording metadata, not evidence for activity dates. Do not turn them or the current runtime date into calendar claims in merged_content. Preserve explicit source-supported event dates and unanchored relative wording; generated summaries do not establish new user facts or stronger preferences.${input.messages.some((m:any)=>m.timestampKind==='imported-unknown')?' New memories in this call include imported history without original message dates; do not infer absolute dates for those records.':''}`};
          }
          return await runner.run(annotated);
        }catch(error){runnerError=error;throw error;}}};
        const deleted=new Set<string>();
        const result = await extractionDeletes.run(deleted,()=>withEmbeddingIntegrity(()=>extractL1Memories({ ...input, baseDir:join(dataDir,'history'), config:{}, storage:history, logger,
          // The durable caller supplies bounded new-message batches and their native background.
          options:{ llmRunner:extractionRunner, enableDedup:true, vectorStore:memory, embeddingService, previousSceneName:previous || undefined, maxMessagesPerExtraction:Math.min(10,input.newMessageCount ?? 10) } })));
        if (!result.success) throw runnerError ?? new Error('记忆提炼失败，请查看后台会话日志');
        for(const record of new Map(result.records.map(record=>[record.id,record])).values()){
          if(deleted.has(record.id) && !findHead.get(record.id))continue;
          assertIndexed(record);
        }
        const coverage=verifyVectorCoverage(memory);if(coverage.missingL1)throw new Error('记忆提炼向量写入不完整');
        await checkpoint.markL1ExtractionComplete(input.sessionKey,result.storedCount,undefined,result.lastSceneName);
        return result;
      },
      async readMemories(){const rows=await queryMemoryRecords(memory),historyRows=await readAllMemoryRecords(join(dataDir,'history'),logger,history),byId=new Map(historyRows.map(row=>[row.id,row]));return rows.map(row=>({...row,source_message_ids:byId.get(row.id)?.source_message_ids??[]}));},
      readMemoryHistory:()=>readAllMemoryRecords(join(dataDir,'history'),logger,history),
      async storeMemory(record:any){await ensureVectors();const saved=await withEmbeddingIntegrity(()=>writeMemory({memory:record,decision:{record_id:record.id,action:'store',target_ids:[]},baseDir:join(dataDir,'history'),sessionKey:record.sessionKey,sessionId:record.sessionId,taskId:record.taskId,vectorStore:memory,embeddingService,storage:history,logger}));assertIndexed(saved);if(saved)await checkpoint.markL1ExtractionComplete(record.sessionKey,1,undefined,record.scene_name);return saved;},
      async recall(query: string, maxChars = 6000) {
        await ensureVectors();
        const result = await withEmbeddingIntegrity(()=>performAutoRecall({ userText:query, pluginDataDir:profileBaseDir,
          cfg:parseConfig({ recall:{ strategy:'hybrid', maxResults:8, maxTotalRecallChars:0, maxCharsPerMemory:0 } }),
          vectorStore:memory, embeddingService, storage:profileBase, logger }));
        if (result?.error) throw new Error('记忆召回失败');
        // Disable native prefix truncation via its public config; search/ranking stay native.
        return fitNativeMemoryEntries(result,await this.readMemories(),maxChars);
      },
      async extractScenes(after = '') {
        const rows = (await queryMemoryRecords(memory)).filter(row => row.updatedAt > after);
        if (!rows.length) return { skipped:true, latestCursor:after };
        const result = await profileOperation(()=>scene.extract(rows.map(row => ({ id:row.id, content:row.content, created_at:row.createdAt }))));
        if (!result.success) throw new Error(result.error ?? '场景提炼失败');
        if(!result.emptyExtraction && result.memoriesProcessed>0)await checkpoint.incrementScenesProcessed();
        return { latestCursor:rows.map(row => row.updatedAt).sort().at(-1), skipped:!!result.emptyExtraction };
      },
      async generatePersona(force=false) {
        const trigger=await personaTrigger.shouldGenerate();
        if(!force && !trigger.should)return false;
        if(!(await readSceneIndex(profileDir,profile)).length)return false;
        const changed=await profileOperation(()=>persona.generate(force?'用户手动重建':trigger.reason));
        if(!changed && !stripSceneNavigation(await profile.readFile('persona.md') ?? '').trim())throw new Error('画像生成失败');
        return changed;
      },
      async editMemory(id: string, content: string) {
        await ensureVectors();
        const existing = (await queryMemoryRecords(memory, { recordIds:[id] }))[0];
        if(existing){const historyRows=await readAllMemoryRecords(join(dataDir,'history'),logger,history);existing.source_message_ids=historyRows.findLast(row=>row.id===id)?.source_message_ids??[];}
        if (!existing) throw new Error('记忆不存在');
        const saved=await withEmbeddingIntegrity(()=>writeMemory({ memory:{ ...existing, source_message_ids:existing.source_message_ids }, decision:{ record_id:id,action:'update', target_ids:[id], merged_content:content,  }, baseDir:join(dataDir,'history'), sessionKey:existing.sessionKey, sessionId:existing.sessionId, vectorStore:memory, embeddingService, storage:history, logger }));assertIndexed(saved);return saved;
      },
      searchConversations: (query: string) => memory.searchL0Fts(buildFtsQuery(query),10),
      close: () => { memory.close(); db.close();if(!suppliedEmbedding)baseEmbedding.close?.(); },
    };
  } catch (error) { memory.close(); db.close();if(!suppliedEmbedding)baseEmbedding.close?.();throw error; }
}
