import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {LlmAdapter} from '@deepseek-ai/dsh-llm';
export const name='rsi-runtime-shared-memory-probe';
export const inject=['rsi','llm'];
export function apply(ctx,config){
  let mode='initial',sourceId='scope-old',oldId,failDedup=false;const calls=[],profileReplies=[];
  class Fixture extends LlmAdapter{
    async *stream(options){
      if(profileReplies.length){
        const block=profileReplies.shift();calls.push({kind:'profile',mode});
        yield {type:'block-start',index:0,blockType:block.type};yield {type:'block-end',index:0,block};yield {type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};yield {type:'finish',reason:{kind:block.type==='tool-call'?'tool-calls':'stop'}};return;
      }
      const prompt=options.messages.flatMap(m=>m.content).filter(b=>b.type==='text').map(b=>b.text).join('\n');
      let output='Nothing to save.',kind='skill';
      if(prompt.includes('【待提取的新消息】')){
        kind='extract';output=JSON.stringify([{scene_name:'海报偏好',message_ids:[sourceId],memories:[{content:mode==='initial'?'用户喜欢收藏电影海报。':'用户减少实体海报，改用数字收藏。',type:['initial','skip'].includes(mode)?'persona':'episodic',priority:80,source_message_ids:[sourceId],metadata:{}}]}]);
        if(mode==='batch'){const entries=JSON.parse(output);entries[0].memories.push({...entries[0].memories[0],content:'用户希望避免实体收藏占用生活空间。'});output=JSON.stringify(entries);}
      }else if(prompt.includes('统一候选记忆池')){
        kind='dedup';assert.ok(!prompt.includes('OTHER_WORKSPACE_PRIVATE'));assert.ok(prompt.includes(oldId));
        calls.push({kind,mode,oldVisible:true});
        if(failDedup){failDedup=false;throw new Error('FIXTURE_SHARED_DEDUP_FAILURE');}
        const ids=[...prompt.matchAll(/### 第 \d+ 条新记忆 \(record_id: ([^)]+)\)/g)].map(m=>m[1]);assert.equal(ids.length,1);
        output=JSON.stringify([{record_id:ids[0],action:mode.startsWith('skip')?'skip':'merge',target_ids:mode.startsWith('skip')?[]:[oldId],merged_content:'用户过去收藏实体海报，目前改用数字收藏。',merged_type:mode==='demote'?'episodic':'persona',merged_priority:80}]);
        if(mode==='batch')oldId=ids[0];
      }else assert.ok(prompt.includes('Skill Review Agent'),'Unexpected fixture call');
      if(kind!=='dedup')calls.push({kind,mode});
      yield {type:'block-start',index:0,blockType:'text'};yield {type:'block-end',index:0,block:{type:'text',text:output}};yield {type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};yield {type:'finish',reason:{kind:'stop'}};
    }
  }
  ctx.effect(()=>ctx.llm.registerAdapter(['rsi-probe'],new Fixture()));
  ctx.effect(()=>{const alive=setInterval(()=>{},1000);const timer=setTimeout(async()=>{try{
    await ctx.rsi.ready;const rt=ctx.rsi.runtime,cwd=join(config.root,'scope-workspace');await mkdir(cwd,{recursive:true});const scope=(await rt.scope(cwd)).id,work=await rt.core(scope),global=await rt.core('global'),live=async()=>(await global.readMemories()).filter(r=>r.id!=='unrelated-global');
    if(config.phase==='restore'){
      assert.equal((await live()).length,0);assert.equal((await work.readMemories()).length,1);assert.ok(rt.state.jobs(scope).every(j=>j.status==='completed'));assert.equal(calls.length,0);
      await writeFile(join(config.root,'restored.json'),JSON.stringify({status:'PASS',modelRequests:0,completedMovesRetained:true}));process.exit(0);
    }
    await mkdir(join(config.root,'unrelated-workspace'),{recursive:true});const other=(await rt.scope(join(config.root,'unrelated-workspace'))).id,privateCore=await rt.core(other);await privateCore.storeMemory({id:'other-private',sessionKey:'other',sessionId:'other',content:'OTHER_WORKSPACE_PRIVATE 用户喜欢收藏电影海报。',type:'persona',priority:99,scene_name:'海报偏好',source_message_ids:['private-source'],metadata:{}});
    let turn=0;
    const enqueue=()=>{turn++;const sessionId='scope-session-'+turn;rt.state.enqueue({scope,sessionId,turn:1,endSeq:1,cwd,messages:[{id:sourceId,role:'user',content:'这是一条用于验证偏好跨会话变化的完整用户消息：我现在减少实体电影海报，转用数字收藏，并希望保留偏好变化的依据。',timestamp:new Date(Date.now()+turn).toISOString()}],route:{provider:'rsi-probe',model:'fixture'},reason:{kind:'completed'}});const job=rt.state.jobs(scope).find(j=>j.session===sessionId);rt.state.updateJob(job.id,'pending',{recorded:true});return {sessionId,id:job.id};};
    let job=enqueue();await rt.process(scope,job.sessionId);const first=(await live())[0];assert.ok(first);oldId=first.id;assert.equal((await work.readMemories()).length,0);
    const unrelated=await global.storeMemory({id:'unrelated-global',sessionKey:'unrelated',sessionId:'unrelated',content:'用户喜欢蓝色。',type:'persona',priority:50,scene_name:'颜色',source_message_ids:['unrelated-source'],metadata:{}});
    await global.profile.writeFile('persona.md','# STALE_PROFILE');rt.state.set('profile-invalid:global',0);assert.equal(await rt.readProfile(cwd,join(global.profileDir,'persona.md')),'# STALE_PROFILE');
    mode='update';sourceId='scope-new';failDedup=true;job=enqueue();const extractionBefore=calls.filter(x=>x.kind==='extract').length;await assert.rejects(rt.process(scope,job.sessionId),/FIXTURE_SHARED_DEDUP_FAILURE/);
    assert.ok(rt.state.jobs(scope).find(j=>j.id===job.id).stages.memoryBatches.pending);assert.ok((await live()).some(r=>r.id===oldId));
    await rt.process(scope,job.sessionId);assert.equal(calls.filter(x=>x.kind==='extract').length,extractionBefore+1);
    let merged=(await live())[0];assert.notEqual(merged.id,oldId);assert.ok(merged.version>first.version);assert.deepEqual(new Set(merged.source_message_ids),new Set(['scope-old','scope-new']));assert.equal((await work.readMemories()).length,0);assert.equal(global.memory.queryL1Records().filter(r=>r.record_id===oldId).length,0);
    await assert.rejects(rt.readProfile(cwd,join(global.profileDir,'persona.md')),e=>e.code==='PROFILE_STALE');assert.ok(!(await rt.recall(cwd,'收藏海报')).text.includes('STALE_PROFILE'));
    profileReplies.push({type:'tool-call',id:'write-scene',name:'write',arguments:JSON.stringify({path:'海报偏好.md',content:'-----META-START-----\ncreated: 2026-10-07T00:00:00Z\nupdated: 2026-10-07T00:00:00Z\nsummary: 数字收藏\nheat: 1\n-----META-END-----\n\n用户过去收藏实体海报，目前改用数字收藏。'})},{type:'text',text:'Saved.'},{type:'tool-call',id:'write-persona',name:'write',arguments:JSON.stringify({path:'persona.md',content:'# UPDATED_PROFILE\n用户目前改用数字收藏。'})},{type:'text',text:'Saved.'});
    await rt.request('settings',{cwd,settings:{learningEnabled:false}});await rt.request('rebuildProfile',{cwd,scope:'global'});assert.equal(profileReplies.length,0);assert.ok((await rt.readProfile(cwd,join(global.profileDir,'persona.md'))).includes('UPDATED_PROFILE'));assert.ok((await rt.recall(cwd,'收藏海报')).text.includes('UPDATED_PROFILE'));await rt.request('settings',{cwd,settings:{learningEnabled:true}});
    oldId=merged.id;mode='skip';sourceId='scope-duplicate';job=enqueue();await rt.process(scope,job.sessionId);assert.equal((await work.readMemories()).length,0);assert.equal((await live())[0].id,oldId);
    mode='skip-episodic';sourceId='scope-duplicate-event';job=enqueue();await rt.process(scope,job.sessionId);assert.equal((await work.readMemories()).length,0);assert.equal((await live())[0].id,oldId);
    const count=calls.length;await rt.process(scope,job.sessionId);assert.equal(calls.length,count);
    // A failure after the destination head exists must finish the move without calling LLM again.
    oldId=merged.id;sourceId='scope-retry';mode='update';job=enqueue();const remove=global.memory.deleteL1Batch.bind(global.memory);let breakDelete=true;
    global.memory.deleteL1Batch=(ids,...rest)=>{if(breakDelete && ids.includes(oldId)){breakDelete=false;throw new Error('FIXTURE_DELETE_FAILURE');}return remove(ids,...rest);};
    await assert.rejects(rt.process(scope,job.sessionId),/FIXTURE_DELETE_FAILURE/);const counterBeforeRetry=(await global.checkpoint.read()).total_memories_extracted;const beforeRetry=calls.length,newHead=(await live()).find(r=>r.id!==oldId);assert.ok(newHead);
    await rt.process(scope,job.sessionId);assert.equal(calls.length,beforeRetry+1); // only the previously unstarted Skill review
    assert.equal((await global.checkpoint.read()).total_memories_extracted,counterBeforeRetry+1);
    merged=(await live())[0];assert.equal(merged.id,newHead.id);assert.equal(merged.version,newHead.version);global.memory.deleteL1Batch=remove;
    oldId=merged.id;sourceId='scope-batch';mode='batch';job=enqueue();const beforeBatch=merged.version;await rt.process(scope,job.sessionId);assert.equal((await live()).length,1);merged=(await live())[0];assert.equal(merged.version,beforeBatch+2);assert.equal((await work.readMemories()).length,0);
    // Native demotion retires the shared head and keeps the new episodic head in this workspace.
    oldId=merged.id;sourceId='scope-demote';mode='demote';job=enqueue();await rt.process(scope,job.sessionId);
    assert.equal((await live()).length,0);const local=(await work.readMemories())[0];assert.equal(local.type,'episodic');assert.ok(local.source_message_ids.includes('scope-old'));assert.equal((await privateCore.readMemories())[0].id,'other-private');
    for(const core of [work,global]){const db=core.memory.getRawDb();assert.equal(db.prepare('SELECT COUNT(*) n FROM l1_records').get().n,db.prepare('SELECT COUNT(*) n FROM l1_vec').get().n);}
    const preserved=(await global.readMemories()).find(r=>r.id==='unrelated-global');assert.equal(preserved.content,unrelated.content);assert.equal(preserved.version,unrelated.version);assert.deepEqual(preserved.source_message_ids,unrelated.source_message_ids);global.memory.deleteL1Batch(['unrelated-global']);
    await rt.request('settings',{cwd,settings:{learningEnabled:false}});
    await rt.request('rebuildProfile',{cwd,scope:'global'});assert.equal(!!rt.state.get('profile-invalid:global'),false);await assert.rejects(rt.readProfile(cwd,join(global.profileDir,'persona.md')));
    await writeFile(join(config.root,'result.json'),JSON.stringify({status:'PASS',realModelRequests:0,fixtureCalls:calls,checks:['native-runtime-process-shared-candidates-across-source-sessions','other-workspace-isolated','unrelated-shared-head-preserved','native-skip-for-persona-and-episodic-keeps-shared-head','native-version-and-source-history-preserved','dedup-failure-resumes-without-reextracting','destination-written-before-old-target-removal','interrupted-move-finishes-without-new-conflict-call-or-version','completed-job-noop','interrupted-move-counted-once-in-native-checkpoint','demotion-removes-global-head','automatic-and-explicit-profile-staleness-guard','empty-global-profile-rebuild','nonempty-global-native-profile-rebuild-and-consumption','same-batch-later-update-sees-previous-shared-head','head-vector-consistency'],limits:['Fixture decisions test scope plumbing, not semantic correctness or real answer gains.','Jobs enter Runtime.process directly; capture/scheduler is covered by the existing host regression.']}));process.exit(0);
  }catch(error){console.error(error.stack);process.exit(1);}},0);return()=>{clearInterval(alive);clearTimeout(timer);};});
}
