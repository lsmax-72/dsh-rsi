import { AsyncLocalStorage } from 'node:async_hooks';

// Context belongs to one native review, so simultaneous human edits retain native limits.
const bodyBudget = new AsyncLocalStorage<number>();
export const GENERATED_SKILL_BODY_MAX_CHARS = 1500;
export function withinSkillReviewBudget<T>(operation: () => T): T {
  return bodyBudget.run(GENERATED_SKILL_BODY_MAX_CHARS, operation);
}
export function checkSkillReviewBody(body: string) {
  const limit = bodyBudget.getStore();
  if (limit === undefined) return;
  const length = [...body].length;
  if (length > limit) throw new Error(`RSI_SKILL_BODY_BUDGET_EXCEEDED: main body has ${length} Unicode characters; limit ${limit}. Keep triggers, decisions and brief Evidence/Validation in SKILL.md. Move long scripts and detailed tables to native skill_files_write resources and reference their relative paths. Do not drop essential knowledge.`);
}
