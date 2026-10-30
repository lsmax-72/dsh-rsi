import { build } from 'esbuild';
import { writeFile,rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';
import './verify-core.mjs';
import './verify-panel.mjs';
const root = dirname(dirname(fileURLToPath(import.meta.url)));
await rm(join(root,'lib'),{recursive:true,force:true});
const source = join(root, 'vendor/core/src');
const replacements = {
  [join(source, 'utils/clean-context-runner.ts')]: join(root, 'adapters/required-runner.ts'),
  [join(source, 'core/report/factory.ts')]: join(root, 'adapters/local-observability.ts'),
  [join(source, 'core/report/obs-logger.ts')]: join(root, 'adapters/local-obs-logger.ts'),
  [join(source, 'core/skill/skill-format.ts')]: join(root, 'adapters/skill-format.ts'),
};
await build({
  entryPoints: ['src/index.ts', 'src/core-entry.ts', 'src/model-bridge.ts', 'src/local-core.ts','src/rpc-contract.ts'],
  absWorkingDir: root, outdir: 'lib', bundle: true, splitting: true,
  banner:{js:'import { createRequire as __rsiCreateRequire } from \"node:module\"; const require = __rsiCreateRequire(import.meta.url);'},
  format: 'esm', platform: 'node', target: 'node24', packages: 'external', sourcemap: true,
  plugins: [{ name: 'local-host-seams', setup(b) {
    b.onResolve({ filter: /clean-context-runner\.js$|factory\.js$|obs-logger\.js$|skill-format\.js$/ }, args => {
      const target = join(args.resolveDir, args.path).replace(/\.js$/, '.ts');
      return replacements[target] ? { path: replacements[target] } : undefined;
    });
  } }],
});

const client=await build({entryPoints:['src/client/index.tsx'],absWorkingDir:root,bundle:true,write:false,format:'cjs',platform:'browser',target:'es2022',external:['react','react/jsx-runtime'],metafile:true,jsx:'automatic',loader:{'.css':'text'},logOverride:{'ignored-bare-import':'silent'},plugins:[{name:'panel-host-seams',setup(b){b.onResolve({filter:/^(react-i18next|tea-component)$/},args=>{if(!args.importer.replaceAll('\\','/').includes('/vendor/panel/'))throw Error('Unexpected panel dependency');return {path:join(root,args.path==='react-i18next'?'adapters/client-split-label.ts':'adapters/client-card.tsx')};});}}],banner:{js:'window.__ModuleLoader__.load({id:"dsh-rsi",factory:(require)=>{var module={exports:{}};var exports=module.exports;'},footer:{js:'return module.exports;}});'}});
// A package-root external also covers subpaths; assert the emitted result, not just the option.
if(Object.keys(client.metafile.inputs).some(path=>/(?:^|[/\\])node_modules[/\\]react(?:[/\\]|$)/.test(path)))throw new Error('Client contains an embedded React runtime');
await writeFile(join(root,'lib/client.js'),client.outputFiles[0].contents);
