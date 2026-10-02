import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const root = dirname(dirname(fileURLToPath(import.meta.url)));
const manifest = JSON.parse(await readFile(join(root, 'vendor/core/manifest.json'), 'utf8'));
for (const entry of manifest.files) {
  const bytes = await readFile(join(root, 'vendor/core/src', entry.path));
  if (createHash('sha256').update(bytes).digest('hex') !== entry.sha256) {
    throw new Error(`Vendored source changed without a manifest update: ${entry.path}`);
  }
}
console.log(`Verified ${manifest.files.length} core source files at ${manifest.revision}`);
