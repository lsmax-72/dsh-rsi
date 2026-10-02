import { asSchema } from 'ai';
import Ajv from 'ajv';
import { randomUUID } from 'node:crypto';
import { createStorageTools } from './core-entry.js';
import {
  BlockAssembler, createSystemMessage, createUserMessage, createToolResultMessage,
} from '@deepseek-ai/dsh-llm';

export interface RunParams {
  prompt: string;
  systemPrompt?: string;
  taskId: string;
  sessionId?: string;
  maxTokens?: number;
  maxIterations?: number;
  enableTools?: boolean;
  tools?: Record<string, unknown>;
  timeoutMs?: number;
  signal?: AbortSignal;
  abortSignal?: AbortSignal;
  storage?: any;
  storagePrefix?: string;
}

export class BridgeError extends Error {
  constructor(public code: string, message: string) { super(message); this.name = 'BridgeError'; }
}

function freeze<T>(value: T): T {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

/** Owns one background Session and its real persistence handle per core invocation. */
export class DshModelRunner {
  constructor(private ctx: any, private options: {
    cwd: string;
    resolveRoute: () => { provider: string; model: string; reasoningEffort?: string };
    maxTokens: number;
    timeoutMs: number;
    maxIterations: number;
    onSession?: (sessionId: string, taskId: string, sourceSessionId?: string) => Promise<void>;
    language?: () => string;
    beforeRequest?: (id: string, taskId: string) => void;
    afterRequest?: (id: string, usage: any, status: string) => void;
  }) {}

  async run(params: RunParams): Promise<string> {
    const maxTokens = params.maxTokens ?? this.options.maxTokens;
    const maxIterations = params.maxIterations ?? this.options.maxIterations;
    const timeoutMs = params.timeoutMs ?? this.options.timeoutMs;
    for (const [name, value] of Object.entries({ maxTokens, maxIterations, timeoutMs })) {
      if (!Number.isSafeInteger(value) || value <= 0) throw new BridgeError('INVALID_LIMIT', `${name} must be a positive integer`);
    }
    const signals = [params.signal, params.abortSignal].filter(Boolean) as AbortSignal[];
    const signal = AbortSignal.any([...signals, AbortSignal.timeout(timeoutMs)]);
    signal.throwIfAborted();
    const route = this.options.resolveRoute();
    if (!route.provider || !route.model) throw new BridgeError('MISSING_ROUTE', 'A dsh provider and model are required');
    const enableTools = params.enableTools ?? !!params.storage;
    const tools = enableTools ? await this.prepareTools(params.tools ?? (params.storage ? createStorageTools(params.storage, params.storagePrefix ?? '') : {})) : [];
    // Preparation detaches this Session from the foreground agent's lifetime.
    const session = this.ctx.sessions.prepare(`rsi-${randomUUID()}`, { meta: { cwd: this.options.cwd } });
    const handle = await this.ctx.sessionPersistence.create(session.header, { inheritedEventCount: session.inheritedEventCount });
    const pending: any[] = [];
    let journalFailed = false;
    const append = (type: string, data: any, opts?: any) => {
      const event = opts === undefined ? session.append(type, data) : session.append(type, data, opts);
      pending.push(event);
    };
    const flush = async () => {
      try {
        if (pending.length) { const batch = pending.splice(0); await handle.append(batch); }
        await handle.flush();
      } catch (error) {
        journalFailed = true;
        throw error;
      }
    };
    let ended = false;
    let turnStarted = false;
    let activeStep: number | undefined;
    const unresolvedCalls = new Map<string, any>();
    const seenCallIds = new Set<string>();
    try {
      await this.options.onSession?.(session.id, params.taskId, params.sessionId);
      append('turn/start', { turn: 1 });
      turnStarted = true;
      append('step/start', { turn: 1, step: 1 });
      activeStep = 1;
      const language = this.options.language?.();
      const system = (params.systemPrompt ?? '') + (language ? `\nWrite generated asset prose in ${language}. Preserve code, commands, paths and API identifiers.` : '');
      append('system/message', { turn: 1, step: 1, message: createSystemMessage(system) }, { surfaceOp: 'append' });
      append('user/message', createUserMessage({ source: { kind: 'user' }, content: [{ type: 'text', text: params.prompt }] }), { surfaceOp: 'append' });
      for (let step = 1; step <= maxIterations; step++) {
        signal.throwIfAborted();
        // Bound preparation uses the same adapter generation for defaults and dispatch.
        // prepared.stream passes through the official llm/stream waterfall.
        const prepared = await this.ctx.llm.prepareCall({ ...route, maxTokens }, signal);
        const header = {
          config: prepared.config,
          ...(Object.keys(prepared.adapterDefaults).length ? { adapterDefaults: prepared.adapterDefaults } : {}),
          ...(tools.length ? { tools: tools.map(t => t.declaration) } : {}),
        };
        if (step > 1) { append('step/start', { turn: 1, step }); activeStep = step; }
        append('request/header', { header, reason: step === 1 ? 'initial' : 'change', ...(step === 1 ? { startsSeries: true } : {}) });
        if (prepared.context) append('request/context', prepared.context);
        await flush(); // No provider dispatch is allowed before the request is durable.
        signal.throwIfAborted();
        const options = freeze({ ...header.config, messages: [...session.deriveMessages()], ...(header.tools ? { tools: header.tools } : {}), sessionId: session.id });
        const assembler = new BlockAssembler();
        const stream: any[] = [];
        let finish: any;
        const requestId = `${session.id}:${step}`;
        try {
          this.options.beforeRequest?.(requestId, params.taskId);
          for await (const chunk of prepared.stream(Object.freeze({ ...options, signal }))) {
            stream.push({ type: 'chunk', time: Date.now(), chunk: structuredClone(chunk) });
            assembler.push(chunk);
            if (chunk.type === 'finish') finish = chunk.reason;
          }
        } catch (error) {
          this.options.afterRequest?.(requestId, assembler.usage, 'failed');
          append('assistant/attempt', { turn: 1, step, stream });
          throw error;
        }
        this.options.afterRequest?.(requestId, assembler.usage, finish?.kind ?? 'incomplete');
        if (!finish || finish.kind === 'error' || finish.kind === 'aborted' || finish.kind === 'max-tokens') {
          append('assistant/attempt', { turn: 1, step, stream });
          throw new BridgeError(finish?.failure?.code ?? (finish?.kind === 'max-tokens' ? 'OUTPUT_TRUNCATED' : 'INCOMPLETE_STREAM'), finish?.failure?.message ?? 'Model stream did not complete successfully');
        }
        if (signal.aborted) { append('assistant/attempt', { turn: 1, step, stream }); signal.throwIfAborted(); }
        const message = assembler.message({ provider: route.provider, model: route.model });
        const calls = message.content.filter((b: any) => b.type === 'tool-call');
        for (const call of calls) {
          if (seenCallIds.has(call.id)) {
            append('assistant/attempt', { turn: 1, step, stream });
            throw new BridgeError('DUPLICATE_TOOL_CALL', 'Tool call identifiers must be unique within the session');
          }
          seenCallIds.add(call.id);
        }
        if (calls.length && (finish.kind !== 'tool-calls' || step === maxIterations)) {
          append('assistant/attempt', { turn: 1, step, stream });
          throw new BridgeError(step === maxIterations ? 'ITERATION_LIMIT' : 'INVALID_TOOL_FINISH', 'Tool request cannot be executed within the extraction limits');
        }
        append('assistant/message', { turn: 1, step, message, stream, ...(assembler.usage ? { usage: assembler.usage } : {}) }, { surfaceOp: 'append' });
        if (calls.length === 0) {
          if (finish.kind !== 'stop') throw new BridgeError('MISSING_TOOL_CALL', 'Model requested tools without a complete call');
          const text = message.content.filter((b: any) => b.type === 'text').map((b: any) => b.text).join('');
          if (!text.trim()) throw new BridgeError('EMPTY_RESPONSE', 'Model returned no final text');
          append('step/end', { turn: 1, step });
          activeStep = undefined;
          append('turn/end', { turn: 1, reason: { kind: 'completed' } });
          ended = true;
          await flush();
          return text;
        }
        for (const call of calls) unresolvedCalls.set(call.id, call);
        // Persist the requested mutations before execution; no filesystem/shell tools are invented.
        for (const call of calls) append('tool/call', { turn: 1, step, callId: call.id, name: call.name, arguments: call.arguments });
        await flush();
        for (const call of calls) {
          signal.throwIfAborted();
          let text: string, isError = false;
          try {
            const tool = tools.find(t => t.declaration.name === call.name);
            if (!tool) throw new BridgeError('UNKNOWN_TOOL', `Unknown extraction tool: ${call.name}`);
            const args = JSON.parse(call.arguments);
            if (!tool.validate(args)) throw new BridgeError('INVALID_TOOL_ARGUMENTS', 'Arguments do not match the logged tool schema');
            const result = await tool.execute(args, { toolCallId: call.id, messages: options.messages, abortSignal: signal });
            text = typeof result === 'string' ? result : JSON.stringify(result);
            if (text === undefined) throw new BridgeError('INVALID_TOOL_RESULT', 'Tool result is not serializable');
          } catch (error: any) {
            isError = true;
            text = JSON.stringify({ error: error.code ?? 'TOOL_ERROR', message: error.message });
          }
          append('tool/result', { turn: 1, step, message: createToolResultMessage({ callId: call.id, content: [{ type: 'text', text }], isError }) }, { surfaceOp: 'append' });
          unresolvedCalls.delete(call.id);
          await flush();
        }
        append('step/end', { turn: 1, step });
        activeStep = undefined;
      }
      throw new BridgeError('ITERATION_LIMIT', 'Extraction exceeded the model call limit');
    } catch (error: any) {
      if (!journalFailed) {
        for (const call of unresolvedCalls.values()) {
          append('tool/result', { turn: 1, step: activeStep, message: createToolResultMessage({ callId: call.id,
            content: [{ type: 'text', text: JSON.stringify({ error: 'EXECUTION_INCOMPLETE', message: 'Extraction ended before this tool returned a recorded result' }) }], isError: true }) }, { surfaceOp: 'append' });
        }
        if (activeStep !== undefined) append('step/end', { turn: 1, step: activeStep });
        if (turnStarted && !ended) append('turn/end', { turn: 1, reason: signal.aborted ? { kind: 'aborted', reason: { kind: 'legacy' } } : { kind: 'error', error: { code: error.code ?? 'EXTRACTION_ERROR', message: error.message } } });
        await flush();
      }
      throw error;
    } finally { await handle.close(); }
  }

  private async prepareTools(dict: Record<string, unknown>) {
    const ajv = new Ajv({ strict: false, allErrors: true });
    return Promise.all(Object.entries(dict).map(async ([name, value]) => {
      const tool = value as any;
      if (typeof tool.execute !== 'function' || !tool.inputSchema) throw new BridgeError('UNSUPPORTED_TOOL', `Unsupported extraction tool: ${name}`);
      const parameters = structuredClone(await asSchema(tool.inputSchema).jsonSchema);
      return { declaration: freeze({ name, description: tool.description ?? '', parameters }), validate: ajv.compile(parameters), execute: tool.execute };
    }));
  }
}
