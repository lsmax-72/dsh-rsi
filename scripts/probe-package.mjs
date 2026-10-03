import assert from 'node:assert/strict';
import {mkdtemp,cp,mkdir,readFile,writeFile,access,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
const project=fileURLToPath(new URL('..',import.meta.url));
const root=await mkdtemp(join(tmpdir(),'dsh-rsi-package-'));
const cache=join(root,'cache');
const npmCli=process.env.npm_execpath;
function run(args,cwd){
  const result=spawnSync(npmCli?process.execPath:'npm',npmCli?[npmCli,...args]:args,{cwd,encoding:'utf8',timeout:180000,maxBuffer:8*1024*1024});
  if(result.error||result.status!==0)throw Error(`npm ${args.join(' ')} failed: ${result.error?.message??''}\n${result.stdout}\n${result.stderr}`);
  return result.stdout;
}
try{
  const source=join(root,'source');await mkdir(source);
  for(const path of ['src','adapters','vendor','scripts','package.json','package-lock.json','cordis.patch.yml','README.md'])await cp(join(project,path),join(source,path),{recursive:true});
  await assert.rejects(access(join(source,'lib/index.js')));
  // Mimic a fresh checkout: lifecycle scripts must generate the ignored output directory.
  run(['ci','--include=dev','--ignore-scripts=false','--cache',cache],source);
  const config=JSON.parse(await readFile(join(source,'package.json'),'utf8'));
  for(const path of Object.values(config.exports))await access(join(source,path));
  const client=await readFile(join(source,'lib/client.js'),'utf8');
  assert.ok(client.includes('require("react")'));assert.ok(client.includes('require("react/jsx-runtime")'));
  assert.equal(/node_modules[/\\]react[/\\]/.test(client),false);
  const packed=run(['pack','--json','--cache',cache],source);
  // prepare logs may precede npm's JSON payload.
  const [pack]=JSON.parse(packed.startsWith('[')?packed:packed.slice(packed.lastIndexOf('\n[')+1));
  assert.ok(pack.files.some(entry=>entry.path==='lib/index.js'));
  assert.ok(pack.files.some(entry=>entry.path==='lib/client.js'));
  const consumer=join(root,'consumer');await mkdir(consumer);
  await writeFile(join(consumer,'package.json'),JSON.stringify({name:'rsi-package-fixture',private:true,type:'module'}));
  // A registry/tarball consumer has no build tool; it must use the shipped artifacts.
  run(['install','--omit=dev','--ignore-scripts','--cache',cache,join(source,pack.filename)],consumer);
  await assert.rejects(access(join(consumer,'node_modules/esbuild')));
  const smoke=String.raw`
    import assert from 'node:assert/strict';
    import {readFile,mkdtemp,rm} from 'node:fs/promises';
    import {join} from 'node:path';
    import {tmpdir} from 'node:os';
    import {createRequire} from 'node:module';
    const require=createRequire(import.meta.url);
    const core=await import('dsh-rsi/core');
    const query=core.buildFtsQuery('中文测试环境');
    const binaries=Object.keys(require.cache).filter(path=>path.endsWith('.node')&&path.includes('jieba'));
    assert.ok(binaries.length,'Native tokenizer was not loaded through the core');
    const nativeRoot=await mkdtemp(join(tmpdir(),'rsi-package-vector-'));
    const store=new core.VectorStore(join(nativeRoot,'memory.sqlite'),768,{info(){},warn(){},error(){},debug(){}});
    store.init({provider:'fixture',model:'package-smoke'});assert.equal(store.isDegraded(),false);assert.equal(store.getCapabilities().vectorSearch,true);store.close();await rm(nativeRoot,{recursive:true,force:true});
    const {getLlama}=await import('node-llama-cpp');const llama=await getLlama({build:'never',progressLogs:false});assert.ok(llama);await llama.dispose();
    for(const path of ['dsh-rsi','dsh-rsi/model-bridge'])await import(path);
    const source=await readFile(require.resolve('dsh-rsi/client'),'utf8');
    const externals=[...new Set([...source.matchAll(/require\("([^"\n]+)"\)/g)].map(match=>match[1]))].sort();
    assert.deepEqual(externals,['react','react/jsx-runtime']);
    console.log(JSON.stringify({platform:process.platform,arch:process.arch,nativeBinaries:binaries.map(path=>path.replaceAll('\\','/').split('node_modules/').at(-1)),ftsQuery:query,clientExternalSpecifiers:externals,serverExportsLoaded:true,sqliteVecLoaded:true,llamaNativeBinaryLoaded:true}));
  `;
  await writeFile(join(consumer,'smoke.mjs'),smoke);
  const checked=spawnSync(process.execPath,['smoke.mjs'],{cwd:consumer,encoding:'utf8',timeout:30000});
  if(checked.error||checked.status!==0)throw Error(`Installed package smoke failed: ${checked.error?.message??''}\n${checked.stdout}\n${checked.stderr}`);
  const result={status:'PASS',checkedAt:new Date().toISOString(),freshSourcePrepareBuild:true,tarballArtifactsPresent:true,productionInstallWithoutEsbuild:true,...JSON.parse(checked.stdout),privatePublishGuard:config.private===true,realModelRequests:0,limitation:'Current host only; Git URL installation and other OS/CPU combinations require separate checks.'};
  const output=process.argv.indexOf('--output');if(output>=0)await writeFile(process.argv[output+1],JSON.stringify(result,null,2)+'\n');
  console.log(JSON.stringify(result,null,2));
}finally{await rm(root,{recursive:true,force:true});}
