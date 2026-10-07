import {createHash} from 'node:crypto';
import {batchDedup,writeMemory} from './core-entry.js';
import {withEmbeddingIntegrity} from './native-embedding.js';

const fingerprint=(value:any)=>createHash('sha256').update((JSON.stringify(value) ?? 'null')).digest('hex');
// This pinned SQLite implementation does not implement recordIds in its query filter.
const selectHeads=(core:any,ids:string[])=>core.memory.queryL1Records().filter((row:any)=>ids.includes(row.record_id));
const stale=()=>Object.assign(new Error('通用记忆在决策后变化，需重新检查冲突'),{code:'SHARED_MEMORY_CHANGED'});

/** A second native dedup pass sees shared heads; it never reads another workspace. */
export async function planSharedMemories(shared:any,records:any[]) {
  if(!records.length)return [];
  let runnerError:any;
  const llmRunner={run:async(params:any)=>{try{return await shared.runner.run({...params,systemPrompt:params.systemPrompt+'\nMemory timestamps are recording metadata, not event dates. Preserve source-supported preference changes and exceptions. Do not infer calendar dates or stronger preferences from generated summaries.'});}catch(error){runnerError=error;throw error;}}};
  const decisions=await withEmbeddingIntegrity(()=>batchDedup({memories:records.map(r=>({...r,record_id:r.id})),config:{},logger:shared.logger,vectorStore:shared.memory,embeddingService:shared.embeddingService,llmRunner}));
  // Native dedup falls back to store on runner failure; that is not a completed shared update.
  if(runnerError)throw runnerError;
  const heads=new Map((await shared.readMemories()).map((r:any)=>[r.id,r]));
  return records.map(record=>{
    const decision=decisions.find(d=>d.record_id===record.id);
    if(!decision)throw new Error('原生通用冲突决策缺失');
    const targets=decision.target_ids.map(id=>{const target=heads.get(id);if(!target)throw new Error('通用冲突目标不在可见范围');return target;});
    return {decision,targets};
  });
}

/** Route native writer operations, preserving its versions and the actual source IDs.
 * Delete after durable destination write; the persisted marker lets a pending job finish
 * an interrupted move without another model call or a second version increment.
 */
export async function applySharedMemory(workspace:any,shared:any,record:any,plan:any,onChanged:(core:any)=>void) {
  const {decision,targets}=plan;
  if(decision.action==='skip'){
    onChanged(workspace);
    if(selectHeads(workspace,[record.id]).length && (!workspace.memory.deleteL1Batch([record.id]) || selectHeads(workspace,[record.id]).length))throw new Error('重复记忆未从工作区移除');
    return;
  }
  const finalType=decision.action==='store'?record.type:(decision.merged_type ?? record.type);
  if(decision.action==='store' && finalType!=='persona')return;
  const destination=finalType==='persona'?shared:workspace;
  const key=fingerprint({record,plan});
  const existing=(await destination.readMemories()).find((r:any)=>r.id===record.id);
  const resumed=existing?.metadata?.rsi_scope_write===key;
  const current=new Map((await shared.readMemories()).map((r:any)=>[r.id,r]));
  if(targets.some((r:any)=>current.has(r.id)?fingerprint(current.get(r.id))!==fingerprint(r):!resumed))throw stale();
  // Invalidate before changing either head: automatic recall and explicit profile reads agree.
  onChanged(workspace);onChanged(shared);
  let saved=existing;
  if(!resumed){
    const ids=[...new Set([record.id,...decision.target_ids])];
    let failure:any;
    const guard=(operation:()=>any)=>{try{return operation();}catch(error){failure??=error;throw error;}};
    const writerStore={
      queryL1Records:({recordIds}:any)=>{
        if(recordIds.some((id:string)=>!ids.includes(id)))throw new Error('记忆写入越过计划范围');
        // Physical scope is the authorization boundary, not the new event's session ID.
        const all=[...selectHeads(workspace,[record.id]),...selectHeads(shared,decision.target_ids)];
        return all.filter(row=>recordIds.includes(row.record_id));
      },
      deleteL1Batch:(recordIds:string[])=>guard(()=>{if(recordIds.some(id=>!ids.includes(id)))throw new Error('记忆删除越过计划范围');return true;}),
      upsertL1:(value:any,embedding:any)=>guard(()=>{
        if(failure)throw failure;
        if(!embedding || value.id!==record.id || value.type!==finalType)throw new Error('通用记忆写入或向量无效');
        if(!destination.memory.upsertL1(value,embedding))throw new Error('通用记忆头写入失败');
        destination.assertMemoryIndexed(value);return true;
      }),
    };
    const storage={appendFile:async(path:string,line:string)=>{try{await destination.history.appendFile(path,line);}catch(error){failure??=error;throw error;}}};
    const memory={...record,source_message_ids:[...new Set([...targets.flatMap((r:any)=>r.source_message_ids??[]),...(record.source_message_ids??[])])],metadata:{...record.metadata,rsi_scope_write:key}};
    // A move replaces the staged workspace head too, so its native version participates.
    saved=await withEmbeddingIntegrity(()=>writeMemory({memory,decision:{...(decision.action==='store'?{record_id:decision.record_id,action:'update',merged_content:record.content,merged_type:record.type,merged_priority:record.priority}:decision),target_ids:ids},baseDir:destination.directory+'/history',sessionKey:record.sessionKey,sessionId:record.sessionId,taskId:record.taskId,vectorStore:writerStore as any,embeddingService:destination.embeddingService,storage:storage as any,logger:destination.logger}));
    if(failure)throw failure;
    if(!saved)throw new Error('通用记忆没有写入结果');
    destination.assertMemoryIndexed(saved);
  }
  if(resumed)destination.assertMemoryIndexed(existing);
  for(const [core,ids] of [[workspace,[record.id]],[shared,decision.target_ids]] as const){
    const candidates=ids.filter((id:string)=>core!==destination || id!==record.id);
    // A previous attempt may have finished one side of the cleanup already.
    const remove=candidates.length?selectHeads(core,candidates).map((row:any)=>row.record_id):[];
    if(remove.length && (!core.memory.deleteL1Batch(remove) || selectHeads(core,remove).length))throw new Error('通用记忆替换目标未删除');
  }
  if(destination===shared){
    // Native checkpoint atomically saves both this operation cursor and its counters.
    // Retrying after a durable head write must neither lose nor double count the move.
    const checkpointKey=`scope-write:${key}`;
    if(!(await shared.checkpoint.read()).runner_states[checkpointKey]?.last_l1_cursor)
      await shared.checkpoint.markL1ExtractionComplete(checkpointKey,1,1,record.scene_name);
  }
}
