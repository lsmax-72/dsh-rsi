import { createRequire } from 'node:module';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

/**
 * Load a package the running Harness already owns.
 *
 * Importing `@deepseek-ai/*` from the plugin's own node_modules would create a
 * second Cordis/Typert/Tool instance next to the host's. Resolving from the
 * running installation first keeps both halves on the same module instance;
 * the plugin-local package is only a fallback for hosts that expose neither
 * `DSH_INSTALL_DIR` nor a resolvable entry script.
 */
const cache = new Map<string, Promise<any>>();

function anchors(): string[] {
  return [
    process.env.DSH_INSTALL_DIR ? join(process.env.DSH_INSTALL_DIR, 'package.json') : undefined,
    process.argv[1],
    import.meta.url,
  ].filter((anchor): anchor is string => Boolean(anchor));
}

async function load(specifier: string): Promise<any> {
  for (const anchor of anchors()) {
    try {
      const require = createRequire(anchor);
      return await import(pathToFileURL(require.resolve(specifier)).href);
    } catch {
      // Try the next anchor; the plugin-local copy is the last resort.
    }
  }
  return import(specifier);
}

export function hostModule(specifier: string): Promise<any> {
  let pending = cache.get(specifier);
  if (!pending) {
    pending = load(specifier);
    cache.set(specifier, pending);
  }
  return pending;
}

/** The host-owned modules the two plugin entry points import at load time. */
export const host = {
  llm: await hostModule('@deepseek-ai/dsh-llm'),
  tools: await hostModule('@deepseek-ai/dsh-tools'),
  typert: await hostModule('@deepseek-ai/dsh-typert-protocol'),
};
