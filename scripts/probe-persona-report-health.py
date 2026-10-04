#!/usr/bin/env python3
"""Offline synthetic controls: saved answers must not hide a failed run."""
import argparse,importlib.util,json,tempfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--official-source',type=Path,required=True);args=p.parse_args()
project=Path(__file__).resolve().parent.parent
if not (project/'scripts/run-personamem-study.py').exists():project=Path('/Users/lsmax/Coder/dsh-rsi')
spec=importlib.util.spec_from_file_location('study',project/'scripts/run-personamem-study.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
cases=[];records=[];keys={}
with tempfile.TemporaryDirectory(prefix='rsi-report-health-') as d:
 root=Path(d);scorer=root/'private-scorer';scorer.mkdir()
 for uid in ['fixture-a','fixture-b']:
  ids=[uid+'-q'+str(n) for n in range(4)];keys.update({qid:'(a)' for qid in ids});cases.append({'personaId':uid,'questionIds':ids})
  for arm in ['baseline','rsi']:
   out=root/('persona-'+uid+'-'+arm);pilot=out/'state/pilot'/('persona-'+uid);pilot.mkdir(parents=True)
   records.append({'personaId':uid,'arm':arm,'runDir':str(out),'status':'CLOSED','returncode':0})
   (pilot/'receipt.json').write_text(json.dumps({'status':'COMPLETED','fixture':False,'formalPersonaMemEvaluation':True}))
   (pilot/'answers.json').write_text(json.dumps([{'questionId':qid,'response':'<final_answer>(a)</final_answer>','stopReason':{'kind':'completed'}} for qid in ids]))
   (pilot/'model-requests.json').write_text(json.dumps([{'phase':qid,'usage':{'totalTokens':7}} for qid in ids]))
   (pilot/'reconstruction.json').write_text(json.dumps([{'matches':True} for qid in ids]))
   (out/'gateway.log').write_text('\n'.join(json.dumps({'request':n+1,'model':'qwen3.8-27b','enableThinking':False,'messageRoles':['system','user']}) for n in range(4)))
 (scorer/'answers.json').write_text(json.dumps(keys))
 freeze={'scorerInputSha256':{str(args.official_source):m.sha(args.official_source),str(scorer/'answers.json'):m.sha(scorer/'answers.json')},'cases':cases,'questionCountPerUser':4,'selectionSeed':20261004,'model':'qwen3.8-27b'}
 def report():
  (root/'runs.json').write_text(json.dumps(records));return m.summarize(root,freeze,scorer,args.official_source)
 healthy=report();assert healthy['status']=='COMPLETE_INDEPENDENT_SAVED_RESULTS' and healthy['pairedAccuracyDifference']==0
 failed=records[-1];failed['returncode']=1
 bad_return=report();assert bad_return['status']=='INCOMPLETE_WITHHOLD_FULL_PAIRED_ESTIMATE' and 'userClusterBootstrap95' not in bad_return
 failed['returncode']=0;receipt=Path(failed['runDir'])/'state/pilot'/('persona-'+failed['personaId'])/'receipt.json';v=json.loads(receipt.read_text());v['status']='ERROR';receipt.write_text(json.dumps(v))
 bad_receipt=report();assert bad_receipt['status']=='INCOMPLETE_WITHHOLD_FULL_PAIRED_ESTIMATE' and 'pairedAccuracyDifference' not in bad_receipt
 assert healthy['knownTokens']==bad_return['knownTokens']==bad_receipt['knownTokens']==112
 print(json.dumps({'status':'PASS_SYNTHETIC_REPORT_HEALTH_CONTROLS','realModelRequests':0,'syntheticDataOnly':True,'checks':['healthy-complete-cohort-publishes-grouped-estimate','all-answers-plus-nonzero-return-withholds-estimate','all-answers-plus-error-receipt-withholds-estimate','failed-attempt-costs-retained']},indent=2))
