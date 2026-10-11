#!/usr/bin/env python3
"""Zero-model launch gate regression, using explicit synthetic image/receipt fixtures."""
import copy, importlib.util, json, tempfile
from pathlib import Path
P=Path(__file__).resolve().parent.parent
q=importlib.util.spec_from_file_location('launch',P/'scripts/start-swe-continuous-study.py');n=importlib.util.module_from_spec(q);q.loader.exec_module(n)
checks=[];real_subprocess_run=n.subprocess.run;real_popen=n.subprocess.Popen
with tempfile.TemporaryDirectory() as td:
 root=Path(td);env=root/'environments';env.mkdir();launch=root/'launch';launch.mkdir()
 spec=n.read(P/'docs/evidence/swe-continuous-formal-draft-20261011.json');spec['budgetConfirmed']=True
 health=P/'.artifacts/swe-expansion-scorer-health-v2-20261008/receipt.json';spec['scorerHealthAudit']={'file':str(health),'sha256':n.sha(health)}
 n.m.spec_check=lambda s:n.require(len(s['cases'])==100 and s['budgetConfirmed'],'Fixture spec invalid')
 completed={}
 for c in spec['cases']:
  d=env/c['instanceId'];d.mkdir();public={'instance_id':c['instanceId'],'repo':c['repo'],'base_commit':c['baseCommit'],'problem_statement':'synthetic public problem','version':c['version']};n.write(d/'task.json',public)
  r={'instanceId':c['instanceId'],'publicInputSha256':n.sha(d/'task.json'),'modelRequests':0,'verifiedSourceFiles':50,'swebenchVersion':'3.0.0','environment':{'publicTreeAudit':{'samePathsTypesAndBlobs':True,'onlyExecutableModesDiffer':True},'baseTree':'synthetic-tree','djangoVersion':'fixture'},'taskTag':'fixture-task','taskImage':'fixture-image','scorerKey':'fixture-scorer','scorerImage':'fixture-image','baselineDate':'@0 +0000'};n.write(d/'environment.json',r);completed[c['instanceId']]={'environmentSha256':n.sha(d/'environment.json'),'publicInputSha256':n.sha(d/'task.json')}
 prep={'fixture':False,'realModelRequests':0,'datasetSha256':spec['datasetSha256'],'cases':spec['cases']};n.write(env/'preparation.json',prep);n.write(env/'state.json',{'status':'READY','completed':completed})
 path=root/'spec.json';n.write(path,spec);f={'spec':str(path),'environments':str(env),'study':str(root/'study'),'dataset':'fixture','scorer':'fixture','embedding':'fixture','revision':'fixture','codeHashes':{'fixture':'code'},'inputs':{str(path):n.sha(path)},'datasetSha256':spec['datasetSha256']}
 n.m.checked=lambda argv:'fixture-image';result=n.complete_spec(f);assert len(result['cases'])==100 and all(not c.get('environmentPending') for c in result['cases'])
 checks.append('all100 receipts, public-only fields, dataset/order, official source/version and image IDs required')
 for corrupt in ['not-ready','missing-case','foreign-field','wrong-image','changed-receipt']:
  state=n.read(env/'state.json');first=env/spec['cases'][0]['instanceId'];p0=(first/'task.json').read_bytes();r0=(first/'environment.json').read_bytes()
  try:
   if corrupt=='not-ready':n.write(env/'state.json',state|{'status':'HALTED'})
   if corrupt=='missing-case':bad=copy.deepcopy(state);bad['completed'].pop(spec['cases'][0]['instanceId']);n.write(env/'state.json',bad)
   if corrupt=='foreign-field':x=n.read(first/'task.json');x['test_patch']='hidden synthetic';n.write(first/'task.json',x)
   if corrupt=='wrong-image':n.m.checked=lambda argv:'changed-image'
   if corrupt=='changed-receipt':(first/'environment.json').write_text('{}')
   try:n.complete_spec(f)
   except (ValueError,KeyError):pass
   else:raise AssertionError('Invalid gate admitted: '+corrupt)
  finally:n.write(env/'state.json',state);(first/'task.json').write_bytes(p0);(first/'environment.json').write_bytes(r0);n.m.checked=lambda argv:'fixture-image'
 checks.append('HALTED/missing/foreign/tampered environment or changed image stops before dispatch')
 actual_check=n.check_inputs;n.m.checked=lambda argv:'fixture' if 'rev-parse' in argv else '';n.m.base.codehash=lambda:{'fixture':'code'}
 # Pin checks exercise real hashing with synthetic files, not a bypassed assertion.
 data=root/'data';data.write_text('fixture');emb=root/'embedding';emb.write_text('fixture');f.update(dataset=str(data),datasetSha256=n.sha(data),embedding=str(emb));n.m.EMBEDDING_SHA=n.sha(emb)
 actual_check(f);path.write_text(path.read_text()+' ')
 try:actual_check(f)
 except ValueError:pass
 else:raise AssertionError('Pinned inputs allowed to change')
 n.write(path,spec);f['inputs'][str(path)]=n.sha(path)
 checks.append('pinned inputs and clean code are checked before readiness and freeze')
 n.write(launch/'launch.json',f);n.check_inputs=lambda f:None;n.m.checked=lambda argv:'fixture-image';commands=[]
 def execute(argv,**kw):
  argv=[str(x) for x in argv];commands.append(argv)
  if 'freeze' in argv:
   Path(f['study']).mkdir();n.write(Path(f['study'])/'protocol.json',{'fixture':True})
  if 'start' in argv:n.write(Path(f['study'])/'background.json',{'pid':0,'fixture':True})
 n.subprocess.run=execute;n.run(launch);assert n.read(launch/'state.json')['status']=='RUNNER_LAUNCHED' and len(commands)==2 and 'freeze' in commands[0] and 'start' in commands[1]
 checks.append('real coordinator entry launches existing runner only after complete_spec and successful freeze')
 for failure in ['preparation-halted','input-drift','requested-stop','freeze-error']:
  new=root/failure;new.mkdir();f['study']=str(root/(failure+'-study'));n.write(new/'launch.json',f);before=len(commands)
  n.check_inputs=lambda f:None
  if failure=='preparation-halted':n.write(env/'state.json',{'status':'HALTED','completed':completed,'error':'fixture preparation failure'})
  if failure=='input-drift':
   def drift(f):raise ValueError('fixture frozen input drift')
   n.check_inputs=drift
  if failure=='requested-stop':(new/'STOP').touch()
  if failure=='freeze-error':
   def fail(argv,**kw):
    commands.append([str(x) for x in argv]);raise RuntimeError('fixture freeze failed')
   n.subprocess.run=fail
  n.run(new);state=n.read(new/'state.json');assert state['status']==('STOPPED' if failure=='requested-stop' else 'HALTED')
  assert len(commands)-before==(1 if failure=='freeze-error' else 0)
  n.write(env/'state.json',{'status':'READY','completed':completed});n.subprocess.run=execute
 checks.append('blocking preparation/input/freeze failure and STOP never launch formal tasks or retry')
