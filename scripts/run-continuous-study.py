#!/usr/bin/env python3
"""Thin coordinator for a fixed coding sequence; native logs/assets carry naturally."""
import argparse,hashlib,importlib.util,json,os,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,path)
def command(argv,log,project):
    with log.open('w') as f:return subprocess.run([str(a) for a in argv],cwd=project,stdout=f,stderr=subprocess.STDOUT).returncode

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['proposal','dataset','scorer-python','environments','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--embedding-model',type=Path,required=True)
    p.add_argument('--freeze-only',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--validate-only',action='store_true');args=p.parse_args()
    project=Path(__file__).resolve().parent.parent;root=args.output.resolve();root.mkdir(parents=True,exist_ok=True);frozen=root/'freeze.json'
    assert os.environ.get('RSI_MODEL_UPSTREAM'),'Use the already authorized service'
    assert sha(args.embedding_model)=='6fa0c02a9c302be6f977521d399b4de3a46310a4f2621ee0063747881b673f67','Use the verified original native embedding model'
    proposal=json.loads(args.proposal.read_text());coding=proposal['coding'];ids=coding['orderedNewTaskIds'];assert len(ids)==8 and len(set(ids))==8
    assert coding['budgetProposal']['outputMaxTokens']==8192 and coding['budgetProposal']['totalBackgroundCap']==160 and coding['budgetProposal']['backgroundCallsPerTask']==20
    if not frozen.exists():
        assert args.freeze_only and not any(root.iterdir()),'Freeze before dispatch and preserve previous attempts'
        assert not subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True).strip()
        hashes={str(f.relative_to(project)):sha(f) for name in ['src','adapters','vendor','lib','scripts'] for f in sorted((project/name).rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.suffix not in ['.pyc','.pyo']}
        for name in ['package.json','package-lock.json','cordis.patch.yml']:hashes[name]=sha(project/name)
        old=json.loads((project/'.artifacts/formal-paired-20261003/freeze.json').read_text())['manifest'];seen={c['instanceId'] for stage in ['prefix','heldOut'] for c in old[stage]};assert not seen.intersection(ids)
        cases=[]
        for instance in ids:
            folder=args.environments.resolve()/(instance+'-audited');env=json.loads((folder/'environment.json').read_text());probe=json.loads((folder/'native-environment-preflight.json').read_text());public=json.loads((folder/'task.json').read_text())
            assert env['instanceId']==public['instance_id']==instance and public['base_commit']==coding['baseCommits'][instance]
            assert env['publicInputSha256']==sha(folder/'task.json') and probe['status']=='PASS_PUBLIC_TREE_VERSION_DATE' and probe['taskImage']==env['taskImage']
            cases.append({'instanceId':instance,'environmentFile':str(folder/'environment.json'),'environmentSha256':sha(folder/'environment.json'),'publicSha256':sha(folder/'task.json'),'nativePreflightSha256':sha(folder/'native-environment-preflight.json'),'environment':env})
        freeze={'status':'FROZEN_CONTINUOUS_CODING','revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip(),'inputSha256':hashes,'datasetSha256':sha(args.dataset),'sourceProposalSha256':sha(args.proposal),'model':'qwen3.8-27b','upstreamSha256':hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest(),'embedding':{'file':str(args.embedding_model.resolve()),'sha256':sha(args.embedding_model)},'cases':cases,'budgets':coding['budgetProposal'],'armsByTask':{c['instanceId']:['baseline','rsi'] if i%2==0 else ['rsi','baseline'] for i,c in enumerate(cases)},'historyPolicy':'Each arm retains its own original previous official task logs. RSI also retains natural assets; current source tree resets per task. No grading inputs/outputs are carried.','partialLearningPolicy':'Carry the closed natural state, including incomplete native checkpoints, without score-based asset selection or rescue calls. Report completeness separately.','infraRetryPolicy':'No automatic retry. At most one independently proven unscored INFRA retry for the entire study, retained as a separate audited attempt and included in cost.','frozenAt':datetime.now(timezone.utc).isoformat()}
        write(frozen,freeze)
    freeze=json.loads(frozen.read_text());assert freeze['status']=='FROZEN_CONTINUOUS_CODING'
    assert sha(args.embedding_model)==freeze['embedding']['sha256'] and str(args.embedding_model.resolve())==freeze['embedding']['file']
    if args.freeze_only:print(json.dumps({'status':freeze['status'],'realModelRequests':0}));return
    assert sha(args.dataset)==freeze['datasetSha256'] and sha(args.proposal)==freeze['sourceProposalSha256']
    assert hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest()==freeze['upstreamSha256']
    if args.validate_only:
        assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip()==freeze['revision'] and not subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True).strip()
        assert all((project/name).is_file() and sha(project/name)==digest for name,digest in freeze['inputSha256'].items())
        for case in freeze['cases']:
            env=case['environment'];folder=Path(case['environmentFile']).parent
            assert sha(folder/'environment.json')==case['environmentSha256'] and sha(folder/'task.json')==case['publicSha256'] and sha(folder/'native-environment-preflight.json')==case['nativePreflightSha256']
            for tag,key in [(env['taskTag'],'taskImage'),(env['scorerKey'],'scorerImage')]:assert subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',tag],text=True).strip()==env[key]
        print(json.dumps({'status':'PASS_FROZEN_CONTINUOUS_INPUTS','cases':len(freeze['cases']),'realModelRequests':0}));return
    spec=importlib.util.spec_from_file_location('budget',project/'scripts/learning-budget.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);pool_path=root/'learning-budget.sqlite';pool=module.LearningBudget(pool_path,freeze['budgets']['totalBackgroundCap']);pool.close()
    records=json.loads((root/'runs.json').read_text()) if (root/'runs.json').exists() else [];assert args.resume or not records
    assert all(r.get('status')=='CLOSED_GRADED' for r in records),'Audit incomplete attempts before resume; never silently retry'
    seeds={'baseline':None,'rsi':None}
    for case in freeze['cases']:
        instance=case['instanceId'];env=case['environment'];b=freeze['budgets']
        for arm in freeze['armsByTask'][instance]:
            prior=next((r for r in records if r['instanceId']==instance and r['arm']==arm),None)
            if prior:seeds[arm]=Path(prior['runDir'])/'state';continue
            assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip()==freeze['revision'] and not subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True).strip()
            assert all((project/name).is_file() and sha(project/name)==digest for name,digest in freeze['inputSha256'].items())
            assert sha(Path(case['environmentFile']))==case['environmentSha256']
            assert sha(Path(case['environmentFile']).parent/'task.json')==case['publicSha256'] and sha(Path(case['environmentFile']).parent/'native-environment-preflight.json')==case['nativePreflightSha256']
            for tag,key in [(env['taskTag'],'taskImage'),(env['scorerKey'],'scorerImage')]:assert subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',tag],text=True).strip()==env[key]
            out=root/(instance+'-'+arm+'-0');learning=b['backgroundCallsPerTask'] if arm=='rsi' else 0
            argv=[sys.executable,'-B',project/'scripts/probe-runner.py','--formal','--image',env['taskTag'],'--arm',arm,'--instance',instance,'--output',out,'--dispatch-limit',b['foregroundCallsPerTaskPerArm'],'--request-limit',b['foregroundCallsPerTaskPerArm']+learning,'--learning-call-budget',b['totalBackgroundCap'],'--learning-dispatch-limit',learning,'--wall-seconds',b['wallSecondsPerTask'],'--settle-seconds',b['backgroundSettleSeconds'],'--baseline-date',env['baselineDate'],'--expected-tree',env['environment']['baseTree'],'--expected-version',env['environment']['djangoVersion']]
            if arm=='rsi':
                argv+=['--learning-pool',pool_path,'--embedding-model',args.embedding_model]
                if seeds[arm]:argv+=['--seed-assets',seeds[arm]/'assets','--seed-sessions',seeds[arm]/'home/sessions']
            elif seeds[arm]:argv+=['--baseline-history',seeds[arm]/'home/sessions']
            record={'instanceId':instance,'arm':arm,'status':'RUNNING','runDir':str(out),'previousOwnState':str(seeds[arm]) if seeds[arm] else None,'startedAt':datetime.now(timezone.utc).isoformat()};records.append(record);write(root/'runs.json',records);print(json.dumps(record),flush=True)
            code=command(argv,root/(out.name+'.runner.log'),project);folder=out/'state/pilot'/instance
            requests=json.loads((folder/'model-requests.json').read_text()) if (folder/'model-requests.json').exists() else []
            wire=[json.loads(line) for line in (out/'gateway.log').read_text().splitlines() if line.strip()] if (out/'gateway.log').exists() else [];sent=[r for r in wire if r.get('request') and r.get('model')]
            delivered=bool(requests) and len(sent)==len(requests) and all(r['enableThinking'] is False and 'developer' not in r['messageRoles'] for r in sent)
            service_error=any(r['status']=='ERROR' and r['phase']!='learning' for r in requests) and any('upstreamStatus' in r for r in wire)
            record.update(status='CLOSED_UNCLASSIFIED',runnerReturnCode=code,requestDeliveryVerified=delivered,modelServiceNeedsReview=service_error,knownTokens=sum(r['usage']['totalTokens'] for r in requests if r.get('usage')),unknownActualUsage=sum(not r.get('usage') for r in requests),finishedAt=datetime.now(timezone.utc).isoformat());write(root/'runs.json',records)
            if code or not delivered or service_error or (out/'budget-settlement-error.json').exists():raise SystemExit('Stop on unclassified infrastructure/input health; preserve the attempt, do not convert to task failure.')
            receipt=json.loads((folder/'receipt.json').read_text());assert receipt['formalBenchmark'] is True and receipt['fixture'] is False and receipt['instanceId']==instance and receipt['arm']==arm
            initial=json.loads((folder/'initial.json').read_text())
            if arm=='baseline':assert initial['assets'] is None and not any(name.startswith('rsi_') for name in initial['toolSchemas'])
            elif seeds[arm] is None:
                assert not initial['assets']['memory'] and not initial['assets']['skills']
                before=json.loads((folder/'receipt.json').read_text())['before'];assert all(all(count==0 for count in layer.values()) for layer in before['layers'].values())
            if seeds[arm]:
                snapshot=json.loads((out/'source-snapshot.json').read_text());expected={str(f.relative_to(seeds[arm]/'home/sessions')):sha(f) for f in sorted((seeds[arm]/'home/sessions').rglob('*')) if f.is_file()}
                assert snapshot['inputSha256']['sessions']==expected
                assert all(sha(out/'state/home/sessions'/name)==digest for name,digest in expected.items())
                record['ownPriorRawHistoryExact']=True
            else:record['firstTaskHasNoPriorAssetsOrHistory']=True
            write(root/'runs.json',records)
            grade=out/'grading.json';score_code=command([args.scorer_python,'-B',project/'scripts/score-prediction.py','--dataset',args.dataset,'--instance',instance,'--prediction',folder/'prediction.patch','--work-dir',out/'grader-only','--output',grade],out/'scorer.log',project)
            assert subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',env['scorerKey']],text=True).strip()==env['scorerImage']
            if score_code:raise SystemExit('Official scorer returned no valid report; stop scale-out without feedback or retry.')
            graded=json.loads(grade.read_text());assert type(graded['resolved']) is bool
            record.update(status='CLOSED_GRADED',grading=str(grade),resolved=graded['resolved']);write(root/'runs.json',records);seeds[arm]=out/'state';print(json.dumps(record),flush=True)
    write(root/'completion.json',{'status':'COMPLETE_SAVED_CONTINUOUS_RUNS','arms':len(records),'knownTokens':sum(r['knownTokens'] for r in records),'unknownActualUsage':sum(r['unknownActualUsage'] for r in records),'scoresReturnedToLearning':False,'diagnosticsPending':True})
if __name__=='__main__':main()
