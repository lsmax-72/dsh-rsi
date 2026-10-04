#!/usr/bin/env python3
"""Read closed native run assets and delivered contexts; no model, learner or scorer."""
import argparse,json,sqlite3,tempfile,shutil,re,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--instance',default='persona-0');args=p.parse_args()
if args.output.exists():p.error('Preserve previous diagnostics')
root=args.run.resolve();state=json.loads((root/'state.json').read_text());assert state['container']['Running'] is False,'Read exported terminal runs only'
folder=root/'state/pilot'/args.instance;requests=json.loads((folder/'model-requests.json').read_text());checks=json.loads((folder/'reconstruction.json').read_text());assert all(x['matches'] for x in checks) and len(checks)==len(requests)
memories=[];skills=[];jobs=[];pipeline_states=[]
with tempfile.TemporaryDirectory() as temp:
 for index,f in enumerate((root/'state/assets').rglob('*.sqlite')):
  copy=Path(temp)/str(index);shutil.copyfile(f,copy);db=sqlite3.connect(copy);db.row_factory=sqlite3.Row
  if f.name=='memory.sqlite':memories.extend({'scope':f.parent.name,**dict(row)} for row in db.execute('SELECT record_id,version,type,content,scene_name,metadata_json FROM l1_records'))
  if f.name=='skills.sqlite':skills.extend({'scope':f.parent.name,**dict(row)} for row in db.execute('SELECT skill_id,name,version,content FROM skills WHERE is_head=1'))
  if f.name=='rsi-state.sqlite':
   jobs=[dict(row) for row in db.execute('SELECT id,status,error,stages FROM jobs')]
   pipeline_states=[{'key':row['key'],'state':json.loads(row['value'])} for row in db.execute("SELECT key,value FROM kv WHERE key LIKE 'pipeline:%'")]
  db.close()
metrics=[]
for file in (root/'state/assets').rglob('embedding.log'):
 for line in file.read_text().splitlines():
  if ' {' in line:metrics.append(json.loads(line[line.index(' {')+1:]))
sent_sessions={r['sessionId'] for r in requests};undispatched=[]
for file in (root/'state/assets/learning-runs').glob('*.json'):
 run=json.loads(file.read_text())
 if run['sessionId'] in sent_sessions:continue
 ends=[]
 for session in (root/'state/home/sessions').rglob('session.v4.jsonl'):
  if run['sessionId'] not in str(session):continue
  ends=[e['data']['reason'] for line in session.read_text().splitlines() if (e:=json.loads(line))['type']=='turn/end']
 undispatched.append({**run,'actualModelRequests':0,'nativeTurnEnds':ends})
text=lambda m:'\n'.join(b.get('text','') for b in m.get('content',[]) if b.get('type')=='text')
questions={};memory_index={(m['scope'],m['record_id'],m['version']):m for m in memories};skill_loads=[]
for ordinal,request in enumerate(requests,1):
 if request['phase']=='learning':continue
 row=questions.setdefault(request['phase'],{'questionId':request['phase'],'requests':[],'firstMemoryRefs':[],'firstContextChars':0,'observableDecisionEvidence':'Requires manual comparison of delivered assets, source history and observed answer; delivery alone is not influence or causality.'})
 first=not row['requests'];row['requests'].append(ordinal)
 for message in request['messages']:
  source=message.get('source',{});body=text(message)
  if first and source.get('kind')=='dsh-rsi':
   row['firstContextChars']+=len(body)
   for scope in source.get('refs',[]):
    for ref in scope.get('memories',[]):
     scope_id=scope.get('scope',scope.get('id'));asset=memory_index.get((scope_id,ref.get('id'),ref.get('version')))
     row['firstMemoryRefs'].append({'scope':scope_id,**ref,'closedHeadMatches':asset is not None,'assetBodyChars':len(asset['content']) if asset else None})
  name=re.search(r'<skill_content name="([^"]+)">',body);instructions=re.search(r'<skill_instructions>\s*([\s\S]*?)\s*</skill_instructions>',body)
  if name and instructions:skill_loads.append({'questionId':request['phase'],'requestOrdinal':ordinal,'name':name[1],'bodyChars':len(instructions[1]),'bodySha256':hashlib.sha256(instructions[1].encode()).hexdigest(),'toolCallId':message.get('toolCallId')})
result={'status':'DEVELOPMENT_DIAGNOSTICS_ONLY','realNewModelRequests':0,'nativeJobs':jobs,'nativePipelineStates':pipeline_states,'learningRunsWithoutActualDispatch':undispatched,'storedMemories':[{**m,'bodyChars':len(m['content'])} for m in memories],'storedSkills':[{**s,'storedMarkdownChars':len(s['content'])} for s in skills],'questions':list(questions.values()),'actualSkillBodyDeliveries':skill_loads,'skillCharsRepeatedAcrossRequests':sum(x['bodyChars'] for x in skill_loads),'embeddingCalls':len(metrics),'embeddingInputChars':sum(x['input_chars'] for x in metrics),'embeddingTimeMs':sum(x['duration_ms'] for x in metrics),'embeddingTokenUsage':None,'durableRequestReconstructions':len(checks),'firstEffectiveCodeEdit':None,'codeTestCounts':None,'codingMetricsNotApplicable':True,'qualityAndCausalityNotInferredFromDelivery':True,'scorerDataRead':False}
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['nativeJobs','storedMemories','storedSkills','questions','actualSkillBodyDeliveries']}))
