#!/usr/bin/env python3
"""Run one isolated arm; formal mode requires explicit fixed environment inputs."""
import argparse
import importlib.util
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import tarfile
import time
import uuid


def command(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)



def export_gateway_evidence(gateway, output):
    # Docker's archive API misses tmpfs mounts on this host; read through the
    # live container before cleanup. Never recreate missing original bytes.
    archive = output / 'gateway-evidence-export.tar'
    with archive.open('wb') as stream:
        result = subprocess.run(['docker', 'exec', gateway, '/usr/bin/python3', '-c',
            "import sys,tarfile; t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|'); t.add('/tmp/gateway-evidence',arcname='gateway-evidence'); t.close()"],
            stdout=stream, stderr=subprocess.PIPE, timeout=30)
    receipt = {'method':'live-container-exec-tar', 'returncode':result.returncode,
               'stderr':result.stderr.decode(errors='replace'), 'rawArchiveSha256':hashlib.sha256(archive.read_bytes()).hexdigest()}
    if result.returncode == 0:
        with tarfile.open(archive) as saved:
            for item in saved:
                if item.isdir(): continue
                name = Path(item.name)
                if not item.isfile() or len(name.parts) != 2 or name.parts[0] != 'gateway-evidence' or not re.fullmatch(r'request-[0-9]+\.(request\.json|response\.bin|summary\.json)',name.name):
                    raise ValueError('Unexpected gateway archive member')
                target = output / name; target.parent.mkdir(exist_ok=True)
                target.write_bytes(saved.extractfile(item).read())
        receipt['exportedFiles'] = len(list((output/'gateway-evidence').iterdir()))
    (output/'gateway-evidence-export.json').write_text(json.dumps(receipt)+'\n')
    return receipt


def discard_exported_npm_cache(output):
    # Downloaded package blobs are not experimental evidence or source-state inputs.
    # Keep npm logs and all task, session, asset, and grader artifacts.
    target = output / 'state/user/.npm/_cacache'
    status = 'NOT_PRESENT'
    if target.exists() or target.is_symlink():
        if target.is_symlink() or target.resolve() != target.absolute():
            status = 'PRESERVED_UNSAFE_PATH'
        else:
            shutil.rmtree(target)
            status = 'OMITTED_REBUILDABLE_DOWNLOAD_CACHE'
    (output / 'export-cache-policy.json').write_text(json.dumps({'path':'state/user/.npm/_cacache','status':status}) + '\n')


def verify_seed(assets, sessions):
    # Validate only provenance and frozen input bytes; learning stays in the native core.
    hashes={kind:{str(file.relative_to(directory)):hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(directory.rglob('*')) if file.is_file()}
        for kind,directory in [('assets',assets),('sessions',sessions)] if directory is not None}
    stored={}
    for file in sessions.rglob('session.v4.jsonl'):
        with file.open() as handle: header=json.loads(handle.readline())
        if header.get('type')!='session' or header.get('version')!=4 or header['id'] in stored:
            raise ValueError('Invalid or duplicate source session')
        stored[header['id']]=str(file.relative_to(sessions))
    # The coordinator supplies closed own-state only; include task paths, never learning logs or scores.
    prior_tasks=[]
    for session_id,relative_path in sorted(stored.items()):
        if not re.fullmatch(r'pilot-django__django-\d+-task',session_id): continue
        if relative_path != f'--workspace--/{session_id}/session.v4.jsonl':
            raise ValueError('Unexpected restored task log path')
        boundaries=[json.loads(line)['type'] for line in (sessions/relative_path).read_text().splitlines() if json.loads(line).get('type') in ['turn/start','turn/end']]
        if not boundaries or boundaries[-1]!='turn/end':
            raise ValueError('Restored task log is not closed')
        prior_tasks.append({'sessionId':session_id,'relativePath':relative_path})
    if assets is None:
        return {'requiredSessionIds':sorted(stored),'inputSha256':{'sessions':hashes['sessions']},'priorTaskLogs':prior_tasks}
    db=sqlite3.connect((assets/'rsi-state.sqlite').as_uri()+'?mode=ro',uri=True)
    try: sources={row[0] for row in db.execute('SELECT id FROM sources')}
    finally: db.close()
    required=sources|{json.loads(file.read_text())['sessionId'] for file in (assets/'learning-runs').glob('*.json')}
    if required-set(stored): raise ValueError('Asset snapshot is missing official source/learning sessions')
    return {'sourceSessionIds':sorted(sources),'requiredSessionIds':sorted(required),'inputSha256':hashes,'priorTaskLogs':prior_tasks}


