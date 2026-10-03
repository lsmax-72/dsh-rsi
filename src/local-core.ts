import { DatabaseSync } from 'node:sqlite';
import { mkdir } from 'node:fs/promises';
import { join } from 'node:path';
import {
  SkillCore, SqliteSkillStore, SkillResourceStore, SkillVersioning, SkillExtractor, SKILL_REVIEW_PROMPT,
  StorageAdapter, LocalStorageBackend, extractL1Memories, VectorStore,
  queryMemoryRecords, readAllMemoryRecords, recordConversation, SceneExtractor, PersonaGenerator,
  performAutoRecall, parseConfig, writeMemory, buildFtsQuery, readSceneIndex, parseSceneBlock,
} from './core-entry.js';

/** Each physical scope owns its native asset stores; no team service is mounted. */
export async function openLocalCore(dataDir: string, runner: any, logger: any) {
  await mkdir(dataDir, { recursive: true });
  const db = new DatabaseSync(join(dataDir, 'skills.sqlite'));
  const memory = new VectorStore(join(dataDir, 'memory.sqlite'), 0, logger);
  try {
    memory.init();
    if (!memory.isFtsAvailable()) throw new Error('记忆全文索引不可用');
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
    return {
      skills, resources, versioning, memory, resourceDir, profile,profileDir,
      async layerCounts(){return {L0:memory.countL0(),L1:(await queryMemoryRecords(memory)).length,L2:(await readSceneIndex(profileDir,profile)).length,L3:await profile.readFile('persona.md')?1:0};},
      async readLayer(layer:string,offset=0){
        if(layer==='L0'){const result=memory.queryL0Paginated({limit:50,offset});return {items:result.rows,total:result.total};}
        if(layer==='L1'){const items=await this.readMemories();return {items,total:items.length};}
        if(layer==='L2'){const entries=await readSceneIndex(profileDir,profile),items=[];for(const entry of entries){if(!/^[^/\\\\]+\.md$/.test(entry.filename))continue;const raw=await profile.readFile(`scene_blocks/${entry.filename}`);if(raw!==null)items.push({...entry,...parseSceneBlock(raw,entry.filename)});}return {items,total:items.length};}
        if(layer==='L3'){const content=await profile.readFile('persona.md');return {items:content?[{id:'persona',content}]:[],total:content?1:0};}
        throw new Error('未知记忆层级');
      },
      createSkillExtractor(language = 'zh-CN') {
        return new SkillExtractor({ core: skills, runner, logger, prefixSkillsLimit: 20,
          systemPrompt: `${SKILL_REVIEW_PROMPT}\nWrite asset prose in ${language}; preserve code, commands, paths and API identifiers.` });
      },
      record: (input: any) => recordConversation({ ...input, baseDir:join(dataDir,'history'), storage:history, logger }),
      async extractMemories(input: any) {
        const result = await extractL1Memories({ ...input, baseDir:join(dataDir,'history'), config:{}, storage:history, logger,
          // dsh emits many assistant messages inside one turn; the native ten-message default can drop its user input.
          options:{ llmRunner:runner, enableDedup:true, vectorStore:memory,
            maxMessagesPerExtraction:Math.max(10,input.messages.length) } });
        if (!result.success) throw new Error('记忆提炼失败，请查看后台会话日志');
        return result;
      },
      async readMemories(){const rows=await queryMemoryRecords(memory),historyRows=await readAllMemoryRecords(join(dataDir,'history'),logger,history),byId=new Map(historyRows.map(row=>[row.id,row]));return rows.map(row=>({...row,source_message_ids:byId.get(row.id)?.source_message_ids??[]}));},
      readMemoryHistory:()=>readAllMemoryRecords(join(dataDir,'history'),logger,history),
      async storeMemory(record:any){return writeMemory({memory:record,decision:{record_id:record.id,action:'store',target_ids:[]},baseDir:join(dataDir,'history'),sessionKey:record.sessionKey,sessionId:record.sessionId,taskId:record.taskId,vectorStore:memory,storage:history,logger});},
      async recall(query: string, maxChars = 6000) {
        const result = await performAutoRecall({ userText:query, pluginDataDir:profileBaseDir,
          cfg:parseConfig({ recall:{ strategy:'keyword', maxResults:8, maxTotalRecallChars:maxChars } }),
          vectorStore:memory, storage:profileBase, logger });
        if (result?.error) throw new Error('记忆召回失败');
        return result;
      },
      async extractScenes(after = '') {
        const rows = (await queryMemoryRecords(memory)).filter(row => row.updatedAt > after);
        if (!rows.length) return { skipped:true, latestCursor:after };
        const result = await scene.extract(rows.map(row => ({ id:row.id, content:row.content, created_at:row.createdAt })));
        if (!result.success) throw new Error(result.error ?? '场景提炼失败');
        return { latestCursor:rows.map(row => row.updatedAt).sort().at(-1), skipped:!!result.emptyExtraction };
      },
      async generatePersona() { const changed=await persona.generate(); if (!changed && !await profile.readFile('persona.md')) throw new Error('画像生成失败');return changed; },
      async editMemory(id: string, content: string) {
        const existing = (await queryMemoryRecords(memory, { recordIds:[id] }))[0];
        if(existing){const historyRows=await readAllMemoryRecords(join(dataDir,'history'),logger,history);existing.source_message_ids=historyRows.findLast(row=>row.id===id)?.source_message_ids??[];}
        if (!existing) throw new Error('记忆不存在');
        return writeMemory({ memory:{ ...existing, source_message_ids:existing.source_message_ids }, decision:{ record_id:id,action:'update', target_ids:[id], merged_content:content,  }, baseDir:join(dataDir,'history'), sessionKey:existing.sessionKey, sessionId:existing.sessionId, vectorStore:memory, storage:history, logger });
      },
      searchConversations: (query: string) => memory.searchL0Fts(buildFtsQuery(query),10),
      close: () => { memory.close(); db.close(); },
    };
  } catch (error) { memory.close(); db.close(); throw error; }
}
