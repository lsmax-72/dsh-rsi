#!/usr/bin/env python3
"""Exercise the real coordinator/command/state handoff with explicit offline fixtures."""
import copy, importlib.util, json, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path
P=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('continuous',P/'scripts/run-swe-continuous.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
checks=[];ids=m.thinking.IDS[:2];s={'purpose':'development','model':'qwen3.8-27b','thinking':'off','thinkingConfirmed':True,'budgetConfirmed':True,'serial':True,'emptyStart':True,'historyMode':'native-fork','stageSize':20,'confidenceInterval':None,'cases':[{'instanceId':id,'taskTag':'fixture-image','baselineDate':'@0 +0000','expectedTree':'tree','expectedVersion':'3.1'} for id in ids],'budgets':{'foregroundCalls':40,'wallSeconds':1200,'maxOutputTokens':8192,'learningCallsPerTask':20,'learningTotal':40,'settleSeconds':900},'modelIdentity':{'id':'fixture'},'embeddingModel':'fixture.gguf','scorerPython':'fixture-python','dataset':'fixture.parquet'}
m.spec_check(s)
for change in [{'budgetConfirmed':False},{'thinking':'on'},{'emptyStart':False}]:
    try:m.spec_check(s|change)
    except ValueError:pass
    else:raise AssertionError('Unconfirmed/wrong configuration accepted')
checks.append('budget confirmation, Thinking Off and empty-start gates enforced')
prep=m.load('prepare-swe-environments');formal=m.read(P/'docs/evidence/swe-continuous-formal-draft-20261009.json');legacy=m.read(P/'docs/evidence/swe-expansion-spec-20261008.json')
assert [c['instanceId'] for c in prep.preparation_cases(formal)]==[c['instanceId'] for c in formal['cases']] and len(prep.preparation_cases(legacy))==104
bad=copy.deepcopy(formal);bad['excluded'].append(bad['cases'][0]['instanceId'])
try:prep.preparation_cases(bad)
except ValueError:pass
else:raise AssertionError('Exposed case accepted by continuous preparation')
checks.append('continuous environment preparation preserves all 100 ordered cases without four prefixes and rejects exposed overlap')
m.validate=lambda *a:None;m.thinking.model_identity=lambda:s['modelIdentity']
original_wire=m.native.verify_thinking_wire
m.native.verify_thinking_wire=lambda out,*a,**kw:{'requests':len(m.read(out/'state/pilot'/m.read(out/'state/pilot'/ids[0]/'receipt.json')['instanceId']/'model-requests.json'))} if (out/'state/pilot'/ids[0]).exists() else {'requests':len(m.read(out/'state/pilot'/ids[1]/'model-requests.json'))}
commands=[]
def execute(argv,log,timeout=None):
    argv=[str(x) for x in argv];commands.append(argv);get=lambda k:Path(argv[argv.index(k)+1]);log.write_text('explicit offline fixture\n')
    if Path(argv[2]).name=='probe-runner.py':
        out=get('--output');instance=argv[argv.index('--instance')+1];arm=argv[argv.index('--arm')+1];pilot=out/'state/pilot'/instance;pilot.mkdir(parents=True);state=out/'state';sessions=state/'home/sessions';sessions.mkdir(parents=True)
        expected=json.loads(get('--history-order').read_text());seed=None
        if '--baseline-history' in argv:seed=get('--baseline-history')
        if '--seed-sessions' in argv:seed=get('--seed-sessions')
        prior=[]
        if seed:
            sessions.rmdir();shutil.copytree(seed,sessions);wanted={'sessions':m.files(seed)}
            if arm=='rsi':wanted['assets']=m.files(get('--seed-assets'))
            m.write(out/'source-snapshot.json',{'inputSha256':wanted})
            prior=[{'sessionId':'pilot-'+id+'-task','relativePath':'--workspace--/pilot-'+id+'-task/session.v4.jsonl'} for id in expected]
        if arm=='rsi':
            if '--seed-assets' in argv:shutil.copytree(get('--seed-assets'),state/'assets')
            else:
                (state/'assets/learning-runs').mkdir(parents=True);db=sqlite3.connect(state/'assets/rsi-state.sqlite');db.execute('CREATE TABLE sources(id TEXT)');db.commit();db.close()
        session_id='pilot-'+instance+'-task';file=sessions/'--workspace--'/session_id/'session.v4.jsonl';file.parent.mkdir(parents=True);prefix=[];header={'type':'session','version':4,'id':session_id,'isSeeded':False}
        if seed:
            parent='pilot-'+expected[-1]+'-task';prefix=[json.loads(line) for line in (seed/'--workspace--'/parent/'session.v4.jsonl').read_text().splitlines()][1:];cut=len(prefix);header.update(isSeeded=True,parentSession=parent)
            m.write(pilot/'history-inheritance.json',{'parentSessionId':parent,'inheritedEventCount':cut})
            prefix=prefix+[{'type':'session/end-seed','seq':cut,'data':{'inherited':True}}]
        all_events=prefix+[{'type':'turn/start','seq':len(prefix)},{'type':'turn/end','seq':len(prefix)+1}];file.write_text('\n'.join(json.dumps(r) for r in [header]+all_events)+'\n')
        ledger=[{'sessionId':session_id,'phase':'task','status':'RETURNED','messages':[],'usage':{'inputTokens':12,'outputTokens':8,'totalTokens':20},'finish':{'kind':'stop'},'reasoningChars':0}]
        m.write(pilot/'model-requests.json',ledger);m.write(pilot/'tool-results.json',[]);m.write(pilot/'phases.json',[{'wallMs':100,'stopReason':{'kind':'completed'}}]);m.write(pilot/'reconstruction.json',[{'matches':True}]);(pilot/'prediction.patch').write_text('synthetic patch')
        m.write(pilot/'receipt.json',{'runnerStatus':'COMPLETED','nativeFiberDisposed':True,'formalBenchmark':True,'fixture':False,'instanceId':instance,'arm':arm,'backgroundDispatches':0})
        m.write(pilot/'initial.json',{'assets':None if arm=='baseline' else {'memory':[],'skills':[]},'toolSchemas':[],'priorTaskLogs':prior})
        (out/'gateway.log').write_text(json.dumps({'request':1,'model':'qwen3.8-27b','maxOutputTokens':8192})+'\n');return 0
    out=get('--output');instance=argv[argv.index('--instance')+1];m.write(out,{'instanceId':instance,'resolved':False,'patchSha256':m.sha(get('--prediction')),'verifiedSourceFiles':50,'modelRequests':0});return 1 if '001-rsi' in str(out) else 0
m.thinking.execute=execute
with tempfile.TemporaryDirectory() as td:
    root=Path(td);m.run(root,s);assert m.read(root/'state.json')['status']=='COMPLETE';assert len(commands)==8
    saved=m.rows(root);assert sum(r['status']=='CLOSED_INFRA' for r in saved)==1
    for arm in m.ARMS:
        first=next(r for r in saved if r['position']==1 and r['arm']==arm);second=next(r for r in saved if r['position']==2 and r['arm']==arm)
        assert second['previousOwnState']==str(Path(first['runDir'])/'state') and second['ownPriorRawHistoryExact'] and second['checkpointVerified'] and second['directNativeHistoryInherited']
        cmd=next(cmd for cmd in commands if Path(cmd[2]).name=='probe-runner.py' and cmd[cmd.index('--arm')+1]==arm and cmd[cmd.index('--instance')+1]==ids[1]);assert '--history-order' in cmd
        assert ('--seed-assets' in cmd)==(arm=='rsi') and ('--baseline-history' in cmd)==(arm=='baseline')
        assert not any('grader-only' in item for item in cmd)
    result=m.read(root/'summary.json');assert result['overall']['pairedNet'] is None and result['overall']['arms']['rsi']['officialPassRate'] is None and result['overall']['arms']['rsi']['infrastructureCases']==1
    before=len(commands);m.run(root,s,True);assert len(commands)==before
    r=saved[0];cp=m.checkpoint_check(root,r);file=Path(cp['state'])/'home/sessions'/next(iter(cp['sessions']));file.write_text(file.read_text()+'tamper')
    try:m.checkpoint_check(root,r)
    except ValueError:pass
    else:raise AssertionError('Tampered state accepted')
checks+=['real run_arm command passes prior own sessions/RSI assets and frozen order, never grader files','scorer failure keeps verified natural state and proceeds to later pair','all four cases close and resume never replays them','INFRA is excluded from official complete pass rate/net difference','closed-checkpoint tampering rejected']
with tempfile.TemporaryDirectory() as td:
    root=Path(td);(root/'STOP').touch();before=len(commands);m.run(root,s);assert len(commands)==before and m.read(root/'state.json')['status']=='STOPPED'
    m.write(m.record_file(root,1,'baseline'),{'position':1,'instanceId':ids[0],'arm':'baseline','attempt':0,'status':'RUNNING'})
    try:m.run(root,s,True)
    except ValueError:pass
    else:raise AssertionError('Ambiguous execution replayed')
checks+=['STOP prevents dispatch and ambiguous RUNNING cannot replay']
with tempfile.TemporaryDirectory() as td:
    root=Path(td);hundred=copy.deepcopy(s);hundred['cases']=[{'instanceId':'django__django-'+str(50000+i)} for i in range(100)]
    for i,c in enumerate(hundred['cases'],1):
        for arm in m.ARMS:m.write(m.record_file(root,i,arm),{'position':i,'instanceId':c['instanceId'],'arm':arm,'attempt':0,'status':'CLOSED_GRADED','resolved':i%3==0,'foreground':{'calls':1,'knownTotalTokens':20,'unknownUsageRequests':0},'learning':{'calls':0,'knownTotalTokens':0,'unknownUsageRequests':0}})
    result=m.summarize(root,hundred);assert result['status']=='COMPLETE' and len(result['stages'])==5 and result['confidenceInterval'] is None and result['overall']['pairedNet']==0
    assert [r['stage']['start'] for r in result['stages']]==[1,21,41,61,81] and [r['cumulative']['end'] for r in result['stages']]==[20,40,60,80,100]
checks.append('100-pair synthetic report creates five stage/cumulative blocks with no iid interval or asset reset')
m.native.verify_thinking_wire=original_wire
# Original real bytes remain strict; shutdown evidence is admitted only at its
# recorded boundary. This is an offline copy of the saved cancellation case.
source=P/'.artifacts/thinking-preexperiment-v4-20261008/django__django-11815-on-0'
with tempfile.TemporaryDirectory() as td:
    out=Path(td);shutil.copytree(source/'state/pilot',out/'state/pilot');shutil.copytree(source/'gateway-evidence',out/'gateway-evidence');wire=[json.loads(l) for l in (source/'gateway.log').read_text().splitlines() if l.strip()]
    for w in wire:
        if w.get('error')=='CLIENT_DISCONNECTED':w['finishedAt']=2000
    (out/'gateway.log').write_text('\n'.join(json.dumps(w) for w in wire)+'\n')
    receipt={'runnerStatus':'COMPLETED','nativeFiberDisposed':True,'shutdownStartedAt':2000,'shutdownFinishedAt':2100}
    proof=original_wire(out,'on',write_result=False,shutdown_receipt=receipt);assert proof['budgetAbortedRequestIds']==[34]
    # Remove the wall termination so only a falsified shutdown timing remains.
    for p in (out/'state/pilot').glob('*/phases.json'):m.write(p,[{'stopReason':{'kind':'completed'},'finishedAt':1000}])
    receipt['shutdownStartedAt']=5000;receipt['shutdownFinishedAt']=5100
    try:original_wire(out,'on',write_result=False,shutdown_receipt=receipt)
    except AssertionError:pass
    else:raise AssertionError('Partial stream unrelated to shutdown accepted')
checks.append('real saved partial-byte Thinking audit requires a proven shutdown/time-budget boundary, not any incomplete response')
result={'status':'PASS_OFFLINE_CONTINUOUS_RUNNER','realModelRequests':0,'scorerInvocations':0,'syntheticScoresAreExperimentResults':False,'checks':checks}
p=Path(sys.argv[1]) if len(sys.argv)>1 else None
if p:m.write(p,result)
print(json.dumps(result,ensure_ascii=False))
