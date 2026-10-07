// Offline identity/body audit; native parsers are also used by production consumers.
import assert from 'node:assert/strict';
import {readFileSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {parseSkillFile,stripSceneNavigation} from '../lib/core-entry.js';
const [run,output]=process.argv.slice(2);assert.ok(run&&output,'Usage: node scripts/audit-scope-assets.mjs RUN OUTPUT');
const read=p=>JSON.parse(readFileSync(p,'utf8'));
const digest=body=>createHash('sha256').update(body).digest('hex');
const reports=[];
for(const {caseId} of read(join(run,'run-summary.json'))){
 const root=join(run,caseId,'state/pilot',caseId),assets=read(join(root,'final-assets.json'));
 const consumers=read(join(root,'model-requests.json')).filter(r=>!r.background);
 const toolResults=consumers.length?read(join(root,'tool-results.json')):[];
 const skills=[],profiles=[];
 for(const a of Object.values(assets)){
  for(const s of a.skills){
   const h=s.head,body=parseSkillFile(h.content).body;
   const hits=consumers.flatMap((r,i)=>r.messages.filter(m=>m.role==='tool'&&!m.isError).flatMap(m=>{
    const text=m.content.map(b=>b.text??'').join('\n');
    const matchingCall=toolResults.some(t=>t.callId===m.toolCallId&&t.name==='skill'&&!t.isError&&t.args?.name===`rsi-${h.name}`);
    return matchingCall&&text.includes(`/skills/${h.skill_id}/v${h.version}/files`)&&text.includes(`<skill_content name="rsi-${h.name}">`)&&text.includes(body)?[{consumerRequest:i+1,callId:m.toolCallId}]:[];
   }));
   // Preference Skill creation is not mandatory, but a declared load must match its saved version.
   if(toolResults.some(t=>t.name==='skill'&&t.args?.name===`rsi-${h.name}`&&!t.isError))assert.ok(hits.length,`${caseId}: loaded Skill body/version mismatch`);
   skills.push({scope:a.scope,id:h.skill_id,name:h.name,version:h.version,bodyCharacters:body.length,bodySha256:digest(body),actualBodyDeliveries:hits});
  }
  for(const f of a.profileFiles.filter(f=>f.path==='persona.md')){
   const saved=f.encoding==='base64'?Buffer.from(f.content,'base64').toString():f.content;
   const body=stripSceneNavigation(saved).trim();
   const hits=consumers.flatMap((r,i)=>r.messages.some(m=>m.source?.kind==='dsh-rsi'&&m.source.form==='memory'&&m.content.some(b=>(b.text??'').includes(body)))?[i+1]:[]);
   if(consumers.length&&body)assert.equal(hits.length,consumers.length,`${caseId}: profile body not present in all consumer requests`);
   profiles.push({scope:a.scope,path:f.path,bodyCharacters:body.length,bodySha256:digest(body),actualBodyDeliveries:hits,presentation:'Native stripSceneNavigation(saved).trim(); navigation separately injected'});
  }
 }
 reports.push({caseId,consumerRequests:consumers.length,skills,profiles,qualityJudgment:null,newModelCalls:0});
}
writeFileSync(output,JSON.stringify(reports,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({cases:reports.length,consumerRequests:reports.reduce((n,r)=>n+r.consumerRequests,0),newModelCalls:0}));
