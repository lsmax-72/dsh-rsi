import assert from 'node:assert/strict';
import {cp, readFile} from 'node:fs/promises';
import {mkdirSync, openSync, closeSync, fsyncSync, writeFileSync, renameSync, appendFileSync} from 'node:fs';
import {execFileSync} from 'node:child_process';
import {LlmAdapter, createUserMessage} from '@deepseek-ai/dsh-llm';
import {auditRequests} from './audit-session-requests.mjs';
import {Session} from '@deepseek-ai/dsh-session';
import {taskProtocol} from './task-input.mjs';

export const name = 'rsi-pilot-task';
export const inject = ['llm', 'agents', 'sessions', 'sessionPersistence', 'skills', 'tools'];

// The same official agent executes both arms. RSI is absent from the baseline patch.
export function apply(ctx, config) {
  assert.ok(['baseline', 'rsi'].includes(config.arm));
  const dir = '/state/pilot/' + config.instanceId;
  mkdirSync(dir, {recursive:true});
  const blocked = [];
  const requests = [], results = [], sessions = new Map(), phaseResults = [];
  let learningAttempts = 0;
  let foreground = 0, phaseCalls = 0, phaseLimit, deadline, initialized = false, currentPhase = 'setup';
  const dispatchLimit = config.dispatchLimit ?? 50;
  const wallTimeMs = config.wallTimeMs ?? 1200000;
  const git = (...args) => execFileSync('git', args, {cwd:'/workspace', encoding:'utf8',
    env:config.baselineDate?{...process.env,GIT_AUTHOR_DATE:config.baselineDate,GIT_COMMITTER_DATE:config.baselineDate}:process.env});
  const durable = (path, value) => {
    const tmp = path + '.tmp';
    writeFileSync(tmp, typeof value === 'string' ? value : JSON.stringify(value, null, 2));
    const fd = openSync(tmp, 'r'); try {fsyncSync(fd);} finally {closeSync(fd);}
    renameSync(tmp, path);
    const parent = openSync(dir, 'r'); try {fsyncSync(parent);} finally {closeSync(parent);}
  };
  const ledger = () => durable(dir + '/model-requests.json', requests);
  const patch = () => {
    if (!initialized) return;
    git('add', '-A');
    durable(dir + '/prediction.patch', git('diff', '--cached', '--binary', 'HEAD'));
  };
  ctx.on('session/event', (session, event) => {
    if (!sessions.has(session.id)) {
      sessions.set(session.id, session);
      durable(dir + '/' + session.id + '.header.json', session.header);
    }
    // Mirror published native events as well as retaining official persistence in /state/home.
    const file = dir + '/source-events.jsonl';
    appendFileSync(file, JSON.stringify({sessionId:session.id, event}) + '\n');
    const fd = openSync(file, 'r'); try {fsyncSync(fd);} finally {closeSync(fd);}
  });
  ctx.on('llm/stream', async function*(options, next) {
    const background = options.sessionId.startsWith('rsi-');
    if (background && learningAttempts >= (config.learningDispatchLimit ?? config.learningCallBudget ?? 30)) {
      blocked.push({sessionId:options.sessionId,phase:'learning',reason:'EXPERIMENT_CALL_CAP',time:Date.now()});
      durable(dir + '/blocked-dispatches.json',blocked);
      throw Object.assign(new Error('Experiment learning dispatch limit reached'),{code:'BUDGET_EXHAUSTED'});
    }
    if (background) learningAttempts++;
    if (!background && (foreground >= dispatchLimit || phaseCalls >= phaseLimit)) throw new Error('Pilot foreground dispatch limit reached');
    if (!background) {foreground++; phaseCalls++;}
    const session = sessions.get(options.sessionId);
    if (session) await ctx.sessions.flush(session);
    else {
      // The native background bridge writes persistence directly and flushes before stream.
      assert.ok(background, 'Foreground request has no observed native session');
      const handle = await ctx.sessionPersistence.open(options.sessionId,'read');
      try {
        const stored = await handle.read();
        const restored = Session.fromRestore(options.sessionId,stored.events,handle.header,handle.inheritedEventCount,stored.eventState);
        assert.deepEqual([...restored.deriveMessages()],options.messages);
      } finally {await handle.close();}
    }
    const request = {sessionId:options.sessionId, phase:background?'learning':currentPhase,
      messages:structuredClone(options.messages), status:'DISPATCHING', usage:null, observedAt:Date.now()};
    requests.push(request); patch(); ledger();
    try {
      for await (const chunk of next()) {
        if (chunk.type === 'usage') {request.usage = chunk.usage; ledger();}
        yield chunk;
      }
      request.status = 'RETURNED';
    } catch (error) {request.status = 'ERROR'; request.error = error.message; throw error;}
    finally {request.finishedAt = Date.now(); ledger();}
  });
  ctx.on('tools/result', (execution, result) => {
    results.push({name:execution.name, callId:execution.callId, args:execution.arguments, isError:result.isError===true});
    durable(dir + '/tool-results.json', results); patch();
  });
  if (config.fixture) {
    class Fixture extends LlmAdapter {
      async *stream(options) {
        if (options.sessionId.startsWith('rsi-')) {
          assert.ok(config.fixtureLearning);
          const block={type:'text',text:options.tools?.length?'No reusable skill candidates.':'[]'};
          yield {type:'block-start',index:0,blockType:'text'};
          yield {type:'block-end',index:0,block};
          yield {type:'usage',usage:{inputTokens:13,outputTokens:7,totalTokens:20}};
          yield {type:'finish',reason:{kind:'stop'}};return;
        }
        const n = requests.filter(r=>r.sessionId===options.sessionId).length;
        if (config.interruptCheckpoint && n === 2) {
          console.log('RSI_CHECKPOINT_READY');
          await new Promise(()=>{});
        }
        const block = n === 1 ? {type:'tool-call', id:'fixture-write', name:'write',
          arguments:JSON.stringify({file_path:'/workspace/preflight-marker.txt', content:'isolated change\n'})}
          : {type:'text', text:'固定响应检查完成。'};
        yield {type:'block-start', index:0, blockType:block.type};
        yield {type:'block-end', index:0, block};
        yield {type:'usage', usage:{inputTokens:13, outputTokens:7, totalTokens:20}};
        yield {type:'finish', reason:{kind:n===1?'tool-calls':'stop'}};
      }
    }
    ctx.effect(()=>ctx.llm.registerAdapter(['pilot-fixture'], new Fixture()));
  }
  ctx.effect(()=>{
    const alive = setInterval(()=>{}, 1000);
    const timer = setTimeout(async()=>{
      let rsi;
      try {
        await cp('/opt/task-source', '/workspace', {recursive:true,verbatimSymlinks:true});
        git('init'); git('config','user.name','lsmax'); git('config','user.email','liushuai072002@163.com');
        git('add','-f','-A'); git('commit','-m','Pilot task baseline'); initialized = true;
        const baselineTree = git('write-tree').trim();
        if (config.expectedTree) assert.equal(baselineTree,config.expectedTree,'Task source tree mismatch');
        const djangoVersion = execFileSync('python',['-c','import django; print(django.get_version())'],{cwd:'/workspace',encoding:'utf8'}).trim();
        if (config.expectedVersion) assert.equal(djangoVersion,config.expectedVersion,'Task/scorer Django version mismatch');
        // get() is the official optional-service lookup; no hidden plugin dependency in baseline.
        rsi = ctx.get('rsi');
        if (config.arm === 'rsi') {assert.ok(rsi); await rsi.ready;}
        else assert.equal(rsi, undefined, 'Baseline must not instantiate RSI');
        const snapshot = async()=>rsi ? await rsi.request('snapshot',{cwd:'/workspace'}) : null;
        const before = await snapshot();
        if (before) assert.equal(before.settings.dailyCallBudget, config.learningCallBudget ?? 30);
        const exportedBefore = rsi ? await rsi.request('export',{cwd:'/workspace'}) : null;
        durable(dir + '/initial.json', {arm:config.arm, baselineTree, settings:before?.settings??null,
          baselineCommitTime:git('show','-s','--format=%ct','HEAD').trim(),
          djangoVersion,
          assets:exportedBefore, toolSchemas:ctx.tools.schemas().map(t=>t.name),
          skillCandidates:await ctx.skills.list({cwd:'/workspace'})});
        const task = JSON.parse(await readFile('/opt/rsi/task.json','utf8'));
        if (!config.fixture && config.instanceId !== 'preflight') assert.equal(task.instance_id,config.instanceId,'Task image/public ID mismatch');
        const phases = config.phases ?? [{name:'task',prompt:task.problem_statement,protocol:taskProtocol}];
        for (const phase of phases) {
          assert.match(phase.name,/^[a-zA-Z0-9_-]+$/);
          currentPhase = phase.name; phaseCalls = 0; phaseLimit = phase.dispatchLimit ?? dispatchLimit;
          if (phase.resetWorkspace) {git('reset','--hard','HEAD');git('clean','-fdx');}
          const phaseStartedAt=Date.now();
          const id = 'pilot-' + config.instanceId + '-' + phase.name;
          const handle = await ctx.agents.create({sessionId:id, meta:{cwd:'/workspace'},
            agentOptions:{provider:config.fixture?'pilot-fixture':'qwen', model:config.fixture?'fixture':'qwen3.8-27b', maxTokens:8192}});
          deadline = setTimeout(()=>handle.agent.cancel({kind:'hook',reason:'Pilot wall time limit reached'}),wallTimeMs);
          if(phase.protocol)handle.agent.inject(createUserMessage({source:{kind:'benchmark-protocol',form:'instructions'},content:[{type:'text',text:phase.protocol}]}));
          handle.agent.followup(createUserMessage({source:{kind:'user'},content:[{type:'text',text:phase.prompt}]}));
          await handle.agent.whenIdle(); await ctx.sessions.flush(handle.agent.session); clearTimeout(deadline); patch();
          durable(dir + '/prediction-' + phase.name + '.patch',git('diff','--cached','--binary','HEAD'));
          const stored = await ctx.sessionPersistence.open(id,'read');
          const outcome = await stored.read(); await stored.close();
          const stopReason = outcome.events.filter(e=>e.type==='turn/end').at(-1)?.data.reason;
          phaseResults.push({phase:phase.name, sessionId:id, stopReason, startedAt:phaseStartedAt, finishedAt:Date.now(), wallMs:Date.now()-phaseStartedAt, requests:requests.filter(r=>r.sessionId===id).length});
          durable(dir + '/phases.json', phaseResults);
          // Observe the default scheduler; never invoke learn/captureStored or inject a named Skill.
          const until = Date.now() + (config.settleMs ?? 90000);
          while (rsi && Date.now() < until) {
            durable(dir + '/scheduler.json', await snapshot());
            await new Promise(resolve=>setTimeout(resolve,1000));
          }
        }
        const after = await snapshot();
        if (rsi) durable(dir + '/assets.json', await rsi.request('export',{cwd:'/workspace'}));
        // Shutdown first: aborted background calls must settle before final usage and request audit.
        await ctx.root.fiber.dispose();
        const audit = await auditRequests(dir + '/model-requests.json', process.env.DSH_HOME + '/sessions', dir + '/reconstruction.json');
        const receipt = {runnerStatus:'COMPLETED', formalBenchmark:!!config.formal, arm:config.arm, fixture:!!config.fixture,
          instanceId:config.instanceId, officialResolved:null, taskDispatches:foreground,
          backgroundDispatches:requests.length-foreground, phases:phaseResults,
          before, after, blockedDispatches:blocked, learningDispatchLimit:config.learningDispatchLimit, toolResults:results, logReconstructionMatches:true,
          knownTokens:requests.reduce((n,r)=>n+(r.usage?.totalTokens??0),0),
          unknownUsage:requests.filter(r=>!r.usage).length,
          limitation:config.fixture?'Fixed responses validate runner plumbing; no effectiveness result.':config.formal?'One fixed formal arm; use paired official reports to interpret effect.':'Default-flow pilot; not a formal paired benchmark.'};
        durable(dir + '/receipt.json', receipt);
        console.log(JSON.stringify(receipt)); process.exit(0);
      } catch (error) {
        clearTimeout(deadline);
        try {patch(); ledger(); for (const session of sessions.values()) await ctx.sessions.flush(session);}
        catch (saveError) {durable(dir + '/save-error.json', {error:saveError.message});}
        durable(dir + '/failure.json', {runnerStatus:'ERROR', classification:'UNCLASSIFIED', officialResolved:null,
          error:error.message, phases:phaseResults, observedRequests:requests.length,
          unknownUsage:requests.filter(r=>!r.usage).length});
        console.error(error.stack); process.exit(1);
      }
    },0);
    return ()=>{clearInterval(alive);clearTimeout(timer);clearTimeout(deadline);};
  });
}