print(json.dumps({'status':'PASS_OFFLINE_CONTINUOUS_LAUNCH','realModelRequests':0,'syntheticScoresAreExperimentResults':False,'checks':checks}))

q=importlib.util.spec_from_file_location('cache',P/'scripts/maintain-swe-build-cache.py');cache=importlib.util.module_from_spec(q);q.loader.exec_module(cache)
valid={'Reclaimable':True,'Shared':False,'ID':'fixture123','Description':'COPY lib /opt/rsi/lib'}
assert cache.candidates([valid])==[valid]
for bad in [valid|{'Shared':True},valid|{'Reclaimable':False},valid|{'Description':'COPY /app'},valid|{'ID':'unsafe;id'}]:assert not cache.candidates([bad])
print(json.dumps({'status':'PASS_PROJECT_CACHE_SELECTION','realModelRequests':0,'imagesOrStateRemoved':False,'checks':['only reclaimable unshared project build records selected','shared active unrelated and malformed records excluded']}))

with tempfile.TemporaryDirectory() as td:
 root=Path(td);(root/'logs').mkdir();instance='django__django-123';n.write(root/'preparation.json',{'cases':[{'instanceId':instance}]});state={'status':'HALTED','pid':None,'current':instance,'completed':{}};f={'environments':str(root)}
 def failed(empty=True,message='requests.exceptions.SSLError: UNEXPECTED_EOF_WHILE_READING'):
  env=root/instance;env.mkdir()
  if not empty:(env/'task.json').write_text('synthetic partial input')
  (root/'logs'/(instance+'.log')).write_text(message)
 class Child:pid=0
 launched=[];n.subprocess.Popen=lambda argv,**kw:launched.append(argv) or Child()
 for i in range(3):failed();assert n.recover_empty_network_failure(f,state)
 failed();assert not n.recover_empty_network_failure(f,state) and len(launched)==3
 assert len(list((root/'network-recovery').glob(instance+'-*')))==3
 # Evidence with any partial source/build bytes cannot be silently retried.
 (root/instance/'task.json').write_text('synthetic partial source');assert not n.recover_empty_network_failure(f,state)
 (root/instance/'task.json').unlink();(root/'logs'/(instance+'.log')).write_text('Frozen/source identity validation failed');assert not n.recover_empty_network_failure(f,state)
