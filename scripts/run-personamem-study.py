#!/usr/bin/env python3
"""Coordinate frozen independent users; all learning stays in the native plugin."""
import argparse,ast,hashlib,json,os,random,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,path)
def grader_from_source(path):
    source=path.read_text();klass=next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name=='Evaluation')
    method=next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=='extract_answer')
    assert hashlib.sha256(ast.get_source_segment(source,method).encode()).hexdigest()=='a619e9665cc3d12e82de4876843c979cbd3e6e6781a8fe1c184fd697583935ae'
    namespace={'re':re};code=ast.Module(body=[ast.ClassDef(name='Evaluation',bases=[],keywords=[],body=[method],decorator_list=[])],type_ignores=[])
    exec(compile(ast.fix_missing_locations(code),'official-answer-method','exec'),namespace);grader=namespace['Evaluation']()
    for text,key,correct in [('<final_answer>(b)</final_answer>','(b)',True),('<final_answer>(a)</final_answer>','(b)',False),('<final_answer>(a) (b)</final_answer>','(b)',False)]:assert bool(grader.extract_answer(text,key)[0])==correct
    return grader

def summarize(root,freeze,scorer,official_source):
    # Offline only. Scores and keys are never passed to probe-runner or any Agent.
    for path,digest in freeze['scorerInputSha256'].items():assert sha(Path(path))==digest
    grader=grader_from_source(official_source);keys=json.loads((scorer/'answers.json').read_text());users=[];total=0;unknown=0
    records=json.loads((root/'runs.json').read_text()) if (root/'runs.json').exists() else []
    for case in freeze['cases']:
        user={'personaId':case['personaId'],'arms':[]};histories=[]
        for arm in ['baseline','rsi']:
            out=root/('persona-'+case['personaId']+'-'+arm);folder=out/'state/pilot'/('persona-'+case['personaId'])
            record=next((r for r in records if r['personaId']==case['personaId'] and r['arm']==arm),None)
            if not record:continue
            requests=json.loads((folder/'model-requests.json').read_text()) if (folder/'model-requests.json').exists() else []
            wire=[json.loads(l) for l in (out/'gateway.log').read_text().splitlines() if l.strip()] if (out/'gateway.log').exists() else []
            sent=[r for r in wire if r.get('request') and r.get('model')]
            assert len(sent)==len(requests),'Gateway/native ledger mismatch; withhold paired result'
            assert all(r['enableThinking'] is False and 'developer' not in r['messageRoles'] for r in sent)
            rows=json.loads((folder/'answers.json').read_text()) if (folder/'answers.json').exists() else []
            assert len({q['questionId'] for q in rows})==len(rows) and all(q['questionId'] in case['questionIds'] for q in rows)
            scores=[{'questionId':q['questionId'],'correct':bool(grader.extract_answer(q['response'],keys[q['questionId']])[0]),'completed':(q.get('stopReason') or {}).get('kind')=='completed','answerAvailable':bool(q['response'].strip()),'responseSha256':hashlib.sha256(q['response'].encode()).hexdigest()} for q in rows]
            receipt=json.loads((folder/'receipt.json').read_text()) if (folder/'receipt.json').exists() else {}
            if receipt:assert not receipt.get('fixture') and receipt.get('formalPersonaMemEvaluation'),'Only real frozen PersonaMem runs may enter an independent report'
            known=sum(r['usage']['totalTokens'] for r in requests if r.get('usage'));missing=sum(not r.get('usage') for r in requests);total+=known;unknown+=missing
            if (folder/'import.json').exists():histories.append(json.loads((folder/'import.json').read_text())['historySha256'])
            user['arms'].append({'arm':arm,'runnerReturnCode':record.get('returncode'),'runnerStatus':receipt.get('status'),'scores':scores,'accuracy':sum(q['correct'] for q in scores)/len(scores) if len(scores)==freeze['questionCountPerUser'] else None,'knownTokens':known,'unknownActualUsage':missing,'foregroundTokens':sum(r['usage']['totalTokens'] for r in requests if r.get('usage') and r['phase']!='learning'),'backgroundTokens':sum(r['usage']['totalTokens'] for r in requests if r.get('usage') and r['phase']=='learning'),'gatewayLedgerMatches':True})
        assert len(set(histories))<=1,'Paired user history changed'
        users.append(user)
    complete=all(len(u['arms'])==2 and all(a['accuracy'] is not None for a in u['arms']) for u in users)
    result={'status':'COMPLETE_INDEPENDENT_SAVED_RESULTS' if complete else 'INCOMPLETE_WITHHOLD_FULL_PAIRED_ESTIMATE','users':users,'plannedUsers':len(users),'knownTokens':total,'unknownActualUsage':unknown,'officialScorerControlsPassed':3,'scoresReturnedToLearning':False,'smallSampleLimit':'Eight correlated user clusters; not the full benchmark or a universal causal guarantee.'}
    if complete:
        delta=[u['arms'][1]['accuracy']-u['arms'][0]['accuracy'] for u in users];rng=random.Random(freeze['selectionSeed']);boot=sorted(sum(rng.choices(delta,k=len(delta)))/len(delta) for _ in range(10000))
        result.update(baselineMacroAccuracy=sum(u['arms'][0]['accuracy'] for u in users)/len(users),rsiMacroAccuracy=sum(u['arms'][1]['accuracy'] for u in users)/len(users),pairedAccuracyDifference=sum(delta)/len(delta),userClusterBootstrap95=[boot[249],boot[9749]],bootstrapDraws=10000)
    write(root/'results.json',result);return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--proposal',type=Path,required=True);p.add_argument('--public',type=Path,required=True);p.add_argument('--scorer',type=Path,required=True);p.add_argument('--official-source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--image',default='dsh-rsi-formal:django__django-11119');p.add_argument('--freeze-only',action='store_true');p.add_argument('--resume',action='store_true');p.add_argument('--report-only',action='store_true');args=p.parse_args()
    project=Path(__file__).resolve().parent.parent;root=args.output.resolve();root.mkdir(parents=True,exist_ok=True);frozen=root/'freeze.json'
    if not frozen.exists():
        assert args.freeze_only,'Freeze the concrete protocol before the first independent dispatch'
        assert not any(root.iterdir()),'Preserve every previous attempt'
        assert not subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True).strip()
        assert os.environ.get('RSI_MODEL_UPSTREAM'),'Use the authorized model service'
        proposal=json.loads(args.proposal.read_text());persona=proposal['persona'];assert len(persona['cases'])==8 and persona['questionCountPerUser']==4
        grader_from_source(args.official_source)
        hashes={str(f.relative_to(project)):sha(f) for name in ['src','adapters','vendor','lib','scripts'] for f in sorted((project/name).rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.suffix not in ['.pyc','.pyo']}
        for name in ['package.json','package-lock.json','cordis.patch.yml']:hashes[name]=sha(project/name)
        public_root=root/'public';public_root.mkdir()
        for case in persona['cases']:
            source=args.public/('persona-'+case['personaId']+'.json');assert sha(source)==case['publicInputSha256']
            (public_root/source.name).write_bytes(source.read_bytes())
        freeze={'status':'FROZEN_INDEPENDENT_PERSONAMEM','revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip(),'inputSha256':hashes,'model':proposal['model'],'upstreamSha256':hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest(),'taskImageId':subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',args.image],text=True).strip(),'taskTag':args.image,'selectionSeed':proposal['selectionSeed'],'questionCountPerUser':persona['questionCountPerUser'],'cases':persona['cases'],'budgets':persona['budgetProposal'],'sourceProposalSha256':sha(args.proposal),'populationProvenance':proposal.get('supersedesForNewDispatchOnly'),'datasetProvenance':proposal.get('datasetProvenance'),'scorerInputSha256':{str(f.resolve()):sha(f) for f in [args.scorer/'answers.json',args.official_source]},'frozenAt':datetime.now(timezone.utc).isoformat(),'diagnosticSampling':'For each user, first two preselected questions and first four delivered Memory references per question. Label direct/partial/unrelated, source attribution and answer correspondence without feeding scores back. All body lengths and request occurrences counted automatically.', 'retryPolicy':'No automatic retry, budget expansion, rescue learning or answer feedback. Stop scale-out on incomplete native learning.','armsByUser':{c['personaId']:['baseline','rsi'] if i%2==0 else ['rsi','baseline'] for i,c in enumerate(persona['cases'])}}
        write(frozen,freeze)
    freeze=json.loads(frozen.read_text())
    if args.report_only:print(json.dumps(summarize(root,freeze,args.scorer,args.official_source)));return
    if args.freeze_only:print(json.dumps({'status':freeze['status'],'freezeSha256':sha(frozen),'realModelRequests':0}));return
    records=json.loads((root/'runs.json').read_text()) if (root/'runs.json').exists() else []
    assert args.resume or not records,'Use resume only for terminal preserved arms, never silently retry'
    assert all(r.get('returncode')==0 and r.get('status')=='CLOSED' for r in records),'Incomplete/ambiguous attempts require a separate audit; no automatic retry'
    for case in freeze['cases']:
        persona=case['personaId'];instance='persona-'+persona
        for arm in freeze['armsByUser'][persona]:
            if any(r['personaId']==persona and r['arm']==arm for r in records):continue
            out=root/(instance+'-'+arm);b=freeze['budgets'];learning=b['backgroundCallsPerUser'] if arm=='rsi' else 0
            argv=[sys.executable,'-B',str(project/'scripts/probe-runner.py'),'--persona-protocol',str(frozen),'--persona-input',str(root/'public'/(instance+'.json')),'--image',freeze['taskTag'],'--arm',arm,'--instance',instance,'--output',str(out),'--dispatch-limit',str(b['foregroundCallsPerQuestion']),'--request-limit',str(learning+freeze['questionCountPerUser']*b['foregroundCallsPerQuestion']),'--learning-call-budget',str(b['backgroundCallsPerUser']),'--learning-dispatch-limit',str(learning),'--wall-seconds',str(b['wallSecondsPerQuestion']),'--settle-seconds',str(b['learningWallSecondsPerUser'])]
            record={'personaId':persona,'arm':arm,'status':'RUNNING','runDir':str(out),'startedAt':datetime.now(timezone.utc).isoformat()};records.append(record);write(root/'runs.json',records);print(json.dumps(record),flush=True)
            with (root/(out.name+'.runner.log')).open('w') as log:code=subprocess.run(argv,cwd=project,stdout=log,stderr=subprocess.STDOUT).returncode
            record.update(status='CLOSED',returncode=code,finishedAt=datetime.now(timezone.utc).isoformat());write(root/'runs.json',records)
            print(json.dumps(record),flush=True)
            if code:
                summarize(root,freeze,args.scorer,args.official_source);raise SystemExit('Stop scale-out: inspect the preserved failure; no unplanned recovery or retry.')
            if arm=='rsi':
                subprocess.run([sys.executable,'-B',str(project/'scripts/personamem-diagnostics.py'),'--run',str(out),'--instance',instance,'--output',str(out/'diagnostics.json')],cwd=project,check=True,stdout=subprocess.DEVNULL)
    print(json.dumps(summarize(root,freeze,args.scorer,args.official_source)),flush=True)
if __name__=='__main__':main()
