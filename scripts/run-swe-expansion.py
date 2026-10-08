#!/usr/bin/env python3
"""Frozen SWE pairs, with closed own-prefix snapshots and no automatic retries."""
import argparse, hashlib, importlib.util, json, os, shutil, subprocess, sys, time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
P=Path(__file__).resolve().parent.parent

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');os.replace(t,p)
def check(v,m):
 if not v:raise ValueError(m)
def files(root):return {str(f.relative_to(root)):sha(f) for f in sorted(root.rglob('*')) if f.is_file()}
def codehash():
 return {str(f.relative_to(P)):sha(f) for d in ['src','adapters','vendor','lib','scripts'] for f in sorted((P/d).rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.suffix not in ['.pyc','.pyo']}|{n:sha(P/n) for n in ['package.json','package-lock.json','cordis.patch.yml']}
def checked(a):return subprocess.check_output(a,cwd=P,text=True).strip()
def execute(a,log):
 with log.open('x') as s:return subprocess.run([str(x) for x in a],cwd=P,stdout=s,stderr=subprocess.STDOUT).returncode

def budget_path(root,stage):return root/('prefix-budget.sqlite' if stage=='prefix' else 'heldout-budget.sqlite')
def init_budgets(root,s):
 spec=importlib.util.spec_from_file_location('budget',P/'scripts/learning-budget.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 for stage,cap in [('prefix',s['budgets']['prefixBackgroundCalls']),('heldOut',len(s['manifest']['heldOut'])*s['budgets']['heldOutBackgroundCalls'])]:
  pool=mod.LearningBudget(budget_path(root,stage),cap);pool.close()
 return mod.LearningBudget

def freeze(a):
 root=a.output;check(not root.exists() or not any(root.iterdir()),'Use an empty experiment output');s=read(a.spec);m=s['manifest'];ids=[c['instanceId'] for st in ['prefix','heldOut'] for c in m[st]]
 check(len(m['prefix'])==4 and m['heldOut'] and len(ids)==len(set(ids)) and all(x.startswith('django__django-') and x.split('-')[-1].isdigit() for x in ids),'Invalid Django manifest')
 check(s['workers']==2 and s['model']=='qwen3.8-27b','Unsupported protocol');check(sha(a.dataset)==s['datasetSha256'],'Dataset mismatch');check(os.environ.get('RSI_MODEL_UPSTREAM'),'Missing model service')
 b=s['budgets'];check(all(type(b[k]) is int and b[k]>0 for k in ['foregroundCalls','wallSeconds','prefixBackgroundCalls','heldOutBackgroundCalls','prefixSettleSeconds','finalPrefixSettleSeconds','heldOutSettleSeconds']),'Invalid budgets')
 check(sha(a.embedding_model)=='6fa0c02a9c302be6f977521d399b4de3a46310a4f2621ee0063747881b673f67','Embedding changed')
 check(not checked(['git','status','--porcelain']),'Commit implementation before freeze')
 check((P/'lib/index.js').is_file(),'Build before freeze')
 checked([str(a.scorer_python.absolute()),'-B','-c',"import importlib.util; from pathlib import Path; p=Path('scripts/probe-scorer.py'); s=importlib.util.spec_from_file_location('scorer',p); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.verify_distribution()"])

 envs={}
 for id in ids:
  case=next(c for st in ['prefix','heldOut'] for c in m[st] if c['instanceId']==id)
  folder=a.environments/id;e=read(folder/'environment.json');check(e['instanceId']==id and e['publicInputSha256']==sha(folder/'task.json'),'Environment mismatch');public=read(folder/'task.json');check(public['instance_id']==id and public['base_commit']==case['baseCommit'] and public['version']==case['version'] and public['repo']=='django/django','Public task differs from selected metadata');envs[id]={'file':str((folder/'environment.json').resolve()),'hashes':{n:sha(folder/n) for n in ['environment.json','task.json']},'environment':e}
 root.mkdir(parents=True,exist_ok=True);s.update(status='FROZEN_SWE_EXPANSION',revision=checked(['git','rev-parse','HEAD']),inputSha256=codehash(),specSha256=sha(a.spec),dataset=str(a.dataset.resolve()),scorerPython=str(a.scorer_python.absolute()),embeddingModel=str(a.embedding_model.resolve()),embeddingSha256=sha(a.embedding_model),upstreamSha256=hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest(),environments=envs,frozenAt=time.time(),gatewayImage='dsh-rsi-pilot2:gateway')
 s['gatewayImageId']=checked(['docker','image','inspect','--format','{{.Id}}',s['gatewayImage']]);validate(s);write(root/'protocol.json',s);(root/'protocol.sha256').write_text(sha(root/'protocol.json')+'\n');return s

def validate(s):
 check(codehash()==s['inputSha256'],'Frozen code inventory changed');check(checked(['git','rev-parse','HEAD'])==s['revision'] and not checked(['git','status','--porcelain']),'Frozen checkout changed')
 check(sha(Path(s['dataset']))==s['datasetSha256'] and sha(Path(s['embeddingModel']))==s['embeddingSha256'],'Frozen data/model changed');check(hashlib.sha256(os.environ.get('RSI_MODEL_UPSTREAM','').encode()).hexdigest()==s['upstreamSha256'],'Service changed')
 check(checked(['docker','image','inspect','--format','{{.Id}}',s['gatewayImage']])==s['gatewayImageId'],'Gateway changed')
 for item in s['environments'].values():
  folder=Path(item['file']).parent;e=item['environment'];check(all(sha(folder/n)==h for n,h in item['hashes'].items()),'Environment bytes changed')
  for tag,key in [(e['taskTag'],'taskImage'),(e['scorerKey'],'scorerImage')]:check(checked(['docker','image','inspect','--format','{{.Id}}',tag])==e[key],'Image changed')

def run_arm(root,s,stage,id,arm,seed):
 out=root/(stage+'-'+id+'-'+arm+'-0');check(not out.exists() and not (root/(out.name+'.record.json')).exists(),'Existing attempt must not be retried');b=s['budgets'];e=s['environments'][id]['environment'];learning=(b['prefixBackgroundCalls'] if stage=='prefix' else b['heldOutBackgroundCalls']) if arm=='rsi' else 0
 argv=[sys.executable,'-B',P/'scripts/probe-runner.py','--formal','--image',e['taskTag'],'--instance',id,'--arm',arm,'--output',out,'--dispatch-limit',b['foregroundCalls'],'--request-limit',b['foregroundCalls']+learning,'--learning-call-budget',100000,'--learning-dispatch-limit',learning,'--wall-seconds',b['wallSeconds'],'--settle-seconds',b['finalPrefixSettleSeconds'] if stage=='prefix' and id==s['manifest']['prefix'][-1]['instanceId'] else b['prefixSettleSeconds'] if stage=='prefix' else b['heldOutSettleSeconds'],'--baseline-date',e['baselineDate'],'--expected-tree',e['environment']['baseTree'],'--expected-version',e['environment']['djangoVersion']]
 if arm=='rsi':
  argv+=['--learning-pool',budget_path(root,stage),'--embedding-model',s['embeddingModel']]
  if seed:argv+=['--seed-assets',seed/'assets','--seed-sessions',seed/'home/sessions']
 elif seed:argv+=['--baseline-history',seed/'home/sessions']
 rec={'stage':stage,'instanceId':id,'arm':arm,'attempt':0,'runDir':str(out/'state/pilot'/id),'classification':'UNCLASSIFIED','status':'RUNNING','grading':None,'startedAt':time.time()};write(root/(out.name+'.record.json'),rec)
 try:
  validate(s)
  if stage=='heldOut' and seed:
   expected=read(seed/'hashes.json');check(expected['sessions']==files(seed/'home/sessions') and (arm!='rsi' or expected['assets']==files(seed/'assets')),'Frozen prefix snapshot changed before dispatch')
  rc=execute(argv,root/(out.name+'.runner.log'));rec['runnerReturnCode']=rc;pilot=Path(rec['runDir']);rows=read(pilot/'model-requests.json');wire=[json.loads(l) for l in (out/'gateway.log').read_text().splitlines() if l.strip()];sent=[r for r in wire if r.get('request') and r.get('model')]
  rec.update(knownTokens=sum((r.get('usage') or {}).get('totalTokens',0) or 0 for r in rows),unknownActualUsage=sum(not r.get('usage') or ((r['usage'].get('totalTokens') or 0)==0 and r.get('status')!='COMPLETED') for r in rows))
  check(rc==0 and rows and len(sent)==len(rows) and all(r['enableThinking'] is False and 'developer' not in r['messageRoles'] for r in sent),'Runner or delivery failure');check(all(r.get('status')=='RETURNED' for r in rows),'Model request incomplete/error');check(rec['unknownActualUsage']==0,'Unknown model usage requires review');check(not (out/'budget-settlement-error.json').exists(),'Settlement failure')
  receipt=read(pilot/'receipt.json');initial=read(pilot/'initial.json')
  check(receipt['formalBenchmark'] is True and receipt['fixture'] is False and receipt['instanceId']==id and receipt['arm']==arm,'Wrong task receipt')
  if arm=='baseline':check(initial['assets'] is None and not any(n.startswith('rsi_') for n in initial['toolSchemas']),'Baseline contains RSI')
  if arm=='rsi' and seed is None:check(not initial['assets']['memory'] and not initial['assets']['skills'],'First prefix has prior assets')
  if seed:
   snap=read(out/'source-snapshot.json');check(snap['inputSha256']['sessions']==files(seed/'home/sessions'),'Wrong own history');check(all(sha(out/'state/home/sessions'/n)==h for n,h in files(seed/'home/sessions').items()),'Restored history changed');rec['ownPriorRawHistoryExact']=True
   if arm=='rsi':check(snap['inputSha256']['assets']==files(seed/'assets'),'Wrong frozen assets')
  grade=out/'grading.json';check(execute([s['scorerPython'],'-B',P/'scripts/score-prediction.py','--dataset',s['dataset'],'--instance',id,'--prediction',pilot/'prediction.patch','--work-dir',out/'grader-only','--output',grade],out/'scorer.log')==0,'Scorer failed');g=read(grade);check(type(g['resolved']) is bool,'Missing official score');rec.update(grading=str(grade),classification='GRADED',status='CLOSED_GRADED',resolved=g['resolved'],officialLogs=str(out/'grader-only'))
 except Exception as err:rec.update(status='HALTED',error=str(err))
 rec['finishedAt']=time.time();write(root/(out.name+'.record.json'),rec);return rec

def records(root):return [read(f) for f in sorted(root.glob('*.record.json'))]
def record_inventory(rows,s):
 expected={(st,c['instanceId'],arm) for st in ['prefix','heldOut'] for c in s['manifest'][st] for arm in ['baseline','rsi']}
 keys=[(r['stage'],r['instanceId'],r['arm']) for r in rows]
 check(len(keys)==len(set(keys)) and set(keys)<=expected,'Saved attempt inventory differs from protocol')
 check(all(r.get('attempt',0)==0 for r in rows),'Retries are forbidden')
 return set(keys)==expected
def report(root,s):
 saved=records(root);write(root/'runs.json',saved)
 spec=importlib.util.spec_from_file_location('summary',P/'scripts/summarize-paired.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 original=mod.usage
 # A zero usage placeholder is unknown, including interrupted provider streams. Raw logs stay intact.
 def measured(rows,unavailable=0):
  normalized=[dict(r,usage=None) if (r.get('usage') or {}).get('totalTokens',0)==0 else r for r in rows]
  return original(normalized,unavailable)
 mod.usage=measured
 result=mod.summarize(s['manifest'],saved);dest=root/('summary-'+str(time.time_ns())+'.json');write(dest,result);return str(dest)

def run(root,s,resume):
 lock=root/'batch.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
 try:
  (root/'launch.lock').unlink(missing_ok=True)
  old=records(root);record_inventory(old,s);check(resume or not old,'Use resume');check(all(r['status']=='CLOSED_GRADED' for r in old),'Incomplete attempts require audit; no retry');write(root/'protocol-manifest.json',s['manifest'])
  init_budgets(root,s)
  halted=False
  def prefix(arm):
   seed=None
   for c in s['manifest']['prefix']:
    id=c['instanceId'];prior=next((r for r in old if r['stage']=='prefix' and r['arm']==arm and r['instanceId']==id),None)
    if prior:seed=Path(prior['runDir']).parents[1];continue
    if (root/'STOP').exists() or (root/'HALT').exists():return False
    r=run_arm(root,s,'prefix',id,arm,seed)
    if r['status']!='CLOSED_GRADED':(root/'HALT').touch();return False
    seed=Path(r['runDir']).parents[1]
   snap=root/('prefix-snapshot-'+arm)
   origin={'sessions':files(seed/'home/sessions'),'assets':files(seed/'assets') if arm=='rsi' else None}
   if not snap.exists():
    snap.mkdir();shutil.copytree(seed/'home/sessions',snap/'home/sessions')
    if arm=='rsi':shutil.copytree(seed/'assets',snap/'assets')
    write(snap/'hashes.json',{'sessions':files(snap/'home/sessions'),'assets':files(snap/'assets') if arm=='rsi' else None})
   saved=read(snap/'hashes.json');check(saved==origin,'Snapshot differs from final prefix source');check(saved['sessions']==files(snap/'home/sessions') and (arm!='rsi' or saved['assets']==files(snap/'assets')),'Snapshot changed');return True
  def safe_prefix(arm):
   try:return prefix(arm)
   except Exception as err:
    write(root/('prefix-'+arm+'-controller-error.json'),{'error':str(err),'at':time.time()});(root/'HALT').touch();return False
  with ThreadPoolExecutor(max_workers=2) as ex:ok=list(ex.map(safe_prefix,['baseline','rsi']))
  if all(ok):
   def pair(index,c):
    id=c['instanceId'];arms=['baseline','rsi'] if index%2==0 else ['rsi','baseline']
    for arm in arms:
     if any(r['stage']=='heldOut' and r['instanceId']==id and r['arm']==arm for r in old):continue
     if (root/'HALT').exists() or (root/'STOP').exists():return
     r=run_arm(root,s,'heldOut',id,arm,root/('prefix-snapshot-'+arm))
     if r['status']!='CLOSED_GRADED':(root/'HALT').touch();return
   with ThreadPoolExecutor(max_workers=2) as ex:
    pending={};todo=iter(enumerate(s['manifest']['heldOut']));done=False
    while pending or not done:
     while len(pending)<2 and not done and not (root/'HALT').exists() and not (root/'STOP').exists():
      try:i,c=next(todo)
      except StopIteration:done=True;break
      pending[ex.submit(pair,i,c)]=c['instanceId']
     if not pending:break
     complete,_=wait(pending,return_when=FIRST_COMPLETED)
     for f in complete:
      cid=pending.pop(f)
      try:f.result()
      except Exception as err:write(root/(cid+'-controller-error.json'),{'error':str(err),'at':time.time()});(root/'HALT').touch()
     write(root/'batch-state.json',{'status':'RUNNING','records':records(root)})
  expected=2*sum(len(s['manifest'][st]) for st in ['prefix','heldOut'])
  complete=record_inventory(records(root),s) and len(records(root))==expected and all(r['status']=='CLOSED_GRADED' for r in records(root))
  if not complete and not (root/'STOP').exists():(root/'HALT').touch()
  state={'status':'HALTED' if (root/'HALT').exists() else 'STOPPED' if (root/'STOP').exists() else 'COMPLETE','records':records(root)}
  try:state['summary']=report(root,s)
  except Exception as err:state.update(status='HALTED',reportError=str(err));(root/'HALT').touch()
  write(root/'batch-state.json',state)
 except Exception as err:
  (root/'HALT').touch();write(root/'batch-state.json',{'status':'HALTED','controllerError':str(err),'records':records(root),'at':time.time()});raise
 finally:lock.unlink(missing_ok=True)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['freeze','start','run','status','report','validate','plan']);p.add_argument('--output',type=Path,required=True)
 for n in ['spec','dataset','scorer-python','environments','embedding-model']:p.add_argument('--'+n,type=Path)
 p.add_argument('--resume',action='store_true');a=p.parse_args();a.output=a.output.resolve()
 if a.mode=='freeze':print(json.dumps({'status':freeze(a)['status']}));return
 if a.mode=='plan':
  s=read(a.spec) if a.spec else read(a.output/'protocol.json');n=len(s['manifest']['heldOut']);b=s['budgets'];print(json.dumps({'prefixTasks':4,'evaluationPairs':n,'taskRuns':2*(4+n),'maxForegroundCalls':2*(4+n)*b['foregroundCalls'],'maxBackgroundCalls':b['prefixBackgroundCalls']+n*b['heldOutBackgroundCalls'],'workers':s['workers'],'realModelRequests':0},indent=2));return
 s=read(a.output/'protocol.json')
 check((a.output/'protocol.sha256').is_file() and (a.output/'protocol.sha256').read_text().strip()==sha(a.output/'protocol.json'),'Frozen protocol bytes changed')
 if a.mode=='status':
  rows=records(a.output);state=read(a.output/'batch-state.json') if (a.output/'batch-state.json').exists() else {'status':'RUNNING' if (a.output/'batch.lock').exists() else 'NOT_STARTED'}
  print(json.dumps({'status':state['status'],'completedRuns':sum(r['status']=='CLOSED_GRADED' for r in rows),'plannedRuns':2*sum(len(s['manifest'][st]) for st in ['prefix','heldOut']),'activeOrFailed':[r for r in rows if r['status']!='CLOSED_GRADED'],'summary':state.get('summary'),'lockPid':(a.output/'batch.lock').read_text() if (a.output/'batch.lock').exists() else None},indent=2));return
 if a.mode=='report':print(report(a.output,s));return
 try:validate(s)
 except Exception as err:
  if a.mode in ['start','run']:
   write(a.output/'startup-error.json',{'error':str(err),'at':time.time()});(a.output/'HALT').touch();write(a.output/'batch-state.json',{'status':'HALTED','controllerError':str(err),'records':records(a.output)})
   if a.mode=='run':(a.output/'launch.lock').unlink(missing_ok=True)
  raise
 if a.mode=='validate':print('PASS_FROZEN_INPUTS');return
 if a.mode=='start':
  check(not (a.output/'batch.lock').exists() and not (a.output/'STOP').exists() and not (a.output/'HALT').exists(),'Study stopped/locked; audit before launch');old=records(a.output);record_inventory(old,s);check((a.resume or not old) and all(r['status']=='CLOSED_GRADED' for r in old),'No automatic retry');log=a.output/('background-'+str(time.time_ns())+'.log')
  launchfd=os.open(a.output/'launch.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(launchfd)
  with log.open('x') as stream:child=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'run','--output',str(a.output)]+(['--resume'] if a.resume else []),cwd=P,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
  write(a.output/'background.json',{'pid':child.pid,'log':str(log),'status':'LAUNCHED'});print(child.pid);return
 run(a.output,s,a.resume)
if __name__=='__main__':main()