print(json.dumps({'status':'PASS_PREMODEL_TRANSPORT_RECOVERY','realModelRequests':0,'checks':['up to3 empty network failures archived and resumed','retry limit preserved','partial bytes and source/freeze failures never retried']}))

with tempfile.TemporaryDirectory() as td:
 root=Path(td);(root/'logs').mkdir();instance='django__django-123';n.write(root/'preparation.json',{'cases':[{'instanceId':instance}]});state={'status':'HALTED','pid':None,'current':instance,'completed':{}};f={'environments':str(root)};env=root/instance;env.mkdir();log=root/'logs'/(instance+'.log');log.write_text('UNEXPECTED_EOF_WHILE_READING')
 (env/'task.json').write_text('partial');assert not n.recover_empty_network_failure(f,state)
 (env/'task.json').unlink();log.write_text('Frozen source identity failed');assert not n.recover_empty_network_failure(f,state)
 log.write_text('UNEXPECTED_EOF_WHILE_READING');assert not n.recover_empty_network_failure(f,state|{'completed':{instance:{}}})
 n.alive=lambda pid:True;assert not n.recover_empty_network_failure(f,state)
print(json.dumps({'status':'PASS_PREMODEL_RECOVERY_NEGATIVE_CONTROLS','checks':['partial source, source validation, completed environment and live worker stop recovery before first retry']}))

# Real APFS operation on isolated state fixtures; no task, asset or model writes.
cache.subprocess.run=real_subprocess_run;cache.subprocess.Popen=real_popen
with tempfile.TemporaryDirectory() as td:
 root=Path(td);study=root/'study';study.mkdir();audit=root/'audit';audit.mkdir()
 for arm in ['baseline','rsi']:
  for pos in [1,2]:
   state=study/f'{pos:03d}-{arm}'/'state';logs=state/'home/sessions';logs.mkdir(parents=True);(logs/'old.jsonl').write_text('independent-'+arm);digest=n.sha(logs/'old.jsonl');n.write(study/f'{pos:03d}-{arm}.checkpoint.json',{'arm':arm,'position':pos,'state':str(state),'sessions':{'old.jsonl':digest}});n.write(study/f'{pos:03d}-{arm}.record.json',{'arm':arm,'position':pos,'status':'CLOSED_GRADED'})
 cpfile=study/'002-baseline.checkpoint.json';original=n.read(cpfile);wrong=dict(original,state=str(study/'002-rsi/state'));n.write(cpfile,wrong)
 try:cache.compact_history(study,audit)
 except ValueError:pass
 else:raise AssertionError('Clone crossed group state')
 n.write(cpfile,original)
 cache.compact_history(study,audit)
 for arm in ['baseline','rsi']:
  before=study/f'001-{arm}'/'state/home/sessions/old.jsonl';after=study/f'002-{arm}'/'state/home/sessions/old.jsonl';assert before.read_bytes()==after.read_bytes() and before.stat().st_ino!=after.stat().st_ino;after.write_text('changed clone');assert before.read_text()=='independent-'+arm
 cache.compact_history(study,audit) # Each closed checkpoint is processed once.
print(json.dumps({'status':'PASS_REAL_APFS_HISTORY_CLONES','realModelRequests':0,'checks':['closed own-group history bytes and checkpoint hashes unchanged','independent inodes: later writes never mutate previous checkpoint','groups remain separate and repeat pass skips completed clone']}))
