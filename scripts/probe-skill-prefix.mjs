import assert from 'node:assert/strict';
import {mkdtemp,rm,writeFile} from 'node:fs/promises';
import {join} from 'node:path';
import {openLocalCore} from '../lib/local-core.js';
import {SkillExtractor,parseSkillFile} from '../lib/core-entry.js';
import {fixtureEmbedding} from './fixture-embedding.mjs';

const output=process.argv[2];assert.ok(output,'Receipt path required');
const root=await mkdtemp('/private/tmp/dsh-rsi-skill-prefix-');
const ids={team_id:'prefix-fixture',user_id:'local-user',agent_id:'local-agent'};
const file=(name,body)=>`---\nname: ${name}\ndescription: needlefixture\n---\n\n${body}`;
const input={...ids,task_id:'prefix-fixture',messages:[{role:'user',content:'Review needlefixture knowledge; development fixture only.'}]};
let core,mode='full',query='needlefixture',calls=0,queryCalls=0,toolCalls=0,listCalls=0,searchCalls=0;
const controls=[];
const runner={async run(params){
  calls++;
  if(params.traceName==='skill.extract.query-gen'){queryCalls++;return query;}
  assert.equal(params.traceName,'skill.extract');
  const execute=async(name,args)=>{toolCalls++;return JSON.parse(await params.tools[name].execute(args));};
  if(mode==='none'){
    assert.doesNotMatch(params.prompt,/\[skill_id=/);controls.push({mode,noPrefix:true});return 'Nothing to save.';
  }
  const expected=mode==='full'?/full list, no truncation/:mode==='relevant'?/BM25 prefetched/:/most-recently-updated/;
  assert.match(params.prompt,expected);
  const matches=[...params.prompt.matchAll(/- (prefix-fixture-\d+) \[skill_id=([^,\]]+), version=(\d+)\]/g)];
  assert.ok(matches.length);const [,name,skill_id,versionText]=matches[0],version=Number(versionText);
  const viewed=await execute('skill_view',{skill_id});assert.equal(viewed.skill_id,skill_id);assert.equal(viewed.name,name);assert.equal(viewed.version,version);
  assert.equal(parseSkillFile(viewed.content).frontmatter.name,name);
  if(mode==='full'){
    const bad=await execute('skill_view',{skill_id:name});assert.equal(bad.error,'SKILL_NOT_FOUND');
    const changed=await execute('skill_update',{skill_id,expected_version:version,content:file(name,'Updated native fixture body.')});assert.ok(changed.ok);assert.equal(changed.version,version+1);
    const stale=await execute('skill_update',{skill_id,expected_version:version,content:file(name,'Stale fixture.')});assert.equal(stale.error,'SKILL_VERSION_STALE');
    const head=await execute('skill_view',{skill_id});assert.equal(head.name,name);assert.equal(head.version,version+1);assert.equal(parseSkillFile(head.content).frontmatter.name,name);
    const listed=await execute('skill_list',{});assert.equal(listed[0].name,name);assert.equal(listed[0].skill_id,skill_id);
  }
  controls.push({mode,delivered:matches.length,firstViewByIdSucceeded:true});return 'Nothing to save.';
}};
try{
  core=await openLocalCore(root,runner,{info(){},warn(){},error(){},debug(){}},fixtureEmbedding());
  const created=await core.skills.create({...ids,name:'prefix-fixture-0',content:file('prefix-fixture-0','Native fixture body.')});assert.notEqual(created.skill_id,created.name);
  const nativeList=core.skills.list.bind(core.skills),nativeSearch=core.skills.search.bind(core.skills);
  core.skills.list=async params=>{listCalls++;return nativeList(params);};
  core.skills.search=async params=>{searchCalls++;return nativeSearch(params);};
  const review=async(expectedList,expectedSearch,args=input)=>{
    const before=[listCalls,searchCalls];await core.createSkillExtractor().extract(args);
    assert.deepEqual([listCalls-before[0],searchCalls-before[1]],[expectedList,expectedSearch]);
  };
  // Production wiring proves that the adapter reaches the actual native request.
  await review(2,0);
  for(let n=1;n<=20;n++)await core.skills.create({...ids,name:`prefix-fixture-${n}`,content:file(`prefix-fixture-${n}`,'Native fixture body.')});
  mode='relevant';await review(1,1);
  mode='recent';query='';await review(1,0);
  mode='none';await review(1,0,{...input,team_id:'empty-prefix-scope'});
  // Explicit zero limit also preserves native no-prefix/no-query behavior.
  const before=queryCalls;await new SkillExtractor({core:core.skills,toolBackend:core.skills,runner,prefixSkillsLimit:0}).extract(input);assert.equal(queryCalls,before);
  const persisted=await core.skills.list({...ids,pagination:{limit:50}});assert.equal(persisted.total,21);
  for(const skill of persisted.items){assert.doesNotMatch(skill.name,/\[skill_id=/);assert.equal(parseSkillFile(skill.content).frontmatter.name,skill.name);}
  assert.equal(queryCalls,2);assert.equal(calls,7);
  const receipt={status:'PASS_NATIVE_SKILL_PREFIX_IDS',controls,realModelRequests:0,embeddingFixture:true,fixtureRunnerCalls:calls,queryFixtureCalls:queryCalls,toolCalls,nativeSqliteAndSkillTools:true,nativePrefetchCallCountsPreserved:true,originalNamesAndFrontmatterPreserved:true,optimisticVersionControlPreserved:true,qualityOrModelCallReductionClaim:false};
  await writeFile(output,JSON.stringify(receipt,null,2)+'\n',{flag:'wx'});console.log(JSON.stringify(receipt));
}finally{core?.close();await rm(root,{recursive:true,force:true});}
