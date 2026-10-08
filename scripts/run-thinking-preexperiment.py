#!/usr/bin/env python3
"""Eight exposed independent baseline pairs; detached and serial, no RSI or formal study dispatch."""
import argparse, hashlib, importlib.util, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path
P=Path(__file__).resolve().parent.parent
ENV=P/'docs/evidence/thinking-environments-20261008.json'
DATA=Path('/Users/lsmax/Coder/EvoAgentBench/data/swebench/data/test-00000-of-00001.parquet')
SCORER=P/'.artifacts/swe-scorer-venv/bin/python'
IDS=['django__django-'+n for n in ['11848','11551','12262','11815','11880','11790','11999','11740']]
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');os.replace(t,p)
def require(v,m):
 if not v:raise RuntimeError(m)
def checked(argv):return subprocess.check_output([str(x) for x in argv],cwd=P,text=True).strip()
def code():
 spec=importlib.util.spec_from_file_location('existing_runner',P/'scripts/run-swe-expansion.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m.codehash()
def model_identity():
 opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
 with opener.open(os.environ['RSI_MODEL_UPSTREAM'].rstrip('/')+'/models',timeout=15) as response:rows=json.load(response)['data']
 row=next(r for r in rows if r['id']=='qwen3.8-27b');return {k:row.get(k) for k in ['id','root','owned_by','max_model_len']}
def validate(s):
 require(checked(['git','rev-parse','HEAD'])==s['revision'] and not checked(['git','status','--porcelain']),'Frozen revision or clean checkout changed')
 require(code()==s['codeHashes'] and sha(DATA)==s['datasetSha256'],'Frozen code or dataset changed')
 require(hashlib.sha256(os.environ.get('RSI_MODEL_UPSTREAM','').encode()).hexdigest()==s['upstreamSha256'],'Model service changed')
 require(model_identity()==s['modelIdentity'],'Reported model deployment changed')
 for e in s['environments']:
  f=P/e['environmentFile'];require(sha(f)==e['environmentSha256'] and sha(f.parent/'task.json')==e['publicInputSha256'],'Frozen public environment changed')
  for tag,key in [(e['taskTag'],'taskImageId'),(e['scorerKey'],'scorerImageId')]:require(checked(['docker','image','inspect','--format','{{.Id}}',tag])==e[key],'Frozen image changed')
def freeze(root):
 require(not root.exists(),'Preserve old experiment directory');require(not checked(['git','status','--porcelain']),'Commit implementation before freeze')
 env=read(ENV);require([e['instanceId'] for e in env['environments']]==IDS,'Only the eight exposed development tasks are permitted')
 checked([SCORER,'-B','-c',"import importlib.util; s=importlib.util.spec_from_file_location('scorer','scripts/probe-scorer.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); m.verify_distribution()"])
 s={'status':'FROZEN_THINKING_DEVELOPMENT','revision':checked(['git','rev-parse','HEAD']),'codeHashes':code(),'datasetSha256':sha(DATA),'upstreamSha256':hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest(),'environments':env['environments'],'model':'qwen3.8-27b','modelIdentity':model_identity(),'weightsHash':None,'budgets':{'foregroundCalls':40,'wallSeconds':1200,'maxOutputTokens':8192,'learningCalls':0},'pairs':8,'plannedRuns':16,'serial':True,'independentEmptyHistory':True,'rsiEnabled':False,'formal100Allowed':False,'selection':'All previously exposed eight continuous-development cases, original registered order, no outcome selection','createdAt':time.time()}
 validate(s);root.mkdir(parents=True);write(root/'protocol.json',s);(root/'protocol.sha256').write_text(sha(root/'protocol.json')+'\n');return s

def summarize(root,s):
 rows=[read(p) for p in sorted(root.glob('*.record.json'))];pairs=[]
 for e in s['environments']:
  arms={r['thinking']:r for r in rows if r['instanceId']==e['instanceId']}
  pair={'instanceId':e['instanceId'],'off':arms.get('off'),'on':arms.get('on')}
  if len(arms)==2:
   a,b=arms['off'],arms['on'];pair['sameInitialMessagesAndTools']=a.get('firstRequest')==b.get('firstRequest') and bool(a.get('firstRequest'))
   pair['resolvedDifference']=int(b['resolved'])-int(a['resolved']) if all(type(x.get('resolved')) is bool for x in [a,b]) else None
  pairs.append(pair)
 totals={}
 for mode in ['off','on']:
  group=[r for r in rows if r['thinking']==mode];graded=[r for r in group if type(r.get('resolved')) is bool]
  totals[mode]={'runs':len(group),'graded':len(graded),'solved':sum(r['resolved'] for r in graded),'passRate':sum(r['resolved'] for r in graded)/8,'knownInputTokens':sum(r.get('inputTokens',0) for r in group),'knownOutputTokens':sum(r.get('outputTokens',0) for r in group),'knownTotalTokens':sum(r.get('totalTokens',0) for r in group),'unknownUsageRequests':sum(r.get('unknownUsageRequests',0) for r in group),'thinkingTokens':sum(r['thinkingTokens'] for r in group) if group and all(r.get('thinkingTokens') is not None for r in group) else None,'foregroundCalls':sum(r.get('calls',0) for r in group),'agentWallSeconds':sum(r.get('agentWallSeconds',0) for r in group),'timeouts':sum(bool(r.get('timedOut')) for r in group),'modelErrors':sum(r.get('modelErrors',0) for r in group),'toolErrors':sum(r.get('toolErrors',0) for r in group),'outputTruncations':sum(r.get('outputTruncations',0) for r in group)}
 complete=len(rows)==16 and all(r['status']=='CLOSED_GRADED' for r in rows) and all(p.get('sameInitialMessagesAndTools') for p in pairs)
 result={'status':'COMPLETE' if complete else 'PARTIAL_DEVELOPMENT','pairs':pairs,'totals':totals,'netSolvedOnMinusOff':totals['on']['solved']-totals['off']['solved'],'confidenceInterval':None,'reason':'Eight exposed cases, one run per mode; configuration development only, no RSI-effect or stable-generalization claim','formal100Started':False}
 write(root/'summary.json',result);return result

def execute(argv,log):
 with log.open('x') as stream:return subprocess.run([str(x) for x in argv],cwd=P,stdout=stream,stderr=subprocess.STDOUT).returncode

def run_case(root,s,e,mode):
 id=e['instanceId'];out=root/(id+'-'+mode+'-0');record=root/(out.name+'.record.json')
 require(not out.exists() and not record.exists(),'Existing attempt cannot be retried')
 rec={'instanceId':id,'thinking':mode,'status':'RUNNING','attempt':0,'startedAt':time.time(),'output':str(out),'resolved':None};write(record,rec)
 try:
  validate(s)
  argv=[sys.executable,'-B',P/'scripts/probe-runner.py','--formal','--arm','baseline','--thinking',mode,'--verify-thinking-wire','--image',e['taskTag'],'--instance',id,'--output',out,'--dispatch-limit','40','--request-limit','40','--learning-call-budget','0','--learning-dispatch-limit','0','--wall-seconds','1200','--settle-seconds','0','--baseline-date',e['baselineDate'],'--expected-tree',e['expectedTree'],'--expected-version',e['expectedVersion']]
  rc=execute(argv,root/(out.name+'.runner.log'));rec['runnerReturnCode']=rc
  pilot=out/'state/pilot'/id;ledger=read(pilot/'model-requests.json') if (pilot/'model-requests.json').exists() else [];tools=read(pilot/'tool-results.json') if (pilot/'tool-results.json').exists() else []
  phases=read(pilot/'phases.json') if (pilot/'phases.json').exists() else []
  good=[r for r in ledger if all(type((r.get('usage') or {}).get(k)) is int and r['usage'][k]>=0 for k in ['inputTokens','outputTokens','totalTokens']) and r['usage']['totalTokens']>0]
  rec.update(calls=len(ledger),inputTokens=sum(r['usage'].get('inputTokens',0) for r in good),outputTokens=sum(r['usage'].get('outputTokens',0) for r in good),totalTokens=sum(r['usage'].get('totalTokens',0) for r in good),unknownUsageRequests=len(ledger)-len(good),modelErrors=sum(r.get('status')=='ERROR' for r in ledger),toolErrors=sum(r.get('isError') is True for r in tools),outputTruncations=sum((r.get('finish') or {}).get('kind')=='max-tokens' for r in ledger),agentWallSeconds=sum(r['wallMs']/1000 for r in phases),phaseStops=[r.get('stopReason') for r in phases])
  rec['timedOut']=any('wall time' in json.dumps(r.get('stopReason',{})).lower() for r in phases)
  wire=[json.loads(l) for l in (out/'gateway.log').read_text().splitlines() if l.strip()] if (out/'gateway.log').exists() else []
  sent=[r for r in wire if r.get('request') and r.get('model')];responses=[r for r in wire if 'responseRequest' in r]
  if sent:
   rec['firstRequest']={k:sent[0].get(k) for k in ['messagesSha256','toolsSha256','maxOutputTokens','temperature']}

  reported=[next((u for u in reversed(r.get('usage',[])) if isinstance(u,dict) and type(u.get('total_tokens')) is int),None) for r in responses]
  reasoning=[(u.get('completion_tokens_details') or {}).get('reasoning_tokens') if u else None for u in reported]
  rec['rawServiceUsage']=reported
  rec['thinkingTokens']=sum(reasoning) if len(reasoning)==len(responses) and reasoning and all(type(n) is int for n in reasoning) else None
  rec['serviceThinkingEvidence']=read(out/'thinking-wire.json') if (out/'thinking-wire.json').exists() else None
  if ledger and (pilot/'prediction.patch').exists():
   g=out/'grading.json';grc=execute([SCORER,'-B',P/'scripts/score-prediction.py','--dataset',DATA,'--instance',id,'--prediction',pilot/'prediction.patch','--work-dir',out/'grader-only','--output',g],out/'scorer.log');rec['scorerReturnCode']=grc
   if g.exists():grade=read(g);rec.update(resolved=grade.get('resolved'),grading=str(g),patchSha256=grade.get('patchSha256'))
  require(bool(rec.get('firstRequest')) and all(re.fullmatch('[0-9a-f]{64}',rec['firstRequest'].get(k) or '') for k in ['messagesSha256','toolsSha256']) and rec['firstRequest']['maxOutputTokens']==8192,'Missing actual prompt/tools/output cap evidence')
  require(rc==0 and ledger and rec['serviceThinkingEvidence'],'Runner or actual Thinking verification failed')
  require(len(sent)==len(ledger) and len(ledger)<=40 and not rec['unknownUsageRequests'],'Delivery/call cap/usage needs review')
  require(all(r['phase']!='learning' for r in ledger),'Unexpected automatic learning')
  initial=read(pilot/'initial.json');require(initial['assets'] is None and not any(n.startswith('rsi_') for n in initial['toolSchemas']),'Baseline contains RSI')
  receipt=read(pilot/'receipt.json');reconstruction=read(pilot/'reconstruction.json')
  require(receipt['arm']=='baseline' and receipt['formalBenchmark'] is True and receipt['fixture'] is False and receipt['instanceId']==id and receipt['backgroundDispatches']==0 and isinstance(reconstruction,list) and len(reconstruction)==len(ledger) and all(c.get('matches') is True for c in reconstruction),'Native request reconstruction failed')
  require(rec.get('scorerReturnCode')==0 and type(rec['resolved']) is bool,'Missing official score')
  require(not (out/'source-snapshot.json').exists(),'Unexpected inherited task history')
  if rec['modelErrors']:raise RuntimeError('Model/service error needs review, saved patch score retained')
  rec['status']='CLOSED_GRADED'
 except Exception as error:rec.update(status='HALTED',error=str(error))
 rec['finishedAt']=time.time();write(record,rec);return rec

def run(root,s,resume):
 lock=root/'batch.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd)
 try:
  (root/'launch.lock').unlink(missing_ok=True)
  saved=[read(p) for p in root.glob('*.record.json')];require(resume or not saved,'Explicit resume required');require(all(r['status']=='CLOSED_GRADED' for r in saved),'Incomplete attempt cannot be retried')
  keys=[(r['instanceId'],r['thinking']) for r in saved];require(len(keys)==len(set(keys)) and all(id in IDS and mode in ['on','off'] for id,mode in keys),'Unexpected saved attempt')
  for index,e in enumerate(s['environments']):
   for mode in (['on','off'] if index%2==0 else ['off','on']):
    if (e['instanceId'],mode) in keys:continue
    if (root/'STOP').exists():write(root/'state.json',{'status':'STOPPED'});summarize(root,s);return
    r=run_case(root,s,e,mode);summary=summarize(root,s);write(root/'state.json',{'status':'RUNNING' if r['status']=='CLOSED_GRADED' else 'HALTED','lastRun':r,'completedRuns':sum(p['status']=='CLOSED_GRADED' for p in [read(f) for f in root.glob('*.record.json')])})
    if r['status']!='CLOSED_GRADED':return
    pair=next(p for p in summary['pairs'] if p['instanceId']==e['instanceId'])
    if pair['on'] and pair['off']:require(pair['sameInitialMessagesAndTools'],'Paired first prompt/tools/output cap differ')
  result=summarize(root,s);require(result['status']=='COMPLETE','Incomplete result inventory');write(root/'state.json',{'status':'COMPLETE','completedRuns':16,'summary':str(root/'summary.json')})
 except Exception as error:write(root/'state.json',{'status':'HALTED','controllerError':str(error)});summarize(root,s)
 finally:lock.unlink(missing_ok=True)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['freeze','start','run','status','stop','report']);p.add_argument('--output',type=Path,default=P/'.artifacts/thinking-preexperiment-20261008');p.add_argument('--resume',action='store_true');a=p.parse_args();root=a.output.resolve();os.environ.setdefault('RSI_MODEL_UPSTREAM','http://10.195.214.152:8100/v1')
 if a.mode=='freeze':freeze(root);print('FROZEN_8_EXPOSED_PAIRS');return
 if a.mode=='status':
  state=read(root/'state.json') if (root/'state.json').exists() else {'status':'NOT_STARTED'};rows=[read(f) for f in root.glob('*.record.json')];state.update(completedRuns=sum(r['status']=='CLOSED_GRADED' for r in rows),plannedRuns=16,activeOrFailed=[{k:r.get(k) for k in ['instanceId','thinking','status','error']} for r in rows if r['status']!='CLOSED_GRADED']);print(json.dumps(state,ensure_ascii=False,indent=2));return
 if a.mode=='stop':(root/'STOP').touch();print('STOP requested');return
 s=read(root/'protocol.json');require((root/'protocol.sha256').read_text().strip()==sha(root/'protocol.json'),'Protocol changed')
 if a.mode=='report':summarize(root,s);print(root/'summary.json');return
 require(not (root/'state.json').exists() or read(root/'state.json')['status']!='HALTED','HALTED batch requires audit, not automatic continuation')
 validate(s)
 if a.mode=='start':
  require(not (root/'batch.lock').exists() and not (root/'STOP').exists(),'Batch locked/stopped');fd=os.open(root/'launch.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
  with (root/'background.log').open('ab') as log:child=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'run','--output',str(root)]+(['--resume'] if a.resume else []),cwd=P,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  write(root/'background.json',{'pid':child.pid});print(child.pid);return
 run(root,s,a.resume)
if __name__=='__main__':main()
