import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, realpathSync,statSync,writeFileSync,readFileSync,unlinkSync } from 'node:fs';
import { resolve, join, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';

export const defaults = {
  enabled: true, learningEnabled: true, language: 'zh-CN',
  dailyCallBudget: 100, maxTokens: 4096, maxIterations: 16, timeoutMs: 180000,
  everyNConversations: 2, idleSeconds: 30, recallMaxChars: 6000,
};
export type Settings = typeof defaults;
export const languages = ['zh-CN', 'en', 'ja', 'ko', 'zh-TW'];
export function workspace(cwd: string) {
  if (typeof cwd !== 'string' || !isAbsolute(cwd)) throw new Error('工作区必须是绝对路径');
  const path = realpathSync(resolve(cwd));if(!statSync(path).isDirectory())throw new Error('工作区必须是目录');
  return { id: createHash('sha256').update(path).digest('hex').slice(0, 24), cwd: path };
}
export function validateSettings(value: any): Settings {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('设置格式无效');
  for (const key of Object.keys(value)) if (!(key in defaults)) throw new Error(`未知设置：${key}`);
  const settings = { ...defaults, ...value };
  if (typeof settings.enabled !== 'boolean' || typeof settings.learningEnabled !== 'boolean' || !languages.includes(settings.language)) throw new Error('开关或语言设置无效');
  for (const key of ['dailyCallBudget','maxTokens','maxIterations','timeoutMs','everyNConversations','idleSeconds','recallMaxChars'] as const) {
    if (!Number.isSafeInteger(settings[key]) || settings[key] < (key === 'dailyCallBudget' ? 0 : 1)) throw new Error(`设置 ${key} 无效`);
  }
  if (settings.everyNConversations > 1000 || settings.dailyCallBudget > 100000 || settings.maxTokens > 32768 || settings.maxIterations > 32 || settings.timeoutMs > 600000 || settings.idleSeconds > 86400 || settings.recallMaxChars > 32000) throw new Error('设置超过允许范围');
  return settings;
}

/** Plugin state only. Memory and Skill assets remain owned by the reused core. */
export class State {
  readonly db: DatabaseSync;
  private readonly lock: string;
  private readonly token=`${process.pid}:${Date.now()}`;
  constructor(readonly directory: string, initial: Partial<Settings> = {}) {
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    this.lock=join(directory,'owner.lock');
    try {writeFileSync(this.lock,this.token,{flag:'wx',mode:0o600});} catch(error:any) {
      if(error.code!=='EEXIST')throw error;
      const pid=Number(readFileSync(this.lock,'utf8').split(':')[0]);
      try {process.kill(pid,0);throw new Error('此资产目录已被另一个插件实例打开');} catch(cause:any) {if(cause.code!=='ESRCH')throw cause;}
      unlinkSync(this.lock);writeFileSync(this.lock,this.token,{flag:'wx',mode:0o600});
    }
    this.db = new DatabaseSync(join(directory, 'rsi-state.sqlite'));
    this.db.exec(`PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, scope TEXT NOT NULL, session TEXT NOT NULL, turn INTEGER NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL, stages TEXT NOT NULL DEFAULT '{}', error TEXT, created INTEGER NOT NULL, updated INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, cwd TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT -1);
      CREATE TABLE IF NOT EXISTS usage (id TEXT PRIMARY KEY, day TEXT NOT NULL, scope TEXT NOT NULL, task TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER);
      CREATE TABLE IF NOT EXISTS skill_controls (scope TEXT NOT NULL, id TEXT NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(scope,id));`);
    if (!this.get('settings')) this.set('settings', validateSettings(initial));
    this.db.prepare("UPDATE jobs SET status='interrupted', error='上次运行中断，可能已有部分资产更新' WHERE status='running'").run();
  }
  get<T = any>(key: string): T | undefined { const row = this.db.prepare('SELECT value FROM kv WHERE key=?').get(key); return row ? JSON.parse(row.value as string) : undefined; }
  set(key: string, value: any) { this.db.prepare('INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').run(key, JSON.stringify(value)); }
  settings(): Settings { return validateSettings(this.get('settings')); }
  configure(value: any) { const settings = validateSettings({ ...this.settings(), ...value }); this.set('settings', settings); return settings; }
  rememberSource(id: string, cwd: string) { this.db.prepare('INSERT OR IGNORE INTO sources(id,cwd) VALUES (?,?)').run(id,cwd); }
  sources(): any[] { return this.db.prepare('SELECT * FROM sources').all(); }
  enqueue(payload: any) {
    const id = `${payload.sessionId}:${payload.turn}`, now = Date.now();
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const result = this.db.prepare("INSERT OR IGNORE INTO jobs(id,scope,session,turn,status,payload,created,updated) VALUES (?,?,?,?,'pending',?,?,?)").run(id,payload.scope,payload.sessionId,payload.turn,JSON.stringify(payload),now,now);
      this.db.prepare('UPDATE sources SET cursor=MAX(cursor,?) WHERE id=?').run(payload.endSeq,payload.sessionId);
      this.db.exec('COMMIT');
      return result.changes > 0;
    } catch (error) { this.db.exec('ROLLBACK'); throw error; }
  }
  jobs(scope?: string): any[] { return (scope ? this.db.prepare('SELECT * FROM jobs WHERE scope=? ORDER BY created').all(scope) : this.db.prepare('SELECT * FROM jobs ORDER BY created').all()).map(row => ({ ...row, payload: JSON.parse(row.payload as string), stages: JSON.parse(row.stages as string) })); }
  updateJob(id: string, status: string, stages?: any, error?: string) { this.db.prepare('UPDATE jobs SET status=?,stages=COALESCE(?,stages),error=?,updated=? WHERE id=?').run(status, stages ? JSON.stringify(stages) : null,error ?? null,Date.now(),id); }
  reserve(id: string, scope: string, task: string, manual = false) {
    const settings = this.settings(), day = new Date().toISOString().slice(0,10);
    if (!settings.enabled || (!settings.learningEnabled && !manual)) throw Object.assign(new Error('自动学习已暂停'), { code: 'LEARNING_PAUSED' });
    const used = this.db.prepare('SELECT COUNT(*) AS count FROM usage WHERE day=?').get(day)!.count as number;
    if (used >= settings.dailyCallBudget) throw Object.assign(new Error('今日学习调用预算已用完'), { code: 'BUDGET_EXHAUSTED' });
    this.db.prepare("INSERT INTO usage(id,day,scope,task,status) VALUES (?,?,?,?,'dispatched')").run(id,day,scope,task);
  }
  settle(id: string, usage: any, status: string) { this.db.prepare('UPDATE usage SET status=?,input_tokens=?,output_tokens=?,total_tokens=? WHERE id=?').run(status,usage?.inputTokens ?? null,usage?.outputTokens ?? null,usage?.totalTokens ?? null,id); }
  usage() {
    const day = new Date().toISOString().slice(0,10);
    return this.db.prepare('SELECT day,COUNT(*) AS calls,SUM(input_tokens) AS inputTokens,SUM(output_tokens) AS outputTokens,SUM(total_tokens) AS totalTokens,SUM(input_tokens IS NULL) AS unknownUsage FROM usage WHERE day=? GROUP BY day').get(day) ?? { day, calls:0, inputTokens:null, outputTokens:null,totalTokens:null,unknownUsage:0 };
  }
  disabled(scope: string, id: string) { return !!this.db.prepare('SELECT disabled FROM skill_controls WHERE scope=? AND id=?').get(scope,id)?.disabled; }
  disable(scope: string, id: string, disabled: boolean) { this.db.prepare('INSERT INTO skill_controls VALUES (?,?,?) ON CONFLICT(scope,id) DO UPDATE SET disabled=excluded.disabled').run(scope,id,Number(disabled)); }
  close() { this.db.close();if(readFileSync(this.lock,'utf8')===this.token)unlinkSync(this.lock); }
}
