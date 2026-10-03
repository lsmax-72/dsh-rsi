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
import time
import uuid


def command(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, **kwargs)



def verify_seed(assets, sessions):
    # Validate only provenance and frozen input bytes; learning stays in the native core.
    hashes={kind:{str(file.relative_to(directory)):hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(directory.rglob('*')) if file.is_file()}
        for kind,directory in [('assets',assets),('sessions',sessions)]}
    stored={}
    for file in sessions.rglob('session.v4.jsonl'):
        with file.open() as handle: header=json.loads(handle.readline())
        if header.get('type')!='session' or header.get('version')!=4 or header['id'] in stored:
            raise ValueError('Invalid or duplicate source session')
        stored[header['id']]=str(file.relative_to(sessions))
    db=sqlite3.connect((assets/'rsi-state.sqlite').as_uri()+'?mode=ro',uri=True)
    try: sources={row[0] for row in db.execute('SELECT id FROM sources')}
    finally: db.close()
    required=sources|{json.loads(file.read_text())['sessionId'] for file in (assets/'learning-runs').glob('*.json')}
    if required-set(stored): raise ValueError('Asset snapshot is missing official source/learning sessions')
    return {'sourceSessionIds':sorted(sources),'requiredSessionIds':sorted(required),'inputSha256':hashes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='dsh-rsi-pilot2:django-11292', help='Prepared task image; source is /opt/task-source')
    parser.add_argument('--arm', choices=['baseline', 'rsi'], required=True)
    parser.add_argument('--instance',default='preflight',help='Unique public task ID; reused across its two arms only')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixture', action='store_true')
    parser.add_argument('--formal',action='store_true')
    parser.add_argument('--expected-tree',help='Verified source Git tree for this task')
    parser.add_argument('--expected-version',help='Verified Django version in its scorer image')
    parser.add_argument('--fixture-learning',action='store_true',help='Fixture-only native learning for quota controls; no real API calls')
    parser.add_argument('--learning-dispatch-limit',type=int,help='New background streams for this run, independent of historical daily usage')
    parser.add_argument('--learning-pool',type=Path,help='Explicitly initialized host experiment pool, never mounted into task containers')
    parser.add_argument('--interrupt-checkpoint', action='store_true', help='Fixture-only SIGKILL after tool edit and durable request ledger')
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
    if args.formal and (args.fixture or args.instance=='preflight' or not args.expected_tree or not args.expected_version): parser.error('Formal runs require real task ID and frozen environment checks')
    if args.formal and args.arm=='rsi' and not args.learning_pool: parser.error('Formal RSI requires a durable learning pool')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',args.instance): parser.error('Invalid task ID')
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
    if not args.fixture and not args.baseline_date:
        parser.error('Real runs require --baseline-date from the scorer image HEAD at the base source tree; current time changes Django development version.')
    if not args.fixture and not os.environ.get('RSI_MODEL_UPSTREAM'):
        parser.error('Real preflight requires the authorized RSI_MODEL_UPSTREAM environment variable.')
    for value in [args.dispatch_limit,args.request_limit,args.wall_seconds]:
        if value < 1: parser.error('Limits must be positive.')
    output = args.output.resolve()
    output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()): parser.error('Output must be empty; preserve every prior attempt.')
    project = Path(__file__).resolve().parent.parent
    patch = json.loads((project/'scripts/container/pilot.patch.json').read_text())
    services = patch[-1]['insert']
    driver = next(s for s in services if s['id']=='rsi-pilot-task')
    driver['config'] = {'arm':args.arm, 'instanceId':args.instance, 'fixture':args.fixture,
        'interruptCheckpoint':args.interrupt_checkpoint, 'baselineDate':args.baseline_date, 'dispatchLimit':args.dispatch_limit,
        'learningCallBudget':args.learning_call_budget, 'learningDispatchLimit':learning_limit, 'fixtureLearning':args.fixture_learning, 'wallTimeMs':args.wall_seconds*1000,
        'settleMs':args.settle_seconds*1000,'formal':args.formal,'expectedTree':args.expected_tree,'expectedVersion':args.expected_version}
    if args.phases: driver['config']['phases']=json.loads(args.phases.read_text())
    if args.arm == 'baseline': services[:] = [s for s in services if s['id']!='rsi']
    else:
        service = next(s for s in services if s['id']=='rsi')
        service['config']['settings']={'dailyCallBudget':args.learning_call_budget}
        if args.fixture:
            service['config']['settings']['learningEnabled']=args.fixture_learning
            if args.fixture_learning: service['config'].update(provider='pilot-fixture',model='fixture')
    if args.fixture: services[:] = [s for s in services if s['id'] not in ['rsi-qwen','rsi-credentials']]
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
    relay_limit=min(args.request_limit,args.dispatch_limit+learning_limit)
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
            shutil.copy2(project/'scripts/audit-session-requests.mjs',root/'audit-session-requests.mjs')
            shutil.copy2(project/'scripts/task-input.mjs',root/'task-input.mjs')
            # Only public problem metadata already present in the prepared task image is reused.
            (root/'pilot.json').write_text(json.dumps(patch,ensure_ascii=False))
            dockerfile = f'FROM {args.image}\nCOPY lib /opt/rsi/lib\nCOPY pilot-task.mjs audit-session-requests.mjs task-input.mjs pilot.json /opt/rsi/scripts/\n'
            if args.seed_assets:
                shutil.copytree(args.seed_assets.resolve(),root/'seed-assets')
                dockerfile += 'COPY --chown=1000:1000 seed-assets /opt/seed-assets\n'
                shutil.copytree(args.seed_sessions.resolve(),root/'seed-sessions')
                dockerfile += 'COPY --chown=1000:1000 seed-sessions /opt/seed-sessions\n'
                seed=verify_seed(root/'seed-assets',root/'seed-sessions')
                (output/'source-snapshot.json').write_text(json.dumps(seed,indent=2))
            (root/'Dockerfile').write_text(dockerfile)
            with (output/'build.log').open('w') as log:
                command('docker','build','--platform','linux/amd64','-t',image,str(root),stdout=log,stderr=subprocess.STDOUT)
        command('docker','network','create','--internal',network,stdout=subprocess.DEVNULL)
        command('docker','volume','create',volume,stdout=subprocess.DEVNULL)
        gateway = None
        if not args.fixture:
            gateway = subprocess.check_output(['docker','run','-d','--network',network,'--network-alias','model',
                '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','256m','--pids-limit','32',
                '-e','RSI_MODEL_UPSTREAM='+os.environ['RSI_MODEL_UPSTREAM'],
                '-e','RSI_MODEL_REQUEST_LIMIT='+str(relay_limit),
                'dsh-rsi-pilot2:gateway','python3','/opt/rsi/scripts/model-gateway.py'],text=True).strip()
            containers.append(gateway)
            command('docker','network','connect','bridge',gateway)
        startup = ('cp -a /opt/seed-assets /state/assets && mkdir -p /state/home && cp -a /opt/seed-sessions /state/home/sessions && ' if args.seed_assets else '')
        startup += 'exec dsh --profile sdk-minimal --patch /opt/rsi/scripts/pilot.json'
        cid = subprocess.check_output(['docker','create','--platform','linux/amd64','--init','--network',network,*policy,
            '--mount',f'type=volume,source={volume},target=/state','-e','QWEN_API_KEY=EMPTY',image,'sh','-c',startup],text=True).strip()
        containers.append(cid)
        info = json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]
        assert info['Config']['User']=='1000:1000' and info['HostConfig']['ReadonlyRootfs'] and not info['HostConfig']['Binds']
        assert len(info['Mounts'])==1 and info['Mounts'][0]['Name']==volume
        assert len(info['NetworkSettings']['Networks'])==1
        (output/'policy.json').write_text(json.dumps({'arm':args.arm,'imageId':info['Image'],
            'user':info['Config']['User'],'networkInternal':True,'rootfsReadOnly':True,'hostBinds':[],
            'experimentOwnedVolume':True,'fixture':args.fixture,'requestLimit':relay_limit,
            'dispatchLimit':args.dispatch_limit,'learningCallBudget':args.learning_call_budget,'learningDispatchLimit':learning_limit, 'fixtureLearning':args.fixture_learning,
            'wallSecondsPerPhase':args.wall_seconds,'settleSecondsPerPhase':args.settle_seconds,
            'formalBenchmark':args.formal,'instanceId':args.instance, 'sourceSessionsRestored':bool(args.seed_sessions), 'effectivePatch':patch},indent=2))
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
        if gateway: (output/'gateway.log').write_text(subprocess.check_output(['docker','logs',gateway],text=True))
        receipt=output/'state/pilot'/args.instance/'receipt.json'
        if args.interrupt_checkpoint: assert killed and state['ExitCode']==137
        else: assert state['ExitCode']==0 and receipt.exists(), (output/'run.log').read_text()[-6000:]
        print(json.dumps({'status':'INTERRUPTION_CAPTURED' if killed else 'PASS','arm':args.arm,'fixture':args.fixture,
            'output':str(output),'formalBenchmarkStarted':args.formal}))
    finally:
        # Export on host timeout or exception too, before removing the only durable state volume.
        if started and not exported:
            stopped=subprocess.run(['docker','stop','--time','10',containers[-1]],capture_output=True)
            copied=subprocess.run(['docker','cp',containers[-1]+':/state/.',str(output/'state')],capture_output=True,text=True)
            (output/'export-status.json').write_text(json.dumps({'returncode':copied.returncode,'stderr':copied.stderr}))
            exported=copied.returncode==0
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


if __name__=='__main__': main()
