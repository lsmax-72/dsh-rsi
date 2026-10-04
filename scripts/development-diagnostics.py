#!/usr/bin/env python3
"""Read saved development evidence and closed native databases; no model, scoring or asset edits."""
from pathlib import Path
import json,sqlite3,shutil,tempfile,re,shlex,hashlib,collections,argparse
parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();base=args.root.resolve()
def text(message):return '\n'.join(block.get('text','') for block in message.get('content',[]) if block.get('type')=='text')
rows=[]
for instance in ['django__django-11095','django__django-11119']:
 root=base/('task-'+instance.rsplit('-',1)[1]);pilot=root/'state/pilot'/instance;requests=json.loads((pilot/'model-requests.json').read_text());front=[r for r in requests if r['phase']=='task'];back=[r for r in requests if r['phase']=='learning'];results=json.loads((pilot/'tool-results.json').read_text());score=json.loads((root/'official-score.json').read_text());snapshot=json.loads((pilot/'receipt.json').read_text());memories=[];skills=[];jobs=[];slot=[]
 with tempfile.TemporaryDirectory() as tmp:
  for f in (root/'state/assets').rglob('*.sqlite'):
   p=Path(tmp)/f.name;shutil.copyfile(f,p);con=sqlite3.connect(p);con.row_factory=sqlite3.Row
   if f.name=='rsi-state.sqlite':
    jobs=[dict(row) for row in con.execute('SELECT id,status,error,stages FROM jobs')];slot=[dict(row) for row in con.execute('SELECT id,task,status,total_tokens FROM usage')]
   if f.name=='memory.sqlite':memories.extend({'scope':f.parent.name,**dict(row)} for row in con.execute('SELECT record_id,content FROM l1_records'))
   if f.name=='skills.sqlite':skills.extend({'scope':f.parent.name,**dict(row)} for row in con.execute('SELECT skill_id,name,version,content FROM skills WHERE is_head=1'))
   con.close()
 refs=[];loads={};repeat_chars=0
 for n,request in enumerate(front,1):
  for m in request['messages']:
   if n==1 and m['source'].get('kind')=='dsh-rsi':refs.extend([ref for scope in m['source'].get('refs',[]) for ref in scope.get('memories',[])])
   content=text(m);name=re.search(r'<skill_content name="([^"]+)">',content);body=re.search(r'<skill_instructions>\s*([\s\S]*?)\s*</skill_instructions>',content)
   if name and body:
    repeat_chars+=len(body[1]);loads.setdefault(m.get('toolCallId',m['id']),{'name':name[1],'firstRequest':n,'bodyChars':len(body[1])})
 source_results={}
 for source in (root/'state/home/sessions').rglob('session.v4.jsonl'):
  for line in source.read_text().splitlines():
   event=json.loads(line)
   if event['type']=='tool/result':
    message=event['data']['message'];source_results[message['toolCallId']]={'messageId':message['id'],'eventSeq':event['seq'],'text':text(message)}
 commands=[]
 for r in results:
  if r['name']!='bash' or not r['args'].get('command'):continue
  command=r['args']['command']
  try:normalized=' '.join(shlex.split(command))
  except ValueError:normalized=command
  observed=source_results.get(r['callId']);rendered=observed['text'] if observed else '';marker=re.search(r'\[exit code: (\d+)\]',rendered);description=r['args'].get('description','')
  framework=bool(re.search(r'runtests\.py|pytest|unittest|manage\.py test',command));behavior=bool(re.search(r'python\s+-c',command) and re.search(r'reproduce|verify|check.*behavio',description,re.I))
  commands.append({'command':command,'normalized':normalized,'patchSha256':r['patchSha256'],'requestOrdinal':r['requestOrdinal'],'toolIsError':r['isError'],'observedNonzeroExitCode':int(marker[1]) if marker else None,'exitCodeLimitation':'Zero exit code is not present in the rendered output; absence of an error marker alone is not proof of the expected behavior.','purposeDescription':description,'frameworkTest':framework,'inlineBehaviorProbe':behavior,'testRelated':framework or behavior,'actualResult':observed})
 grouping=collections.Counter((r['normalized'],r['patchSha256']) for r in commands)
 repeated=sum(count-1 for count in grouping.values() if count>1)
 metrics=[]
 for p in (root/'state/assets').rglob('embedding.log'):
  for line in p.read_text().splitlines():
   if ' {' in line:metrics.append(json.loads(line[line.index(' {')+1:]))
 wire=[json.loads(l) for l in (root/'gateway.log').read_text().splitlines() if l.strip()];sent=[r for r in wire if r.get('request') and r.get('model')];assert len(sent)==len(requests)
 first_edit=None
 if (root/'first-edit-score.json').exists():
  first=json.loads((root/'first-edit-score.json').read_text());patches=json.loads((pilot/'patch-snapshots.json').read_text());position=next(p for p in patches if p['sha256']==first['patchSha256'])
  if first['resolved']:first_edit={'requestOrdinal':position['requestOrdinal'],'patchSha256':first['patchSha256'],'supportedBy':'Official scoring of the first nonempty saved patch','cumulativeKnownTokens':sum(r['usage']['totalTokens'] for r in front[:position['requestOrdinal']])}
 seen=collections.Counter();sent_ids=set()
 for request in requests:
  seen[request['sessionId']]+=1;sent_ids.add(f"{request['sessionId']}:{seen[request['sessionId']]}")
 slots_without_sent=[r for r in slot if r['id'] not in sent_ids]
 rows.append({'instanceId':instance,'officialResolved':score['resolved'],'foregroundStop':snapshot['phases'][0]['stopReason'],'foregroundCalls':len(front),'learningCalls':len(back),'foregroundTokens':sum(r['usage']['totalTokens'] for r in front if r['usage']),'learningTokens':sum(r['usage']['totalTokens'] for r in back if r['usage']),'allKnownTokens':snapshot['knownTokens'],'unknownActualRequestUsage':sum(r['usage'] is None for r in requests),'gatewayRequestCountMatches':True,'persistentJobs':jobs,'persistentMemoryBodies':memories,'persistentSkillBodies':[{**s,'storedMarkdownChars':len(s['content'])} for s in skills],'firstQuery':next(text(m) for m in front[0]['messages'] if m['source']['kind']=='user'),'fixedProtocolStillVisible':any(m['source']['kind']=='benchmark-protocol' for m in front[0]['messages']),'firstMemoryRefs':refs,'actualSkillLoads':list(loads.values()),'repeatedSkillCharsAcrossRequests':repeat_chars,'embeddingCalls':len(metrics),'embeddingInputChars':sum(m['input_chars'] for m in metrics),'embeddingTimeMs':sum(m['duration_ms'] for m in metrics),'embeddingUnknownTokenCalls':len(metrics),'firstEffectiveEdit':first_edit,'unchangedPatchIdenticalCommandRepeats':repeated,'commands':commands,'frameworkTestCommands':sum(c['frameworkTest'] for c in commands),'inlineBehaviorProbes':sum(c['inlineBehaviorProbe'] for c in commands),'learningSlotsWithoutMatchingCurrentRunRequest':slots_without_sent,'notes':['Persistent assets/jobs read after shutdown; pre-shutdown receipt/export may be stale.','Imported prior usage slots are distinguished from current sent requests.','Body delivery does not establish causality.','Character and embedding time totals are not token estimates.']})
result={'status':'DEVELOPMENT_ONLY','tasks':rows,'knownTokensAllTasks':sum(r['allKnownTokens'] for r in rows),'officialSuccesses':sum(r['officialResolved'] for r in rows),'formalEffectClaim':False,'scorerResultsNotReturnedToLearning':True}
args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='tasks'}))