def verify_thinking_wire(output,mode,allow_budget_abort=False,write_result=True,shutdown_receipt=None):
    rows=[json.loads(line) for line in (output/'gateway.log').read_text().splitlines() if line.strip()]
    sent=[r for r in rows if r.get('request') and r.get('model')]
    summaries=[r for r in rows if 'responseRequest' in r]
    assert sent and len(sent)==len(summaries),'Missing complete wire response evidence'
    assert {r['request'] for r in sent}=={r['responseRequest'] for r in summaries},'Wire evidence IDs differ'
    assert all(r['enableThinking'] is (mode=='on') for r in sent),'Thinking switch not delivered'
    ledgers=list((output/'state/pilot').glob('*/model-requests.json'))
    phases=[r for path in (output/'state/pilot').glob('*/phases.json') for r in json.loads(path.read_text())]
    timed_out=any('wall time' in json.dumps(r.get('stopReason',{})).lower() for r in phases)
    budget_aborted=[]
    for r in summaries:
        assert r['parseErrors']==0,'Unparseable upstream response'
        complete=r['responseComplete'] and ('event-stream' not in r['contentType'] or r['sseDone'])
        if not complete:
            at=r.get('finishedAt',0)
            closed_shutdown=bool(shutdown_receipt and shutdown_receipt.get('nativeFiberDisposed') is True and shutdown_receipt.get('runnerStatus')=='COMPLETED' and shutdown_receipt['shutdownStartedAt']-1000<=at<=shutdown_receipt['shutdownFinishedAt']+1000)
            closed_wall=bool(shutdown_receipt and timed_out and any('wall time' in json.dumps(p.get('stopReason',{})).lower() and at>=p['finishedAt']-1000 for p in phases))
            independent_wall=allow_budget_abort and timed_out and r['responseRequest']==max(x['request'] for x in sent)
            assert (independent_wall or closed_shutdown or closed_wall) and r['error']=='CLIENT_DISCONNECTED','Unfinished upstream response outside declared budget cancellation/shutdown'
            budget_aborted.append(r['responseRequest'])
        for key,path in [('requestSha256','rawRequest'),('responseSha256','rawResponse')]:
            assert hashlib.sha256((output/'gateway-evidence'/r[path]).read_bytes()).hexdigest()==r[key],'Wire evidence bytes changed'
    chars=sum(r['reasoningChars'] for r in summaries)
    nativeChars=sum(r.get('reasoningChars',0) for path in ledgers for r in json.loads(path.read_text()))
    if ledgers:
        assert nativeChars==chars,'Service/native reasoning audit differs'
        assert (nativeChars>0 if mode=='on' else nativeChars==0),'Service reasoning was not faithfully exposed by the native provider'
    assert (chars>0 if mode=='on' else chars==0),'Requested Thinking mode has no matching real service reasoning'
    result={'status':'PASS_ACTUAL_THINKING_WIRE','thinking':mode,'requests':len(sent),'reasoningChars':chars,'reasoningContentChars':sum(r['reasoningContentChars'] for r in summaries),'nativeReasoningChars':nativeChars if ledgers else None,'responseModels':sorted({model for r in summaries for model in r['responseModels']}),'systemFingerprints':sorted({fp for r in summaries for fp in r['systemFingerprints']}),'weightsHash':None,'rawEvidence':'gateway-evidence','budgetAbortedRequestIds':budget_aborted,'allResponsesComplete':not budget_aborted}
    if write_result:(output/'thinking-wire.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-budget-abort',action='store_true',help='Thinking preexperiment only: audit exact partial bytes at a declared task wall-time cancellation')
    parser.add_argument('--verify-thinking-wire',action='store_true',help='Strict service reasoning audit for this independent baseline preexperiment only')
    parser.add_argument('--thinking',choices=['on','off'],default='off',help='Baseline independent SWE task only: opt in to actual provider reasoning')
    parser.add_argument('--image', default='dsh-rsi-pilot2:django-11292', help='Prepared task image; source is /opt/task-source')
    parser.add_argument('--embedding-model',type=Path,help='Pinned native local GGUF copied read-only into the experiment image; no host bind')
    parser.add_argument('--arm', choices=['baseline', 'rsi'], required=True)
    parser.add_argument('--instance',default='preflight',help='Unique public task ID; reused across its two arms only')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixture', action='store_true')
    parser.add_argument('--persona-fixture-closed-profile-failure',action='store_true',help='Fixture only: complete history job, close an independent native profile quota failure, then answer with frozen assets')
    parser.add_argument('--persona-fixture-closed-learning-failure',action='store_true',help='Fixture only: store native assets then abort Skill review; verify opt-in foreground continuation, zero real models')
    parser.add_argument('--fixture-answer-stop',choices=['stop','max-tokens','error-after-text'],default='stop',help='PersonaMem fixture only: native finish reason; never modifies a real provider')
    parser.add_argument('--scope-quality-protocol',type=Path,help='Frozen synthetic cross-scope quality diagnostic; no scorer or task tools')
    parser.add_argument('--persona-input',type=Path,help='Public PersonaMem input only; answers must be absent')
    parser.add_argument('--persona-protocol',type=Path,help='Frozen independent PersonaMem manifest; validates user, questions, public hash and budgets before dispatch')
    parser.add_argument('--persona-fixture-questions',type=int,choices=[2,4],default=2,help='Fixture-only question count; real independent cases require a frozen manifest')
    parser.add_argument('--validate-only',action='store_true',help='Verify a frozen PersonaMem case without Docker or model dispatch')
    parser.add_argument('--profile-recovery',action='store_true',help='Native checkpoint recovery only; requires matching closed assets/source logs, no foreground tasks')
    parser.add_argument('--formal',action='store_true')
    parser.add_argument('--expected-tree',help='Verified source Git tree for this task')
    parser.add_argument('--expected-version',help='Verified Django version in its scorer image')
    parser.add_argument('--fixture-learning',action='store_true',help='Fixture-only native learning for quota controls; no real API calls')
    parser.add_argument('--learning-dispatch-limit',type=int,help='New background streams for this run, independent of historical daily usage')
    parser.add_argument('--learning-pool',type=Path,help='Explicitly initialized host experiment pool, never mounted into task containers')
    parser.add_argument('--interrupt-checkpoint', action='store_true', help='Fixture-only SIGKILL after tool edit and durable request ledger')
    parser.add_argument('--fixture-compact',action='store_true',help='Fixture-only native idle compaction test; no real model dispatch')
    parser.add_argument('--history-order',type=Path,help='Continuous study: exact prior task ID sequence, independently checked against restored sessions')
    parser.add_argument('--baseline-history',type=Path,help='Continuous study only: previous baseline official logs, with no RSI assets or grading files')
    parser.add_argument('--seed-assets', type=Path, help='Copy an experiment-owned frozen asset store; never a personal profile')
    parser.add_argument('--seed-sessions',type=Path,help='Matching experiment-owned official session directory for source reconstruction')
    parser.add_argument('--phases', type=Path, help='JSON list of named prompts for a small preflight only')
    parser.add_argument('--baseline-date', help='Verified scorer image HEAD date at the base source tree; required for real runs')
    parser.add_argument('--dispatch-limit', type=int, default=25)
    parser.add_argument('--request-limit', type=int, default=40)
    parser.add_argument('--learning-call-budget', type=int, default=15)
    parser.add_argument('--wall-seconds', type=int, default=1200)
    parser.add_argument('--settle-seconds', type=int, default=90)
    args = parser.parse_args()
    if args.scope_quality_protocol and (args.arm!='rsi' or args.persona_input or args.formal or args.phases or args.seed_assets or args.seed_sessions or args.profile_recovery or args.learning_pool or args.baseline_history): parser.error('Scope quality requires a fresh RSI-only diagnostic')
    if args.persona_fixture_closed_profile_failure and not (args.fixture and args.fixture_learning and args.persona_input and args.arm=='rsi'): parser.error('Closed-profile control requires a native PersonaMem RSI learning fixture')
    if args.persona_fixture_closed_profile_failure and args.persona_fixture_closed_learning_failure: parser.error('Use one declared fixture failure mode')
    if args.persona_fixture_closed_learning_failure and not (args.fixture and args.fixture_learning and args.persona_input and args.arm=='rsi'): parser.error('Closed-learning failure control requires a native PersonaMem RSI learning fixture')
    if args.fixture_answer_stop!='stop' and (not args.fixture or not args.persona_input): parser.error('Synthetic finish reasons require a PersonaMem fixture')
    if args.persona_fixture_questions!=2 and (not args.fixture or not args.persona_input): parser.error('Synthetic question count requires a PersonaMem fixture')
    if args.validate_only and not args.persona_protocol: parser.error('Validation-only requires an independent PersonaMem protocol')
    if args.persona_protocol and (not args.persona_input or args.fixture or args.formal or args.profile_recovery): parser.error('Independent PersonaMem requires its frozen protocol and real public input only')
    if args.profile_recovery and (args.arm!='rsi' or not args.seed_assets or not args.seed_sessions or args.persona_input or args.formal or args.phases): parser.error('Profile recovery requires RSI and its closed native assets/source logs only')
    if args.formal and (args.fixture or args.instance=='preflight' or not args.expected_tree or not args.expected_version): parser.error('Formal runs require real task ID and frozen environment checks')
    if args.formal and args.arm=='rsi' and not args.learning_pool: parser.error('Formal RSI requires a durable learning pool')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',args.instance): parser.error('Invalid task ID')
    if args.baseline_history and (args.arm!='baseline' or args.seed_assets or args.seed_sessions or args.persona_input or args.profile_recovery or (not args.formal and not args.fixture)): parser.error('Baseline raw history requires its own continuous task arm and no assets')
    if args.fixture_compact and not (args.fixture and args.history_order):parser.error('Native compaction fixture requires --fixture and ordered history')
    if args.history_order and (args.persona_input or args.scope_quality_protocol or args.profile_recovery or args.phases):parser.error('Ordered history is for coding sequences only')
    if args.seed_sessions and not args.seed_assets: parser.error('Source sessions require matching asset snapshot')
    if args.seed_assets and not args.seed_sessions: parser.error('Asset snapshots require matching official source sessions')
    if args.fixture_learning and (not args.fixture or args.arm!='rsi'): parser.error('Fixture learning requires --fixture --arm rsi')
    if args.learning_pool and args.arm!='rsi': parser.error('Baseline cannot reserve a learning pool')
    learning_limit=args.learning_dispatch_limit if args.learning_dispatch_limit is not None else args.learning_call_budget
    if learning_limit<0 or args.learning_call_budget<0 or args.settle_seconds<0: parser.error('Invalid background limit or settling window')
    if args.interrupt_checkpoint and not args.fixture:
        parser.error('Interruption control must use a fixture, not a paid model request.')
    if args.arm == 'baseline' and args.seed_assets:
        parser.error('Baseline cannot receive RSI assets.')
    if not args.fixture and not args.persona_input and not args.profile_recovery and not args.scope_quality_protocol and not args.baseline_date:
        parser.error('Real runs require --baseline-date from the scorer image HEAD at the base source tree; current time changes Django development version.')
    if not args.fixture and not os.environ.get('RSI_MODEL_UPSTREAM'):
        parser.error('Real preflight requires the authorized RSI_MODEL_UPSTREAM environment variable.')
    for value in [args.dispatch_limit,args.request_limit,args.wall_seconds]:
        if value < 1: parser.error('Limits must be positive.')
    if args.thinking=='on':args.verify_thinking_wire=True
    if args.allow_budget_abort and not args.verify_thinking_wire:parser.error('Budget-abort audit requires actual Thinking wire verification')
    if args.verify_thinking_wire and (args.arm!='baseline' or not args.formal or args.fixture or args.persona_input or args.scope_quality_protocol or args.phases or args.baseline_history or args.seed_assets or learning_limit!=0 or args.learning_pool):parser.error('Thinking wire verification requires an independent formal baseline SWE task with zero learning')
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()): parser.error('Output must be empty; preserve every prior attempt.')
    project = Path(__file__).resolve().parent.parent
    patch = json.loads((project/'scripts/container/pilot.patch.json').read_text())
    services = patch[-1]['insert']
    driver = next(s for s in services if s['id']=='rsi-pilot-task')
    provider=next(s for s in services if s['id']=='rsi-qwen')['config']['providers']['qwen']
    provider['reasoning']='low' if args.thinking=='on' else 'off'
    driver['config'] = {'arm':args.arm, 'thinking':args.thinking, 'instanceId':args.instance, 'fixture':args.fixture,
        'fixtureAnswerStop':args.fixture_answer_stop,'interruptCheckpoint':args.interrupt_checkpoint, 'baselineDate':args.baseline_date, 'dispatchLimit':args.dispatch_limit,
        'learningCallBudget':args.learning_call_budget, 'learningDispatchLimit':learning_limit, 'fixtureLearning':args.fixture_learning, 'wallTimeMs':args.wall_seconds*1000,
        'settleMs':args.settle_seconds*1000,'formal':args.formal,'expectedTree':args.expected_tree,'expectedVersion':args.expected_version}
    if args.persona_fixture_closed_profile_failure:
        driver['config'].update(fixtureClosedProfileFailure=True,learningFailurePolicy='evaluate-closed-native-failure-v2')
    if args.persona_fixture_closed_learning_failure:
        driver['config'].update(fixtureClosedLearningFailure=True,learningFailurePolicy='evaluate-closed-bounded-failure')
    if args.phases: driver['config']['phases']=json.loads(args.phases.read_text())
    if args.persona_input:
        if args.formal or args.phases or args.seed_assets: parser.error('PersonaMem pilot uses its own public history, not coding phases or old snapshots')
        public=json.loads(args.persona_input.read_text())
        expected_questions=args.persona_fixture_questions if args.fixture else 2
        if args.persona_protocol:
            frozen=json.loads(args.persona_protocol.read_text())
            if frozen.get('status') not in ['FROZEN_INDEPENDENT_PERSONAMEM','FROZEN_PERSONAMEM_REPLICATION'] or frozen.get('model')!='qwen3.8-27b': parser.error('Independent PersonaMem protocol is not frozen for the configured model')
            if frozen['status']=='FROZEN_PERSONAMEM_REPLICATION' and (frozen.get('cohortKind')!='preexposed-development-replication' or frozen.get('independenceClaim') is not False): parser.error('Replication exposure label missing')
            case=next((c for c in frozen['cases'] if c['personaId']==public['personaId']),None)
            if case is None or case['publicInputSha256']!=hashlib.sha256(args.persona_input.read_bytes()).hexdigest() or case['questionIds']!=[q['id'] for q in public['questions']]: parser.error('Public PersonaMem input differs from the frozen case')
            expected_questions=frozen['questionCountPerUser']
            if frozen['upstreamSha256']!=hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest(): parser.error('Frozen model endpoint changed')
            image_id=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',args.image],text=True).strip()
            if image_id!=frozen['taskImageId']: parser.error('Frozen task/runtime image changed')
            budgets=frozen['budgets']
            if budgets['maxOutputTokens']!=4096 or budgets['quietSeconds']!=45: parser.error('Unsupported independent PersonaMem output/quiet budgets')
            if (args.dispatch_limit,args.wall_seconds,args.learning_call_budget,args.settle_seconds)!=(budgets['foregroundCallsPerQuestion'],budgets['wallSecondsPerQuestion'],budgets['backgroundCallsPerUser'],budgets['learningWallSecondsPerUser']): parser.error('PersonaMem limits differ from the frozen budgets')
            expected_learning=budgets['backgroundCallsPerUser'] if args.arm=='rsi' else 0
            if learning_limit!=expected_learning or args.request_limit!=(expected_learning+expected_questions*args.dispatch_limit): parser.error('PersonaMem actual dispatch/gateway cap differs from protocol')
            if subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip()!=frozen['revision'] or subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True).strip(): parser.error('Frozen PersonaMem revision or clean checkout changed')
            if any(not (project/path).is_file() or hashlib.sha256((project/path).read_bytes()).hexdigest()!=sha for path,sha in frozen['inputSha256'].items()): parser.error('Frozen implementation bytes changed')
            driver['config']['personaFormal']=True
            learning_policy=frozen.get('learningFailurePolicy','require-complete')
            if learning_policy not in ['require-complete','evaluate-closed-bounded-failure','evaluate-closed-native-failure-v2']: parser.error('Unknown frozen learning failure policy')
            driver['config']['learningFailurePolicy']=learning_policy
        if len(public.get('questions',[]))!=expected_questions or any('correct_answer' in q for q in public['questions']): parser.error('Public question count/answer separation differs from the selected PersonaMem mode')
        driver['config']['expectedQuestionCount']=expected_questions
        driver['name']='/opt/rsi/scripts/personamem-pilot-task.mjs'
        next(row for row in patch if row['id']=='tools')['config']['mode']='native'
        driver['config']['phases']=[{'name':q['id']} for q in public['questions']]
        services[:]=[row for row in services if row['id'] not in ['rsi-fs','rsi-files','rsi-search','rsi-shell','rsi-shell-env','rsi-bash','rsi-ptc']]
    if args.scope_quality_protocol:
        frozen=json.loads(args.scope_quality_protocol.read_text())
        if frozen.get('status')!='FROZEN_SYNTHETIC_SCOPE_QUALITY' or frozen.get('model')!='qwen3.8-27b': parser.error('Scope quality protocol must be frozen for qwen3.8-27b')
        case=next((c for c in frozen['cases'] if c['id']==args.instance),None)
        if case is None or set(case)!=set(['id','historyBefore','historyAfter','question']): parser.error('Unexpected public diagnostic input; rubric stays on reviewer side')
        budgets=frozen['budgets']
        if (args.dispatch_limit,args.learning_call_budget,learning_limit,args.request_limit,args.wall_seconds)!=(budgets['consumerCalls'],budgets['backgroundCalls'],budgets['backgroundCalls'],budgets['totalCalls'],budgets['wallSeconds']): parser.error('Scope quality budgets differ from frozen protocol')
        if not args.fixture:
            if subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',args.image],text=True).strip()!=frozen['taskImageId']: parser.error('Frozen scope runtime base image changed')
            if subprocess.check_output(['git','rev-parse','HEAD'],cwd=project,text=True).strip()!=frozen['revision'] or subprocess.check_output(['git','status','--porcelain'],cwd=project,text=True).strip(): parser.error('Frozen scope quality requires its clean source revision')
            if any(hashlib.sha256((project/file).read_bytes()).hexdigest()!=sha for file,sha in frozen['inputSha256'].items()): parser.error('Scope diagnostic implementation changed')
            if hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest()!=frozen['upstreamSha256']: parser.error('Declared model service changed')
        driver['name']='/opt/rsi/scripts/review-scope-quality.mjs'
        driver['config']['scopeQuality']=True
        next(row for row in patch if row['id']=='tools')['config']['mode']='native'
        services[:]=[row for row in services if row['id'] not in ['rsi-fs','rsi-files','rsi-search','rsi-shell','rsi-shell-env','rsi-bash','rsi-ptc']]
    if args.profile_recovery:
        driver['name']='/opt/rsi/scripts/recover-native-profiles.mjs'
        services[:]=[row for row in services if row['id'] not in ['rsi-fs','rsi-files','rsi-search','rsi-shell','rsi-shell-env','rsi-bash','rsi-ptc']]
        next(row for row in patch if row['id']=='tools')['config']['mode']='native'
    if args.arm == 'baseline': services[:] = [s for s in services if s['id']!='rsi']
    else:
        service = next(s for s in services if s['id']=='rsi')
        service['config']['settings']={'dailyCallBudget':args.learning_call_budget}
        if args.scope_quality_protocol: service['config']['settings'].update(learningEnabled=False,maxTokens=4096,maxIterations=8,timeoutMs=180000)
        if args.fixture:
            service['config']['settings']['learningEnabled']=False if args.scope_quality_protocol else args.fixture_learning
            if args.fixture_learning or args.scope_quality_protocol: service['config'].update(provider='pilot-fixture',model='fixture')
    embedding_model=None
    if args.arm=='rsi':
        embedding_model=(args.embedding_model or project/'.artifacts/models/embeddinggemma-300m-qat-Q8_0.gguf').resolve()
        if not embedding_model.is_file(): parser.error('RSI requires a preloaded local GGUF; isolated tasks cannot download models')
        model_sha=hashlib.sha256(embedding_model.read_bytes()).hexdigest()
        if model_sha!='6fa0c02a9c302be6f977521d399b4de3a46310a4f2621ee0063747881b673f67': parser.error('Use the pinned native local model')
        service['config']['embedding']={'provider':'local','modelPath':'/opt/rsi/embedding.gguf'}
    if args.persona_input and args.fixture_learning: service['config']['settings']['idleSeconds']=1
    if args.fixture: services[:] = [s for s in services if s['id'] not in ['rsi-qwen','rsi-credentials']]
    if args.validate_only:
        print(json.dumps({'status':'VALIDATED_NO_DISPATCH','instanceId':args.instance,'personaId':public['personaId'],'questionIds':[q['id'] for q in public['questions']],'arm':args.arm,'realModelRequests':0,'formalBenchmarkStarted':False}));return
    prefix = 'rsi-preflight-' + uuid.uuid4().hex[:10]
    network, volume, image = prefix+'-net',prefix+'-state',prefix+':local'
    pool=None
    if args.learning_pool:
        spec=importlib.util.spec_from_file_location('learning_budget',project/'scripts/learning-budget.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        pool=module.LearningBudget(args.learning_pool.resolve())
        learning_limit=pool.reserve(prefix,learning_limit)
        driver['config']['learningDispatchLimit']=learning_limit
        (output/'budget-reservation.json').write_text(json.dumps({'leaseId':prefix,'quota':learning_limit,'pool':pool.snapshot()},indent=2))
    # Persona limits apply per question; the relay sees the sum of all question budgets.
    foreground_limit=args.dispatch_limit*(len(public['questions']) if args.persona_input else 1)
    relay_limit=min(args.request_limit,foreground_limit+learning_limit)
    gateway = None
    containers = []
    started = False
    exported = False
    policy = ['--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--cpus','2','--memory','3g','--pids-limit','256',
        '--tmpfs','/tmp:rw,exec,uid=1000,gid=1000,mode=700,size=512m',
        '--tmpfs','/workspace:uid=1000,gid=1000,mode=700,size=512m']
    try:
        with tempfile.TemporaryDirectory(prefix='rsi-preflight-build-') as temp:
            root=Path(temp)
            shutil.copytree(project/'lib',root/'lib')
            shutil.copy2(project/'scripts/pilot-task.mjs',root/'pilot-task.mjs')
            shutil.copy2(project/'scripts/model-gateway.py',root/'model-gateway.py')
            if args.scope_quality_protocol:
                shutil.copy2(project/'scripts/review-scope-quality.mjs',root/'review-scope-quality.mjs')
                shutil.copy2(project/'scripts/personamem-history.mjs',root/'personamem-history.mjs')
                (root/'scope-quality.json').write_text(json.dumps(case,ensure_ascii=False))
            if args.profile_recovery:shutil.copy2(project/'scripts/recover-native-profiles.mjs',root/'recover-native-profiles.mjs')
            if args.persona_input:
                shutil.copy2(project/'scripts/personamem-pilot-task.mjs',root/'personamem-pilot-task.mjs')
                shutil.copy2(project/'scripts/personamem-history.mjs',root/'personamem-history.mjs')
                shutil.copy2(project/'scripts/personamem-learning-policy.mjs',root/'personamem-learning-policy.mjs')
                shutil.copy2(project/'scripts/personamem-native-learning-policy.mjs',root/'personamem-native-learning-policy.mjs')
                shutil.copy2(args.persona_input,root/'personamem.json')
            shutil.copy2(project/'scripts/audit-session-requests.mjs',root/'audit-session-requests.mjs')
            shutil.copy2(project/'scripts/task-input.mjs',root/'task-input.mjs')
            # Only public problem metadata already present in the prepared task image is reused.
            shutil.copy2(project/'package.json',root/'package.json')
            shutil.copy2(project/'package-lock.json',root/'package-lock.json')
            dockerfile = f'FROM {args.image}\nUSER root\nCOPY package.json package-lock.json /opt/rsi/\nRUN cd /opt/rsi && npm ci --ignore-scripts\nCOPY lib /opt/rsi/lib\nCOPY model-gateway.py pilot-task.mjs audit-session-requests.mjs task-input.mjs pilot.json /opt/rsi/scripts/\nENV NODE_LLAMA_CPP_GPU=false\n'
            if args.history_order:dockerfile += 'ENV RSI_NATIVE_COMPACTION_MODULE=/opt/dsh/node_modules/@deepseek-ai/dsh-compaction-basic/lib/index.js\n'
            if args.persona_input:
                dockerfile += 'COPY personamem-pilot-task.mjs personamem-history.mjs personamem-learning-policy.mjs personamem-native-learning-policy.mjs /opt/rsi/scripts/\nCOPY personamem.json /opt/rsi/personamem.json\n'
            if args.scope_quality_protocol:dockerfile += 'COPY review-scope-quality.mjs personamem-history.mjs scope-quality.json /opt/rsi/scripts/\n'
            if args.profile_recovery:dockerfile += 'COPY recover-native-profiles.mjs /opt/rsi/scripts/\n'
            if embedding_model:
                shutil.copy2(embedding_model,root/'embedding.gguf')
                dockerfile += 'COPY embedding.gguf /opt/rsi/embedding.gguf\n'
            dockerfile += 'USER 1000:1000\n'
            if args.baseline_history:
                shutil.copytree(args.baseline_history.resolve(),root/'seed-sessions')
                dockerfile += 'COPY --chown=1000:1000 seed-sessions /opt/seed-sessions\n'
                seed=verify_seed(None,root/'seed-sessions')
                driver['config']['priorTaskLogs']=seed['priorTaskLogs']
                (output/'source-snapshot.json').write_text(json.dumps(seed,indent=2))
            if args.seed_assets:
                shutil.copytree(args.seed_assets.resolve(),root/'seed-assets')
                dockerfile += 'COPY --chown=1000:1000 seed-assets /opt/seed-assets\n'
                shutil.copytree(args.seed_sessions.resolve(),root/'seed-sessions')
                dockerfile += 'COPY --chown=1000:1000 seed-sessions /opt/seed-sessions\n'
                seed=verify_seed(root/'seed-assets',root/'seed-sessions')
                driver['config']['priorTaskLogs']=seed['priorTaskLogs']
                (output/'source-snapshot.json').write_text(json.dumps(seed,indent=2))
            if args.history_order:
                ordered=json.loads(args.history_order.read_text())
                if not isinstance(ordered,list) or len(ordered)!=len(set(ordered)) or any(not re.fullmatch(r'django__django-\d+',id) for id in ordered):raise ValueError('Invalid prior task order')
                restored={log['sessionId']:log for log in driver['config'].get('priorTaskLogs',[])}
                if set(restored)!={'pilot-'+id+'-task' for id in ordered}:raise ValueError('Prior task order differs from restored closed sessions')
                driver['config']['priorTaskLogs']=[restored['pilot-'+id+'-task'] for id in ordered]
                driver['config']['continuousState']=True
                driver['config']['fixtureCompact']=args.fixture_compact
                # Match the native desktop context management on both arms.
                # Summarizer output must respect the same gateway output cap.
                services[:0]=[
                    {'id':'continuous-token-meter','name':'@deepseek-ai/dsh-token-meter'},
                    {'id':'continuous-compaction','name':'@deepseek-ai/dsh-compaction-basic','config':{'auto':True,'thresholdRatio':0.8,'headroomTokens':65536,'retainRatio':0.16,'maxTokens':8192,'compactionRetries':1,'maxOverflowRetries':1}},
                    {'id':'continuous-tool-pruner','name':'@deepseek-ai/dsh-compaction-tool-result-pruner','config':{'thresholdChars':8192,'headChars':4096,'tailChars':1024}}]

            (root/'pilot.json').write_text(json.dumps(patch,ensure_ascii=False))
            (root/'Dockerfile').write_text(dockerfile)
            with (output/'build.log').open('w') as log:
                command('docker','build','--platform','linux/amd64','-t',image,str(root),stdout=log,stderr=subprocess.STDOUT)
        command('docker','network','create','--internal',network,stdout=subprocess.DEVNULL)
        command('docker','volume','create',volume,stdout=subprocess.DEVNULL)
        gateway = None
        if not args.fixture:
            gateway = subprocess.check_output(['docker','run','-d','--label','dsh-rsi-output='+str(output),'--label','dsh-rsi-role=gateway','--network',network,'--network-alias','model',
                '--read-only','--tmpfs','/tmp:rw,uid=1000,gid=1000,mode=700,size=128m','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--pids-limit','32',
                '-e','RSI_MODEL_UPSTREAM='+os.environ['RSI_MODEL_UPSTREAM'],
                '-e','RSI_MODEL_REQUEST_LIMIT='+str(relay_limit),
                image,'/usr/bin/python3','/opt/rsi/scripts/model-gateway.py'],text=True).strip()
            containers.append(gateway)
            command('docker','network','connect','bridge',gateway)
        startup = ('cp -a /opt/seed-assets /state/assets && ' if args.seed_assets else '')
        startup += ('mkdir -p /state/home && cp -a /opt/seed-sessions /state/home/sessions && ' if args.seed_assets or args.baseline_history else '')
        startup += 'exec dsh --profile sdk-minimal --patch /opt/rsi/scripts/pilot.json'
        cid = subprocess.check_output(['docker','create','--label','dsh-rsi-output='+str(output),'--label','dsh-rsi-role=task','--platform','linux/amd64','--init','--network',network,*policy,
            '--mount',f'type=volume,source={volume},target=/state','-e','QWEN_API_KEY=EMPTY',image,'sh','-c',startup],text=True).strip()
        containers.append(cid)
        info = json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
        assert info['Config']['User']=='1000:1000' and info['HostConfig']['ReadonlyRootfs'] and not info['HostConfig']['Binds']
        assert len(info['Mounts'])==1 and info['Mounts'][0]['Name']==volume
        assert len(info['NetworkSettings']['Networks'])==1
        (output/'policy.json').write_text(json.dumps({'arm':args.arm,'thinking':args.thinking,'verifyThinkingWire':args.verify_thinking_wire,'imageId':info['Image'],'gatewayImageId':info['Image'] if gateway else None,'gatewaySourceSha256':hashlib.sha256((project/'scripts/model-gateway.py').read_bytes()).hexdigest(),
            'user':info['Config']['User'],'networkInternal':True,'rootfsReadOnly':True,'hostBinds':[],
            'experimentOwnedVolume':True,'fixture':args.fixture,'requestLimit':relay_limit,
            'dispatchLimit':args.dispatch_limit,'learningCallBudget':args.learning_call_budget,'learningDispatchLimit':learning_limit, 'fixtureLearning':args.fixture_learning,
            'wallSecondsPerPhase':args.wall_seconds,'settleSecondsPerPhase':args.settle_seconds,
            'embeddingModelSha256':model_sha if embedding_model else None,'embeddingProvider':'native-local' if embedding_model else None,
            'scopeQualityProtocolSha256':hashlib.sha256(args.scope_quality_protocol.read_bytes()).hexdigest() if args.scope_quality_protocol else None,'syntheticQualityDiagnostic':bool(args.scope_quality_protocol),'formalBenchmark':args.formal or bool(args.persona_protocol),'personaProtocolSha256':hashlib.sha256(args.persona_protocol.read_bytes()).hexdigest() if args.persona_protocol else None,'instanceId':args.instance, 'sourceSessionsRestored':bool(args.seed_sessions or args.baseline_history),'baselineRawHistoryRestored':bool(args.baseline_history), 'effectivePatch':patch},indent=2))
        phase_count = len(driver['config'].get('phases',[{}]))
        until = time.monotonic() + phase_count*(args.wall_seconds+args.settle_seconds)+90
        killed = False
        with (output/'run.log').open('w') as log:
            process = subprocess.Popen(['docker','start','-a',cid],stdout=log,stderr=subprocess.STDOUT,text=True)
            started = True
            while process.poll() is None:
                if args.interrupt_checkpoint and 'RSI_CHECKPOINT_READY' in (output/'run.log').read_text():
                    command('docker','kill',cid,stdout=subprocess.DEVNULL); killed=True; break
                if time.monotonic()>until:
                    command('docker','stop','--time','10',cid,stdout=subprocess.DEVNULL); break
                time.sleep(1)
            process.wait(timeout=20)
        state=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]['State']
        (output/'state.json').write_text(json.dumps({'container':state,'deliberatelyKilled':killed}))
        copied=command('docker','cp',cid+':/state/.',str(output/'state'),capture_output=True)
        exported=True
        discard_exported_npm_cache(output)
        if gateway: (output/'gateway.log').write_text(subprocess.check_output(['docker','logs',gateway],text=True))
        receipt=output/'state/pilot'/args.instance/'receipt.json'
        if args.interrupt_checkpoint: assert killed and state['ExitCode']==137
        else: assert state['ExitCode']==0 and receipt.exists(), (output/'run.log').read_text()[-6000:]
        print(json.dumps({'status':'INTERRUPTION_CAPTURED' if killed else 'PASS','arm':args.arm,'fixture':args.fixture,
            'output':str(output),'formalBenchmarkStarted':args.formal or bool(args.persona_protocol)}))
    finally:
        # Export on host timeout or exception too, before removing the only durable state volume.
        if started and not exported:
            stopped=subprocess.run(['docker','stop','--time','10',containers[-1]],capture_output=True)
            copied=subprocess.run(['docker','cp',containers[-1]+':/state/.',str(output/'state')],capture_output=True,text=True)
            (output/'export-status.json').write_text(json.dumps({'returncode':copied.returncode,'stderr':copied.stderr}))
            exported=copied.returncode==0
        if gateway:
            wirelogs=subprocess.run(['docker','logs',gateway],capture_output=True,text=True)
            (output/'gateway.log').write_text(wirelogs.stdout)
            try: export_gateway_evidence(gateway,output)
            except (OSError,subprocess.TimeoutExpired,ValueError,tarfile.TarError) as error:
                (output/'gateway-evidence-export.json').write_text(json.dumps({'returncode':1,'method':'live-container-exec-tar','error':str(error)}))
        for cid in reversed(containers): subprocess.run(['docker','rm','-f',cid],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        # If export failed, retain the experiment volume for recovery instead of destroying evidence.
        if not started or exported: subprocess.run(['docker','volume','rm',volume],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        else: (output/'retained-volume.json').write_text(json.dumps({'volume':volume}))
        if pool:
            # Never refund a lost or ambiguous attempt: its reservation survives interruption.
            try:
                if not started:
                    pool.settle(prefix,0,'NO_TASK_STARTED')
                elif exported:
                    file=output/'state/pilot'/args.instance/'model-requests.json'
                    requests=json.loads(file.read_text())
                    if not args.fixture:
                        wire=[json.loads(line) for line in (output/'gateway.log').read_text().splitlines() if line.strip()]
                        sent=[row for row in wire if row.get('request') and row.get('model')]
                        if len(sent)!=len(requests): raise ValueError('Gateway/request ledger mismatch; retain entire reservation')
                    used=sum(r['phase']=='learning' for r in requests)
                    pool.settle(prefix,used,hashlib.sha256(file.read_bytes()).hexdigest())
            except (ValueError,OSError,sqlite3.Error) as error:
                (output/'budget-settlement-error.json').write_text(json.dumps({'error':str(error),'reservationRetained':True}))
            finally:
                (output/'budget-settlement.json').write_text(json.dumps(pool.snapshot(),indent=2));pool.close()
        subprocess.run(['docker','network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(['docker','image','rm',image],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    if args.verify_thinking_wire:verify_thinking_wire(output,args.thinking,args.allow_budget_abort)


if __name__=='__main__': main()
