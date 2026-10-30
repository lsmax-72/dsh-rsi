import { validateSkillFile as nativeValidate } from '../vendor/core/src/core/skill/skill-format.ts';
import type { SkillFile } from '../vendor/core/src/core/skill/types.js';
import { checkSkillReviewBody } from '../src/skill-review-budget.js';
export * from '../vendor/core/src/core/skill/skill-format.ts';

// Native parsing, patching and version writes all converge on this validation seam.
export function validateSkillFile(file: SkillFile) {
  nativeValidate(file);
  checkSkillReviewBody(file.body);
}
