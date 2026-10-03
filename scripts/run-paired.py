#!/usr/bin/env python3
"""Run the approved fixed paired protocol, reusing the isolated runner and official grader."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime,timezone


def write(path,value):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(temp,path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True);parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--scorer-python',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--environments',type=Path,required=True)
    parser.add_argument('--resume',action='store_true',help='Continue completed graded arms after preparation interruption; never retry ambiguous attempts')
    args=parser.parse_args();project=Path(__file__).resolve().parent.parent;root=args.output.resolve()
    root.mkdir(parents=True,exist_ok=True)
    if any(root.iterdir()) and not args.resume:parser.error('New formal experiments need an empty output directory; preserve interrupted attempts')
    if not os.environ.get('RSI_MODEL_UPSTREAM'):parser.error('Use the already authorized qwen service environment')
    manifest=json.loads(args.manifest.read_text());assert len(manifest['prefix'])==4 and len(manifest['heldOut'])==20
    assert subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True)==''
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip()
    hashes={str(p.relative_to(project)):hashlib.sha256(p.read_bytes()).hexdigest() for directory in ['src','adapters','vendor','lib','scripts'] for p in sorted((project/directory).rglob('*')) if p.is_file()}
    for name in ['package.json','package-lock.json','cordis.patch.yml']:
        hashes[name]=hashlib.sha256((project/name).read_bytes()).hexdigest()
    assert hashlib.sha256(args.dataset.read_bytes()).hexdigest()==manifest['datasetSha256']
    freeze={'status':'APPROVED_RUNNING','approvedBy':'user confirmation in current conversation, 2026-10-03',
        'revision':revision,'inputSha256':hashes,'manifest':manifest,'manifestSha256':hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
        'upstreamSha256':hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest(),'model':'qwen3.8-27b','foregroundLimit':40,'prefixLearningLimit':100,'heldOutLearningLimit':10,
        'startedAt':datetime.now(timezone.utc).isoformat(),'formalBenchmarkStarted':False}
    records=[]
    if args.resume:
        saved=json.loads((root/'freeze.json').read_text())
        assert saved['manifestSha256']==freeze['manifestSha256'] and saved['inputSha256']==hashes and saved['upstreamSha256']==freeze['upstreamSha256'],'Frozen inputs changed'
        freeze=saved;records=json.loads((root/'runs.json').read_text()) if (root/'runs.json').exists() else []
        assert all(r['classification']=='GRADED' and r['runnerReturnCode']==0 for r in records),'An ambiguous attempt needs review before resuming'
    write(root/'freeze.json',freeze)
    loader=importlib.util.spec_from_file_location('budget',project/'scripts/learning-budget.py');budget=importlib.util.module_from_spec(loader);loader.loader.exec_module(budget)
    pool=budget.LearningBudget(root/'prefix-budget.sqlite',100);pool.close()
    seed=None
    def command(argv,log):
        with log.open('w') as stream:return subprocess.run([str(v) for v in argv],cwd=project,stdout=stream,stderr=subprocess.STDOUT).returncode
    for stage in ['prefix','heldOut']:
        for index,case in enumerate(manifest[stage]):
            instance=case['instanceId']
            completed=[r for r in records if r['stage']==stage and r['instanceId']==instance]
            if len(completed)==2:
                if stage=='prefix':seed=Path(next(r['runDir'] for r in completed if r['arm']=='rsi')).parent.parent
                continue
            envdir=args.environments.resolve()/instance;envfile=envdir/'environment.json'
            if not envfile.exists():
                print(json.dumps({'stage':stage,'instanceId':instance,'phase':'prepare-environment'}),flush=True)
                code=command([args.scorer_python,'-B',project/'scripts/prepare-task-image.py','--dataset',args.dataset,'--instance',instance,'--output',envdir],root/('prepare-'+instance+'.log'))
                if code:raise RuntimeError('Environment preparation failed; no task started for '+instance)
            env=json.loads(envfile.read_text());assert env['instanceId']==instance
            arms=['rsi','baseline'] if stage=='heldOut' and (index+1)%2==0 else ['baseline','rsi']
            if stage=='heldOut':
                assert seed is not None
                pool_path=root/(instance+'-budget.sqlite');pool=budget.LearningBudget(pool_path,10);pool.close()
            else:pool_path=root/'prefix-budget.sqlite'
            for arm in arms:
                if any(r['arm']==arm for r in completed):
                    if stage=='prefix' and arm=='rsi':seed=Path(next(r['runDir'] for r in completed if r['arm']=='rsi')).parent.parent
                    continue
                # Prevent edits midway through the fixed study, including ignored compiled files.
                assert all((project/path).is_file() and hashlib.sha256((project/path).read_bytes()).hexdigest()==sha for path,sha in hashes.items()),'Frozen implementation changed'
                assert subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',env['taskTag']],text=True).strip()==env['taskImage']
                out=root/(stage+'-'+instance+'-'+arm+'-0');log=root/(out.name+'.runner.log')
                limit=100 if stage=='prefix' else 10
                settle=360 if stage=='prefix' and index==3 else 180
                argv=[sys.executable,'-B',project/'scripts/probe-runner.py','--formal','--image',env['taskTag'],
                    '--instance',instance,'--arm',arm,'--output',out,'--dispatch-limit','40','--request-limit',str(40+limit if arm=='rsi' else 40),
                    '--learning-call-budget','100000','--learning-dispatch-limit',str(limit if arm=='rsi' else 0),
                    '--wall-seconds','1200','--settle-seconds',str(settle),'--baseline-date',env['baselineDate'],
                    '--expected-tree',env['environment']['baseTree'],'--expected-version',env['environment']['djangoVersion']]
                if arm=='rsi':
                    argv+=['--learning-pool',pool_path]
                    if seed:argv+=['--seed-assets',seed/'assets','--seed-sessions',seed/'home/sessions']
                print(json.dumps({'stage':stage,'instanceId':instance,'arm':arm,'phase':'run-agent','finishedRuns':len(records)}),flush=True)
                freeze['formalBenchmarkStarted']=True;write(root/'freeze.json',freeze)
                code=command(argv,log);run=out/'state/pilot'/instance;grade=out/'grading.json'
                record={'stage':stage,'instanceId':instance,'arm':arm,'attempt':0,'runDir':str(run),'grading':None,
                    'classification':'UNCLASSIFIED','runnerReturnCode':code,'environment':str(envfile),'seedState':str(seed) if arm=='rsi' and seed else None}
                records.append(record);write(root/'runs.json',records)
                patch=run/'prediction.patch'
                ledger=run/'model-requests.json'
                attempts=json.loads(ledger.read_text()) if ledger.exists() else []
                task_started=any(not r['sessionId'].startswith('rsi-') for r in attempts)
                wire=[json.loads(line) for line in (out/'gateway.log').read_text().splitlines() if line.strip()] if (out/'gateway.log').exists() else []
                sent=[r for r in wire if r.get('request') and r.get('model')]
                delivery_valid=len(sent)==len(attempts) and bool(attempts) and all(r['enableThinking'] is False and 'developer' not in r['messageRoles'] for r in sent)
                needs_service_review=any(r.get('status')=='ERROR' and not r['sessionId'].startswith('rsi-') for r in attempts) and any('upstreamStatus' in r for r in wire)
                record['requestDeliveryVerified']=delivery_valid;record['modelServiceNeedsReview']=needs_service_review
                if patch.exists() and (code==0 or task_started) and delivery_valid and not needs_service_review:
                    print(json.dumps({'stage':stage,'instanceId':instance,'arm':arm,'phase':'official-score'}),flush=True)
                    scorecode=command([args.scorer_python,'-B',project/'scripts/score-prediction.py','--dataset',args.dataset,
                        '--instance',instance,'--prediction',patch,'--work-dir',out/'grader-only','--output',grade],out/'scorer.log')
                    if scorecode==0 and type(json.loads(grade.read_text())['resolved']) is bool:
                        record['grading']=str(grade);record['classification']='GRADED'
                write(root/'runs.json',records)
                report=json.loads(grade.read_text()) if record['grading'] else {}
                print(json.dumps({'stage':stage,'instanceId':instance,'arm':arm,'phase':'saved','resolved':report.get('resolved'),
                    'runnerReturnCode':code,'finishedRuns':len(records)}),flush=True)
                summary=root/('summary-'+str(len(records)).zfill(2)+'.json')
                summarycode=command([sys.executable,'-B',project/'scripts/summarize-paired.py','--manifest',args.manifest,'--runs',root/'runs.json','--output',summary],root/'summary.log')
                # Ambiguous infrastructure or unverifiable inputs stop scale-out, not silently become TASK_FAIL.
                if summarycode or code or not delivery_valid or needs_service_review or not record['grading'] or (out/'budget-settlement-error.json').exists():
                    raise RuntimeError('Saved attempt needs fault review; do not rerun or replace this task automatically: '+out.name)
                if stage=='prefix' and arm=='rsi':seed=out/'state'
    freeze['status']='COMPLETE_SAVED_RESULTS';freeze['finishedAt']=datetime.now(timezone.utc).isoformat();write(root/'freeze.json',freeze)
    print(json.dumps({'status':'COMPLETE_SAVED_RESULTS','runs':len(records),'summary':str(root/'summary-48.json')}),flush=True)


if __name__=='__main__':main()
