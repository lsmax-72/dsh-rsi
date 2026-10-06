#!/usr/bin/env python3
"""Replay actual native quota-fixture journals through the offline reporter; no real models."""
import argparse,copy,hashlib,importlib.util,json,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--native-control',type=Path,required=True);p.add_argument('--official-source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();assert not args.output.exists()
project=Path(__file__).resolve().parent.parent;spec=importlib.util.spec_from_file_location('reporter',project/'scripts/run-personamem-study.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
proof=json.loads(args.native_control.read_text())['nativeFreezeProof'];controls=[]
with tempfile.TemporaryDirectory(prefix='dsh-rsi-native-report-') as tmp:
 root=Path(tmp);(root/'public').mkdir();public=root/'public/persona-fixture.json';mod.write(public,{'history':[]});scorer=root/'scorer';scorer.mkdir();mod.write(scorer/'answers.json',{'q1':'(b)','q2':'(b)'})
 freeze={'status':'FROZEN_PERSONAMEM_REPLICATION','cohortKind':'preexposed-development-replication','independenceClaim':False,'learningFailurePolicy':mod.NATIVE_LEARNING_POLICY,'budgets':{'backgroundCallsPerUser':1},'cases':[{'personaId':'fixture','questionIds':['q1','q2'],'publicInputSha256':mod.sha(public)}],'questionCountPerUser':2,'requiresCommonHistoricalTimeNote':True,'selectionSeed':42,'scorerInputSha256':{str((scorer/'answers.json').resolve()):mod.sha(scorer/'answers.json'),str(args.official_source.resolve()):mod.sha(args.official_source)}}
 def setup():
  records=[]
  for arm in ['baseline','rsi']:
   out=root/('persona-fixture-'+arm);folder=out/'state/pilot/persona-fixture';folder.mkdir(parents=True,exist_ok=True)
   req=copy.deepcopy(proof['gateInput']['requests']) if arm=='rsi' else []
   req.extend({'phase':q,'usage':{'totalTokens':0 if arm=='rsi' and q=='q2' else 5 if arm=='rsi' else 10},'status':'RETURNED'} for q in ['q1','q2'])
   receipt={'status':'COMPLETED','formalPersonaMemEvaluation':True,'fixture':False,'foregroundRequests':2,'commonHistoricalTimeNote':True,'historicalContextSha256':'synthetic-shared-note','learningFailurePolicy':mod.NATIVE_LEARNING_POLICY}
   if arm=='rsi':
    native=folder/'native-learning-runs.json';mod.write(native,proof['gateInput']['nativeRuns'])
    learning={k:copy.deepcopy(proof['gateInput'][k]) for k in ['settled','snapshot','activeCount','expectedL0','callLimit']};learning.update(nativeEvidenceSha256=mod.sha(native),disposition=proof['disposition']);mod.write(folder/'learning.json',learning)
    receipt.update(learningDisposition=proof['disposition'],learningStateSha256=mod.sha(folder/'learning.json'))
   mod.write(folder/'receipt.json',receipt);mod.write(folder/'import.json',{'historySha256':'synthetic-empty-history'});mod.write(folder/'model-requests.json',req);mod.write(folder/'answers.json',[{'questionId':q,'response':'<final_answer>(b)</final_answer>','stopReason':{'kind':'completed'}} for q in ['q1','q2']]);(out/'gateway.log').write_text(''.join(json.dumps({'request':i+1,'model':'fixture','enableThinking':False,'messageRoles':[]})+'\n' for i in range(len(req))))
   records.append({'personaId':'fixture','arm':arm,'status':'CLOSED','returncode':0})
  mod.write(root/'runs.json',records)
 for case in ['native-closed-profile-opt-in','old-policy-does-not-accept-new-receipt','missing-native-journal','altered-dispatch-input','reservation-count-mismatch','non-bounded-native-end','invented-failed-job-disposition','changed-public-history','changed-frozen-budget']:
  setup();trial=copy.deepcopy(freeze);folder=root/'persona-fixture-rsi/state/pilot/persona-fixture'
  if case=='old-policy-does-not-accept-new-receipt':trial['learningFailurePolicy']=mod.PARTIAL_LEARNING_POLICY
  if case=='missing-native-journal':(folder/'native-learning-runs.json').unlink()
  if case=='altered-dispatch-input':
   requests=json.loads((folder/'model-requests.json').read_text());requests[0]['messages'][0]['content'][0]['text']+=' tampered';mod.write(folder/'model-requests.json',requests)
  if case in ['reservation-count-mismatch','invented-failed-job-disposition']:
   learning=json.loads((folder/'learning.json').read_text());receipt=json.loads((folder/'receipt.json').read_text())
   if case=='reservation-count-mismatch':learning['snapshot']['usage']['calls']=2
   else:learning['disposition']['failedJobs']=[{'id':'invented','status':'failed','code':'ABORTED'}];receipt['learningDisposition']=learning['disposition']
   mod.write(folder/'learning.json',learning);receipt['learningStateSha256']=mod.sha(folder/'learning.json');mod.write(folder/'receipt.json',receipt)
  if case=='non-bounded-native-end':
   native=json.loads((folder/'native-learning-runs.json').read_text());native[0]['events'][-1]['data']['reason']['error']['code']='UNKNOWN';mod.write(folder/'native-learning-runs.json',native)
   learning=json.loads((folder/'learning.json').read_text());learning['nativeEvidenceSha256']=mod.sha(folder/'native-learning-runs.json');mod.write(folder/'learning.json',learning);receipt=json.loads((folder/'receipt.json').read_text());receipt['learningStateSha256']=mod.sha(folder/'learning.json');mod.write(folder/'receipt.json',receipt)
  if case=='changed-public-history':mod.write(public,{'history':[{'role':'user','content':'changed'}]})
  if case=='changed-frozen-budget':trial['budgets']['backgroundCallsPerUser']=2
  if case=='native-closed-profile-opt-in':
   result=mod.summarize(root,trial,scorer,args.official_source.resolve());assert result['status']=='COMPLETE_PREEXPOSED_SAVED_RESULTS';assert result['closedBoundedFailedLearners']==1 and result['completedLearners']==0;assert result['knownTokens']==45 and result['unknownActualUsage']==1;assert result['users'][0]['arms'][1]['learningDisposition']['failedJobs']==[];assert len(result['users'][0]['arms'][1]['learningDisposition']['failedProfiles'])==2;controls.append({'case':case,'status':result['status'],'knownFixtureTokens':45,'unknownFixtureUsage':1,'failedLearningRetained':True})
  else:
   try:mod.summarize(root,trial,scorer,args.official_source.resolve())
   except AssertionError as e:controls.append({'case':case,'rejected':True,'error':str(e)[-500:]})
   else:raise AssertionError('Invalid native report fixture accepted: '+case)
  mod.write(public,{'history':[]})
 result={'status':'PASS_NATIVE_PROFILE_FAILURE_REPORT_CONTROLS','realModelRequests':0,'fixtureOnly':True,'controls':controls,'nativeControlSha256':mod.sha(args.native_control),'reporterSha256':mod.sha(project/'scripts/run-personamem-study.py'),'limits':'Actual installed-host profile journals plus synthetic answers/counters; validates reporting and cost boundaries only, not quality or an eight-user estimate.'};args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result))
