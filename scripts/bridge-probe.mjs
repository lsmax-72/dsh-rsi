import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { LlmAdapter } from '@deepseek-ai/dsh-llm';
import { Session } from '@deepseek-ai/dsh-session';

export const name = 'dsh-rsi-bridge-probe';
export const inject = ['rsi', 'llm', 'sessionPersistence'];
const content = n => `---\nname: rsi-probe\ndescription: 原生版本写入验证\n---\n\n第${n}版：先检查测试环境，再运行目标测试。\n`;
const ids = { user_id: 'local-user', team_id: 'probe-workspace', agent_id: 'local-agent' };
const hash = value => createHash('sha256').update(JSON.stringify(value)).digest('hex');

export function apply(ctx, config) {
  const requests = [];
  let replies = [];
  class FixtureAdapter extends LlmAdapter {
    async *stream(options) {
      const { signal, ...request } = options;
      requests.push(structuredClone(request));
      const reply = replies.shift();
      assert.ok(reply, 'Unexpected model request');
      if (reply.waitForAbort) {
        await new Promise((_, reject) => {
          if (signal.aborted) reject(signal.reason);
          else signal.addEventListener('abort', () => reject(signal.reason), { once: true });
        });
      }
      if (reply.error) { yield { type: 'finish', reason: { kind: 'error', failure: { code: 'PROBE_FAILURE', message: 'deterministic model failure' } } }; return; }
      const block = reply.call ? { type: 'tool-call', ...reply.call } : { type: 'text', text: reply.text };
      yield { type: 'block-start', index: 0, blockType: block.type };
      yield { type: 'block-end', index: 0, block };
      yield { type: 'usage', usage: { inputTokens: 13, outputTokens: 7, totalTokens: 20 } };
      yield { type: 'finish', reason: { kind: reply.call ? 'tool-calls' : 'stop' } };
    }
  }
  ctx.effect(() => ctx.llm.registerAdapter(['rsi-probe'], new FixtureAdapter()));
  ctx.effect(() => {
    // An AbortSignal timeout is unref'd; keep this otherwise idle CLI probe alive.
    const keepAlive = setInterval(() => {}, 1000);
    const timer = setTimeout(async () => {
      try {
        const core = await ctx.rsi.ready;
        if (config.phase === 'restore') {
          const first = JSON.parse(await readFile(join(config.root, 'result.json'), 'utf8'));
          const list = await core.skills.list(ids);
          assert.equal(list.items[0].version, 2);
          assert.equal(list.items[0].content, content(2));
          assert.equal((await core.readMemories()).length, 1);
          for (const expected of first.logs) {
            const handle = await ctx.sessionPersistence.open(expected.id, 'read');
            try {
              const stored = await handle.read();
              assert.equal(hash(stored.events), expected.sha256);
              Session.fromRestore(handle.id, stored.events, handle.header, handle.inheritedEventCount, stored.eventState);
            } finally { await handle.close(); }
          }
          assert.equal(requests.length, 0);
          await writeFile(join(config.root, 'restored.json'), JSON.stringify({ status: 'PASS', logsRestored: first.logs.length, modelDispatches: 0 }));
          core.close();
          process.exit(0);
        }
        // Replies are fixed test fixtures, never scored as model learning quality.
        replies = [{ text: '桥接成功。' }];
        assert.equal(await ctx.rsi.runner.run({ taskId: 'text', prompt: '纯文本验证', systemPrompt: '输出中文' }), '桥接成功。');
        replies = [{ text: JSON.stringify([{ scene_name: '测试习惯', message_ids: ['m1'], memories: [{ content: '用户希望修改代码后运行目标测试。', type: 'instruction', priority: 70, source_message_ids: ['m1'], metadata: {} }] }]) }];
        const memory = await core.extractMemories({ sessionKey: 'probe-source', messages: [{ id: 'm1', role: 'user', content: '请记住我在这个项目中希望修改代码后先运行目标测试，失败时保留完整报错并解释原因。', timestamp: Date.now() }] });
        assert.equal(memory.storedCount, 1);
        assert.equal((await core.readMemories()).length, 1);
        const extractor = core.createSkillExtractor(ctx.rsi.language);
        const input = { ...ids, messages: [{ role: 'user', content: '任务完成后总结通用的测试步骤。' }] };
        replies = [{ call: { id: 'call-create', name: 'skill_create', arguments: JSON.stringify({ name: 'rsi-probe', content: content(1) }) } }, { text: '已保存技能。' }];
        const created = await extractor.extract(input);
        assert.equal(created.candidates[0].version, 1);
        const skillId = created.candidates[0].skill_id;
        replies = [{ call: { id: 'call-update', name: 'skill_update', arguments: JSON.stringify({ skill_id: skillId, expected_version: 1, content: content(2) }) } }, { text: '已更新技能。' }];
        const updated = await extractor.extract(input);
        assert.equal(updated.candidates[0].version, 2);
        assert.equal((await core.skills.get({ ...ids, skill_id: skillId, version: 1 })).content, content(1));
        assert.equal((await core.skills.get({ ...ids, skill_id: skillId })).content, content(2));
        // Invalid arguments never reach a mutating implementation.
        let executed = 0;
        replies = [{ call: { id: 'bad-args', name: 'check', arguments: '{"value":"bad"}' } }, { text: '参数已拒绝。' }];
        const { jsonSchema } = await import('ai');
        const check = { inputSchema: jsonSchema({ type: 'object', properties: { value: { type: 'number' } }, required: ['value'], additionalProperties: false }), execute: () => { executed++; return 'ok'; } };
        await ctx.rsi.runner.run({ taskId: 'invalid-args', prompt: '检查参数', enableTools: true, tools: { check } });
        assert.equal(executed, 0);
        assert.equal(requests.at(-1).messages.at(-1).isError, true);
        replies = [{ call: { id: 'limited', name: 'check', arguments: '{"value":1}' } }];
        await assert.rejects(ctx.rsi.runner.run({ taskId: 'limit', prompt: '迭代上限', maxIterations: 1, enableTools: true, tools: { check } }), { code: 'ITERATION_LIMIT' });
        assert.equal(executed, 0);
        replies = [{ error: true }];
        await assert.rejects(ctx.rsi.runner.run({ taskId: 'error', prompt: '失败路径' }), { code: 'PROBE_FAILURE' });
        const abort = new AbortController(); abort.abort();
        const before = requests.length;
        await assert.rejects(ctx.rsi.runner.run({ taskId: 'pre-abort', prompt: '取消路径', signal: abort.signal }));
        assert.equal(requests.length, before);
        replies = [{ waitForAbort: true }];
        await assert.rejects(ctx.rsi.runner.run({ taskId: 'timeout', prompt: '超时路径', timeoutMs: 100 }));
        assert.equal(replies.length, 0);
        const logs = [];
        for (const id of new Set(requests.map(r => r.sessionId))) {
          const handle = await ctx.sessionPersistence.open(id, 'read');
          try {
            const { events, eventState } = await handle.read();
            const matches = requests.filter(r => r.sessionId === id);
            const headers = events.filter(e => e.type === 'request/header');
            assert.equal(headers.length, matches.length);
            for (let index = 0; index < headers.length; index++) {
              const event = headers[index];
              const restored = Session.fromRestore(id, events.slice(0, event.seq + 1), handle.header, handle.inheritedEventCount, eventState);
              assert.deepEqual([...restored.deriveMessages()], matches[index].messages);
              assert.deepEqual(event.data.header.tools ?? [], matches[index].tools ?? []);
              for (const [key, value] of Object.entries(event.data.header.config)) assert.deepEqual(matches[index][key], value);
            }
            assert.equal(events.at(-1).type, 'turn/end');
            for (const event of events.filter(e => e.type === 'assistant/message')) {
              assert.deepEqual(event.data.usage, { inputTokens: 13, outputTokens: 7, totalTokens: 20 });
            }
            logs.push({ id, sha256: hash(events), requests: headers.length });
          } finally { await handle.close(); }
        }
        const result = { status: 'PASS', realProviderRequests: 0, taskCommandsExecuted: 0, fixtureModelDispatches: requests.length, memoryRecords: 1, skillVersions: 2, logs,
          checks: ['native-memory-extraction-and-write', 'native-skill-tool-create-update', 'historical-skill-version', 'request-reconstruction', 'reported-usage-persistence', 'invalid-tool-arguments', 'iteration-limit-no-mutation', 'model-error', 'pre-abort-no-dispatch', 'timeout'],
          limitation: 'Deterministic adapter fixtures validate integration and persistence, not model quality, automatic learning, foreground consumption, UI or sandbox isolation.' };
        await writeFile(join(config.root, 'result.json'), JSON.stringify(result, null, 2));
        core.close();
        console.log(JSON.stringify(result));
        process.exit(0);
      } catch (error) { console.error(error.stack); process.exit(1); }
    }, 0);
    return () => { clearTimeout(timer); clearInterval(keepAlive); };
  });
}
