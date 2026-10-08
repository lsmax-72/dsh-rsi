#!/usr/bin/env python3
"""Offline orchestration controls; task/model/score execution is replaced, not the budget pool."""
import hashlib,importlib.util,json,shutil,tempfile,threading,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('runner',Path(__file__).with_name('run-swe-expansion.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
S={'model':'qwen3.8-27b','workers':2,'manifest':{'prefix':[{'instanceId':str(i)} for i in range(4)],'heldOut':[{'instanceId':str(i)} for i in range(4,7)]},'budgets':{'prefixBackgroundCalls':100,'heldOutBackgroundCalls':10,'foregroundCalls':40,'wallSeconds':1200,'prefixSettleSeconds':180,'finalPrefixSettleSeconds':360,'heldOutSettleSeconds':180},'embeddingModel':'fixture.gguf','scorerPython':'fixture-python','dataset':'fixture.parquet'}
checks=[];original_arm=m.run_arm;original_report=m.report;original_validate=m.validate;m.validate=lambda s:None;m.report=lambda root,s:'offline'
with tempfile.TemporaryDirectory() as td:
 root=Path(td);events=[];active=0;peak=0;lock=threading.Lock()
 def fake(root,s,stage,id,arm,seed):
  global active,peak
  with lock:active+=1;peak=max(peak,active)
  time.sleep(.01)
  if stage=='heldOut':assert seed==root/('prefix-snapshot-'+arm)
  if stage=='prefix' and id!='0':assert seed==root/(stage+'-'+str(int(id)-1)+'-'+arm+'-0')/'state'
  out=root/(stage+'-'+id+'-'+arm+'-0');state=out/'state';sessions=state/'home/sessions';sessions.mkdir(parents=True);(sessions/'own').write_text(arm)
  if arm=='rsi':(state/'assets').mkdir();(state/'assets/asset').write_text('fixed')
  rec={'stage':stage,'instanceId':id,'arm':arm,'attempt':0,'status':'CLOSED_GRADED','classification':'GRADED','runDir':str(state/'pilot'/id),'grading':None};m.write(root/(out.name+'.record.json'),rec)
  with lock:events.append((stage,id,arm));active-=1
  return rec
 m.run_arm=fake;m.run(root,S,False);assert len(events)==14 and peak==2;assert m.read(root/'batch-state.json')['status']=='COMPLETE'
 before=len(events);m.run(root,S,True);assert len(events)==before
 (root/'prefix-snapshot-rsi/assets/asset').write_text('tampered');m.run(root,S,True);assert m.read(root/'batch-state.json')['status']=='HALTED';assert 'Snapshot' in m.read(root/'prefix-rsi-controller-error.json')['error']
 bad=m.records(root)[0];bad['status']='RUNNING';m.write(root/'prefix-0-baseline-0.record.json',bad)
 try:m.run(root,S,True)
 except ValueError:pass
 else:raise AssertionError('Ambiguous attempt resumed')
 checks+=['two actual worker threads stay within 2','each arm carries own prefix','heldout uses fixed snapshot','closed resume never reruns','tampered snapshot rejected against original source','RUNNING resume rejected']
with tempfile.TemporaryDirectory() as td:
 root=Path(td);(root/'STOP').touch();m.run(root,S,False);assert not m.records(root);assert m.read(root/'batch-state.json')['status']=='STOPPED';checks.append('STOP prevents dispatch')
with tempfile.TemporaryDirectory() as td:
 root=Path(td);barrier=threading.Barrier(2);started=[]
 def failure(root,s,stage,id,arm,seed):
  started.append((stage,id,arm));barrier.wait(timeout=2)
  if arm=='rsi':time.sleep(.05)
  rec={'stage':stage,'instanceId':id,'arm':arm,'status':'HALTED' if arm=='baseline' else 'CLOSED_GRADED','classification':'UNCLASSIFIED','runDir':str(root/'fixture/state/pilot'/id),'grading':None}
  m.write(root/(arm+'.record.json'),rec);return rec
 m.run_arm=failure;m.run(root,S,False);assert len(started)==2 and m.read(root/'batch-state.json')['status']=='HALTED';checks.append('failure stops next dispatch and waits for in-flight worker')
with tempfile.TemporaryDirectory() as td:
 root=Path(td);Budget=m.init_budgets(root,S);p=Budget(m.budget_path(root,'prefix'));h=Budget(m.budget_path(root,'heldOut'))
 assert p.reserve('p1',100)==100;p.settle('p1',80,'fixture-evidence');assert p.reserve('p2',100)==20;p.settle('p2',20,'fixture-evidence');assert p.reserve('p3',100)==0
 assert h.snapshot()['remaining']==30;assert h.reserve('h1',10)==10;assert h.reserve('h2',10)==10;assert h.reserve('h3',10)==10;assert h.reserve('h4',10)==0;p.close();h.close();checks.append('real durable pools cap prefix at 100 and heldout at N*10 independently')
# Exercise the real arm command construction, validation and official report indexing with local files.
with tempfile.TemporaryDirectory() as td:
 root=Path(td);s=dict(S,environments={'case':{'environment':{'taskTag':'fixture-image','baselineDate':'@0 +0000','environment':{'baseTree':'tree','djangoVersion':'3.0'}}}});sent=[]
 def execute(argv,log):
  argv=[str(x) for x in argv];sent.append(argv);get=lambda k:Path(argv[argv.index(k)+1])
  if argv[2].endswith('probe-runner.py'):
   out=get('--output');pilot=out/'state/pilot/case';pilot.mkdir(parents=True);arm=argv[argv.index('--arm')+1]
   rows=[{'sessionId':'task','status':'RETURNED','usage':{'inputTokens':12,'outputTokens':8,'totalTokens':20}}];m.write(pilot/'model-requests.json',rows);(out/'gateway.log').write_text(json.dumps({'request':1,'model':'qwen3.8-27b','enableThinking':False,'messageRoles':['user']})+'\n')
   m.write(pilot/'receipt.json',{'formalBenchmark':True,'fixture':False,'instanceId':'case','arm':arm});m.write(pilot/'initial.json',{'assets':None if arm=='baseline' else {'memory':[],'skills':[]},'toolSchemas':[]});(pilot/'prediction.patch').write_text('fixture patch')
   if '--baseline-history' in argv:
    src=get('--baseline-history');shutil.copytree(src,out/'state/home/sessions');m.write(out/'source-snapshot.json',{'inputSha256':{'sessions':m.files(src)}})
  else:m.write(get('--output'),{'instanceId':'case','resolved':False})
  return 0
 m.execute=execute;seed=root/'own';(seed/'home/sessions').mkdir(parents=True);(seed/'home/sessions/log').write_text('own history');m.write(seed/'hashes.json',{'sessions':m.files(seed/'home/sessions'),'assets':None})
 rec=original_arm(root,s,'heldOut','case','baseline',seed);assert rec['status']=='CLOSED_GRADED' and rec['ownPriorRawHistoryExact'],rec;assert '--baseline-history' in sent[0] and '--seed-assets' not in sent[0];assert Path(sent[1][sent[1].index('--work-dir')+1]).name=='grader-only'
 rec=original_arm(root,s,'prefix','case','rsi',None);assert rec['status']=='CLOSED_GRADED',rec;cmd=sent[2];assert cmd[cmd.index('--learning-pool')+1]==str(root/'prefix-budget.sqlite');assert cmd[cmd.index('--learning-dispatch-limit')+1]=='100';checks.append('real command wiring keeps own baseline history and isolated scorer and prefix cap')
# Reporting normalizes missing/zero provider usage without editing original request evidence.
with tempfile.TemporaryDirectory() as td:
 root=Path(td);pilot=root/'state/pilot/0';pilot.mkdir(parents=True);m.write(pilot/'model-requests.json',[{'sessionId':'task','status':'RETURNED','usage':{'inputTokens':12,'outputTokens':8,'totalTokens':20}},{'sessionId':'task','status':'INCOMPLETE','usage':{'inputTokens':0,'outputTokens':0,'totalTokens':0}}]);before=(pilot/'model-requests.json').read_bytes()
 m.write(root/'bad.record.json',{'stage':'prefix','instanceId':'0','arm':'baseline','attempt':0,'runDir':str(pilot),'classification':'UNCLASSIFIED','grading':None,'status':'HALTED'})
 result=m.read(Path(original_report(root,S)));u=result['arms']['baseline']['allAttemptsUsage'];assert u['knownTotalTokens']==20 and u['missingTotalTokens']==1 and u['totalTokens'] is None;assert before==(pilot/'model-requests.json').read_bytes();checks.append('zero interrupted usage remains unknown and raw ledgers unchanged')
# A final offline summary failure must leave a durable halted result.
with tempfile.TemporaryDirectory() as td:
 root=Path(td);(root/'STOP').touch();m.report=lambda root,s:(_ for _ in ()).throw(ValueError('summary evidence mismatch'));m.run(root,S,False)
 state=m.read(root/'batch-state.json');assert state['status']=='HALTED' and state['reportError']=='summary evidence mismatch' and (root/'HALT').exists();checks.append('final report failure persists HALTED and its cause');m.report=lambda root,s:'offline'
# Fail before dispatch durably, and preserve the attempt instead of silently replaying it.
with tempfile.TemporaryDirectory() as td:
 root=Path(td);m.validate=lambda s:(_ for _ in ()).throw(ValueError('frozen input changed'));before=len(sent)
 rec=original_arm(root,s,'prefix','case','rsi',None);assert rec['status']=='HALTED' and rec['error']=='frozen input changed' and len(sent)==before
 try:original_arm(root,s,'prefix','case','rsi',None)
 except ValueError:pass
 else:raise AssertionError('Failed predispatch attempt was replayed')
 checks.append('predispatch input failure is durable and cannot be replayed')
 m.validate=lambda s:None
with tempfile.TemporaryDirectory() as td:
 root=Path(td);bad=[{'stage':'prefix','instanceId':'0','arm':'baseline','attempt':0}]*2
 try:m.record_inventory(bad,S)
 except ValueError:pass
 else:raise AssertionError('Duplicate attempts accepted')
 try:m.record_inventory([{'stage':'heldOut','instanceId':'outside','arm':'rsi','attempt':0}],S)
 except ValueError:pass
 else:raise AssertionError('Outside task accepted')
 checks.append('duplicate or outside attempts cannot count as completion')
with tempfile.TemporaryDirectory() as td:
 project=Path(td);old_p=m.P;m.P=project
 for d in ['src','adapters','vendor','lib','scripts']:(project/d).mkdir()
 for n in ['package.json','package-lock.json','cordis.patch.yml']:(project/n).write_text('fixture')
 (project/'src/original.js').write_text('one');frozen={'inputSha256':m.codehash()};(project/'src/new.js').write_text('added')
 try:original_validate(frozen)
 except ValueError as e:assert str(e)=='Frozen code inventory changed'
 else:raise AssertionError('Added code not detected')
 (project/'src/new.js').unlink();(project/'src/original.js').unlink()
 try:original_validate(frozen)
 except ValueError as e:assert str(e)=='Frozen code inventory changed'
 else:raise AssertionError('Deleted code not detected')
 m.P=old_p;checks.append('frozen code inventory detects added and deleted source')
print(json.dumps({'status':'PASS_OFFLINE_SWE_COORDINATOR','realModelRequests':0,'dockerOperations':0,'taskAndScorerExecution':'fixture only','checks':checks},ensure_ascii=False))
