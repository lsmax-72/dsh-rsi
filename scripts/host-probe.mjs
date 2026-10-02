import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';

export const name = 'dsh-rsi-host-probe';
export const inject = ['skills', 'sessions', 'llm'];

/** Diagnostic plugin: exercises host APIs without running an agent or calling a model. */
export function apply(ctx, config) {
  const root = config.dataRoot;
  const events = [];
  let modelCalls = 0;
  ctx.on('llm/stream', () => {
    modelCalls += 1;
    throw new Error('The host probe does not permit model calls.');
  });
  ctx.on('session/event', (_session, event) => events.push(event));
  // Provider rows mount concurrently; discovery is the readiness observation.
  ctx.effect(() => {
    const timer = setTimeout(async () => {
      const file = join(root, 'skills/rsi-probe/SKILL.md');
      let previous;
      try {
        const lookup = { cwd: root };
        let catalog = [];
        for (let attempt = 0; attempt < 100; attempt += 1) {
          catalog = await ctx.skills.list(lookup);
          if (catalog.some(skill => skill.name === 'rsi-probe')) break;
          await new Promise(resolve => setTimeout(resolve, 20));
        }
        assert.deepEqual(catalog.map(skill => skill.name), ['rsi-probe']);
        const first = await ctx.skills.get('rsi-probe', lookup);
        assert.ok(first.content.includes('版本一'));
        assert.equal(first.provider, 'dsh-rsi-probe-files');
        previous = await readFile(file, 'utf8');
        await writeFile(file, previous.replace('版本一', '版本二'));
        const second = await ctx.skills.get('rsi-probe', lookup);
        assert.ok(second.content.includes('版本二'));

        const session = ctx.sessions.create(undefined, { meta: { cwd: root } });
        session.append('turn/start', { turn: 1 });
        session.append('user/message', {
          id: randomUUID(), role: 'user', source: { kind: 'user' },
          content: [{ type: 'text', text: second.content }],
        }, { surfaceOp: 'append' });
        session.append('turn/end', { turn: 1, reason: { kind: 'completed' } });
        assert.equal(session.deriveMessages()[0].content[0].text, second.content);
        assert.ok(events.some(event => event.type === 'turn/end'));
        const durabilityListenerParticipated = await ctx.sessions.flush(session);

        const { DatabaseSync } = await import('node:sqlite');
        const db = new DatabaseSync(':memory:');
        try {
          db.exec('CREATE TABLE probe (value TEXT); INSERT INTO probe VALUES (\'ready\')');
          assert.equal(db.prepare('SELECT value FROM probe').get().value, 'ready');
        } finally {
          db.close();
        }
        await writeFile(file, previous);
        assert.equal(modelCalls, 0);
        const result = {
          status: 'PASS', modelCalls, sessionId: session.id, durabilityListenerParticipated,
          checks: ['isolated-skill-discovery', 'skill-body-reload', 'session-event-observation', 'logged-message-projection', 'session-flush-api', 'builtin-sqlite'],
          provider: second.provider,
          limitation: 'Interface probe only. No agent task, learning extraction, model inference, or persistence round trip was executed.',
        };
        await writeFile(join(root, 'result.json'), JSON.stringify(result, null, 2) + '\n');
        console.log(JSON.stringify(result));
        // This one-shot diagnostic profile has no task or model work to drain.
        process.exit(0);
      } catch (error) {
        if (previous !== undefined) await writeFile(file, previous);
        console.error(error.stack);
        process.exit(1);
      }
    }, 0);
    return () => clearTimeout(timer);
  });
}
