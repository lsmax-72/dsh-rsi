import type { SkillCore } from '../vendor/core/src/core/skill/skill-core.js';

/** Display IDs in native extraction prefixes; tools must retain the original core. */
export function prefixPresentationCore(core: SkillCore): SkillCore {
  const present = <T extends { name: string; skill_id: string; version: number }>(skill: T): T => ({
    ...skill, name: `${skill.name} [skill_id=${skill.skill_id}, version=${skill.version}]`,
  });
  return new Proxy(core, {
    get(target, key) {
      if (key === 'list') return async (input: Parameters<SkillCore['list']>[0]) => {
        const page = await target.list(input);
        return { ...page, items: page.items.map(present) };
      };
      if (key === 'search') return async (input: Parameters<SkillCore['search']>[0]) => {
        const hits = await target.search(input);
        return hits.map(hit => ({ ...hit, skill: present(hit.skill) }));
      };
      const value = Reflect.get(target, key, target);
      return typeof value === 'function' ? value.bind(target) : value;
    },
  });
}
