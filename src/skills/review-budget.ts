import { AsyncLocalStorage } from 'node:async_hooks';

// Context belongs to one native review, so simultaneous human edits retain native limits.
const bodyBudget = new AsyncLocalStorage<number>();
export const GENERATED_SKILL_BODY_MAX_CHARS = 1500;
// Draft below the acceptance ceiling; a model cannot reliably edit to a few characters.
export const GENERATED_SKILL_BODY_DRAFT_CHARS = 1000;
export function withinSkillReviewBudget<T>(operation: () => T): T {
  return bodyBudget.run(GENERATED_SKILL_BODY_MAX_CHARS, operation);
}
export function checkSkillReviewBody(body: string) {
  const limit = bodyBudget.getStore();
  if (limit === undefined) return;
  const length = [...body].length;
  if (length > limit) throw new Error(`RSI_SKILL_BODY_BUDGET_EXCEEDED: main body has ${length} Unicode characters; limit ${limit}. Rebuild a compact body targeting at most ${GENERATED_SKILL_BODY_DRAFT_CHARS} Unicode characters (reduce this draft by at least ${length - GENERATED_SKILL_BODY_DRAFT_CHARS}), leaving headroom instead of approaching the ${limit} ceiling. Do not submit unchanged content again. Keep triggers, decisions and brief Evidence/Validation in SKILL.md; move detailed facts, scripts and evidence tables to native skill_files_write resources of the current skill and reference their relative paths. Preserve essential knowledge in those resources; use their returned skill_id/version for further writes.`);
}
