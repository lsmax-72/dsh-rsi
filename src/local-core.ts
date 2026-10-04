import { DatabaseSync } from 'node:sqlite';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import { createReadyEmbedding, guardedEmbedding, withEmbeddingIntegrity, verifyVectorCoverage } from './native-embedding.js';
import { FileLogger } from '../adapters/local-observability.js';
import {
  SkillCore, SqliteSkillStore, SkillResourceStore, SkillVersioning, SkillExtractor, SKILL_REVIEW_PROMPT,
  StorageAdapter, LocalStorageBackend, extractL1Memories, VectorStore,
  queryMemoryRecords, readAllMemoryRecords, recordConversation, SceneExtractor, PersonaGenerator, PersonaTrigger, CheckpointManager, stripSceneNavigation,
  performAutoRecall, parseConfig, writeMemory, buildFtsQuery, readSceneIndex, parseSceneBlock,
} from './core-entry.js';

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
    const scene = new SceneExtractor({ dataDir: profileDir, config: {}, storage: profile, llmRunner: runner, logger });
    const persona = new PersonaGenerator({ dataDir: profileDir, config: {}, storage: profile, llmRunner: runner, logger });
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
      createSkillExtractor(language = 'zh-CN') {
        return new SkillExtractor({ core: skills, runner, logger, prefixSkillsLimit: 20,
          systemPrompt: `${SKILL_REVIEW_PROMPT}\nWrite asset prose in ${language}; preserve code, commands, paths and API identifiers.\nKeep a general SOP concise (target about 1500 characters); retain its trigger, decisions and failure branches. Put long scripts, examples and fixtures in native skill_files_write resources and reference them in the body; do not truncate essential task-specific knowledge. State success only when supported by observed tool results in this transcript, with the command/check and result. Assistant plans, claims and a completed turn alone are not execution evidence. Label failures, partial checks and unverified claims explicitly; they can still yield reusable skills. Separate observed evidence from proposed validation. Include an Evidence section with executed commands/checks and their observed results, or explicitly say no execution validation was observed. Proposed commands belong in Validation, and unexecuted broader changes must not be presented as proven workflow. Do not copy the harness execution protocol as learned user preferences.` });
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
        const extractionRunner={run:async (params:any)=>{try{return await runner.run(params.taskId==='l1-extraction'?{...params,systemPrompt:`${params.systemPrompt}\nThese memory inputs contain user/assistant prose, without tool execution results. Do not convert assistant claims or plans into verified success. Attribute such outcomes as assistant-reported/unverified, retain the source message IDs, and never invent successful tests. Instruction memories are standing rules or reusable operating conventions; a one-off feature/fix request is not a rule for future unrelated tasks. Capture useful task-specific history as episodic context instead, without inventing success. Describe the scene from the user activity, not the extractor or AI narrator. Preserve durable user facts and preferences.`}:params);}catch(error){runnerError=error;throw error;}}};
        const result = await withEmbeddingIntegrity(()=>extractL1Memories({ ...input, baseDir:join(dataDir,'history'), config:{}, storage:history, logger,
          // dsh emits many assistant messages inside one turn; the native ten-message default can drop its user input.
          options:{ llmRunner:extractionRunner, enableDedup:true, vectorStore:memory, embeddingService, previousSceneName:previous || undefined,
            maxMessagesPerExtraction:Math.max(10,input.messages.length) } }));
        if (!result.success) throw runnerError ?? new Error('记忆提炼失败，请查看后台会话日志');
        for(const record of result.records)assertIndexed(record);
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
          cfg:parseConfig({ recall:{ strategy:'hybrid', maxResults:8, maxTotalRecallChars:maxChars } }),
          vectorStore:memory, embeddingService, storage:profileBase, logger }));
        if (result?.error) throw new Error('记忆召回失败');
        return result;
      },
      async extractScenes(after = '') {
        const rows = (await queryMemoryRecords(memory)).filter(row => row.updatedAt > after);
        if (!rows.length) return { skipped:true, latestCursor:after };
        const result = await scene.extract(rows.map(row => ({ id:row.id, content:row.content, created_at:row.createdAt })));
        if (!result.success) throw new Error(result.error ?? '场景提炼失败');
        if(!result.emptyExtraction && result.memoriesProcessed>0)await checkpoint.incrementScenesProcessed();
        return { latestCursor:rows.map(row => row.updatedAt).sort().at(-1), skipped:!!result.emptyExtraction };
      },
      async generatePersona(force=false) {
        const trigger=await personaTrigger.shouldGenerate();
        if(!force && !trigger.should)return false;
        if(!(await readSceneIndex(profileDir,profile)).length)return false;
        const changed=await persona.generate(force?'用户手动重建':trigger.reason);
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
