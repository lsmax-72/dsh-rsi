#!/usr/bin/env python3
"""Exercise actual offline reporter failure boundaries; synthetic ledgers, zero models."""
import argparse,copy,hashlib,importlib.util,json,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--official-source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();assert not args.output.exists()
project=Path(__file__).resolve().parent.parent;spec=importlib.util.spec_from_file_location('actual_reporter',project/'scripts/run-personamem-study.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
controls=[]
with tempfile.TemporaryDirectory(prefix='dsh-rsi-failed-report-') as tmp:
 root=Path(tmp);scorer=root/'scorer';scorer.mkdir();mod.write(scorer/'answers.json',{'q1':'(b)'})
 freeze={'cases':[{'personaId':'fixture','questionIds':['q1']}],'questionCountPerUser':1,'requiresCommonHistoricalTimeNote':True,'selectionSeed':42,'scorerInputSha256':{str((scorer/'answers.json').resolve()):mod.sha(scorer/'answers.json'),str(args.official_source.resolve()):mod.sha(args.official_source)}}
 def setup(mode):
  records=[]
  for arm in ['baseline','rsi']:
   out=root/('persona-fixture-'+arm);folder=out/'state/pilot/persona-fixture';folder.mkdir(parents=True,exist_ok=True)
   failed=arm=='rsi' and mode!='complete';req=[{'phase':'learning' if failed else 'q1','usage':{'totalTokens':0 if mode=='unknown-failure' and failed else 20}}]
   receipt={'status':'ERROR' if failed else 'COMPLETED','foregroundRequests':0 if failed else 1,'formalPersonaMemEvaluation':True,'fixture':False,'commonHistoricalTimeNote':True,'historicalContextSha256':'shared-time-fixture','error':'fixture learning abort' if failed else None,'classification':'UNCLASSIFIED_NOT_TASK_FAIL' if failed else None}
   answers=[] if failed else [{'questionId':'q1','response':'<final_answer>(b)','stopReason':{'kind':'completed'}}]
   if failed:receipt.pop('commonHistoricalTimeNote');receipt.pop('historicalContextSha256')
   if arm=='rsi' and mode=='completed-missing-note':
    receipt.update(status='COMPLETED',foregroundRequests=1);req[0]['phase']='q1';answers=[{'questionId':'q1','response':'<final_answer>(b)','stopReason':{'kind':'completed'}}]
   if arm=='rsi' and mode=='failed-answer-missing-note':
    receipt['foregroundRequests']=1;req[0]['phase']='q1';answers=[{'questionId':'q1','response':'<final_answer>(b)','stopReason':{'kind':'error'}}]
   if arm=='rsi' and mode=='wrong-preanswer-phase':req[0]['phase']='q1'
   wire=[{'request':1,'model':'fixture','enableThinking':False,'messageRoles':[]}]
   if arm=='rsi' and mode=='wire-mismatch':wire.append(copy.deepcopy(wire[0]))
   mod.write(folder/'receipt.json',receipt);mod.write(folder/'answers.json',answers);mod.write(folder/'model-requests.json',req);mod.write(folder/'import.json',{'historySha256':'same-history-fixture'});(out/'gateway.log').write_text(''.join(json.dumps(x)+'\n' for x in wire));records.append({'personaId':'fixture','arm':arm,'status':'CLOSED','returncode':1 if failed else 0})
  mod.write(root/'runs.json',records)
 for mode in ['complete','preanswer-failure','unknown-failure','completed-missing-note','failed-answer-missing-note','wrong-preanswer-phase','wire-mismatch']:
  setup(mode)
  if mode in ['complete','preanswer-failure','unknown-failure']:
   r=mod.summarize(root,freeze,scorer,args.official_source.resolve())
   if mode=='complete':assert r['status']=='COMPLETE_INDEPENDENT_SAVED_RESULTS' and r['baselineMacroAccuracy']==r['rsiMacroAccuracy']==1
   else:
    assert r['status']=='INCOMPLETE_WITHHOLD_FULL_PAIRED_ESTIMATE';assert r['baselineMacroAccuracy'] is r['rsiMacroAccuracy'] is r['pairedAccuracyDifference'] is r['userClusterBootstrap95'] is None;assert r['bootstrapDraws']==0;assert r['users'][0]['arms'][1]['historicalTimeContextStatus']=='NOT_REACHED_PREANSWER_FAILURE';assert r['users'][0]['arms'][1]['accuracy'] is None;assert r['unknownActualUsage']==(1 if mode=='unknown-failure' else 0);assert r['knownTokens']==(20 if mode=='unknown-failure' else 40)
   controls.append({'case':mode,'status':r['status'],'unknownUsage':r['unknownActualUsage']})
  else:
   try:mod.summarize(root,freeze,scorer,args.official_source.resolve())
   except AssertionError as error:controls.append({'case':mode,'rejected':True,'error':str(error)})
   else:raise AssertionError('Invalid report fixture accepted: '+mode)
 receipt={'status':'PASS_FAILED_PREANSWER_REPORT_CONTROLS','fixtureOnly':True,'realModelRequests':0,'officialScorerSourceUnchanged':True,'reporterScriptSha256':mod.sha(project/'scripts/run-personamem-study.py'),'controls':controls,'scope':'Offline reporting only; no learner recovery, rescoring feedback, new answer generation or quota change.'};args.output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt))
