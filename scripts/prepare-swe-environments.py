#!/usr/bin/env python3
"""Prepare fixed SWE environments sequentially in a detached process; never dispatch models."""
import argparse, fcntl, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    os.replace(temporary, path)

def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False

def run(root):
    with (root / 'worker.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another environment worker holds the lock')
        freeze = json.loads((root / 'preparation.json').read_text())
        state = json.loads((root / 'state.json').read_text())
        state.pop('error', None)
        state.update(status='PREPARING', pid=os.getpid(), updatedAt=time.time())
        save(root / 'state.json', state)
        try:
            if sha(freeze['dataset']) != freeze['datasetSha256']:
                raise RuntimeError('Frozen dataset changed')
            for path, expected in freeze['inputHashes'].items():
                if sha(path) != expected:
                    raise RuntimeError('Frozen preparation input changed: ' + path)
            for case in freeze['cases']:
                instance = case['instanceId']
                if instance in state['completed']:
                    entry = state['completed'][instance]
                    if sha(root / instance / 'environment.json') != entry['environmentSha256'] or sha(root / instance / 'task.json') != entry['publicInputSha256']:
                        raise RuntimeError('Completed environment receipt changed: ' + instance)
                    continue
                if (root / 'STOP').exists():
                    state['status'] = 'STOPPED'
                    break
                free = shutil.disk_usage(root).free
                state['freeBytes'] = free
                if free < freeze['minimumFreeBytes']:
                    state['status'] = 'STOPPED_LOW_DISK'
                    break
                env = root / instance
                # Partial directories are evidence. A restart must not silently overwrite them.
                if env.exists():
                    raise RuntimeError('Partial environment requires manual review: ' + str(env))
                for path, expected in freeze['inputHashes'].items():
                    if sha(path) != expected:
                        raise RuntimeError('Frozen preparation input changed: ' + path)
                state.update(current=instance, updatedAt=time.time())
                save(root / 'state.json', state)
                command = [freeze['python'], '-B', freeze['executor'], '--dataset', freeze['dataset'], '--instance', instance, '--output', str(env)]
                with (root / 'logs' / (instance + '.log')).open('x') as log:
                    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
                if result.returncode:
                    raise RuntimeError('Environment preparation failed (%d): %s; no automatic retry' % (result.returncode, instance))
                receipt = json.loads((env / 'environment.json').read_text())
                public = json.loads((env / 'task.json').read_text())
                if receipt['instanceId'] != instance or public['instance_id'] != instance or public['base_commit'] != case['baseCommit']:
                    raise RuntimeError('Environment/public receipt does not match fixed case: ' + instance)
                state['completed'][instance] = {'stage': case['stage'], 'environmentSha256': sha(env / 'environment.json'), 'publicInputSha256': sha(env / 'task.json')}
                state.update(current=None, updatedAt=time.time())
                save(root / 'state.json', state)
            else:
                state['status'] = 'TEST_READY' if freeze['fixture'] else 'READY'
        except Exception as error:
            state.update(status='HALTED', error=str(error))
        finally:
            state['updatedAt'] = time.time()
            save(root / 'state.json', state)
        return 0 if state['status'] in ['READY', 'TEST_READY', 'STOPPED', 'STOPPED_LOW_DISK'] else 1

def preparation_cases(spec):
    if spec.get('purpose')=='formal' and spec.get('historyMode')=='native-fork':
        cases=[dict(c,stage='continuous') for c in spec['cases']]
        if len(cases)!=100 or len({c['instanceId'] for c in cases})!=100 or set(c['instanceId'] for c in cases)&set(spec['excluded']):raise ValueError('Continuous preparation requires 100 unexposed distinct cases, no prefix')
    else:
        cases = [dict(c, stage=stage) for stage in ['prefix', 'heldOut'] for c in spec['manifest'][stage]]
        if len(spec['manifest']['prefix']) != 4 or len(spec['manifest']['heldOut']) != 100 or len({c['instanceId'] for c in cases}) != 104:
            raise ValueError('Legacy preparation requires the fixed 4 + 100 distinct cases')
    return cases

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['start', 'run', 'status'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--spec', type=Path)
    p.add_argument('--dataset', type=Path)
    p.add_argument('--python', type=Path)
    p.add_argument('--fixture-executor', type=Path, help='Zero-model tests only; completion is TEST_READY')
    a = p.parse_args(); root = a.output.resolve()
    if a.action == 'status':
        state = json.loads((root / 'state.json').read_text())
        state['workerAlive'] = alive(state.get('pid', 0)) if state.get('pid') else False
        print(json.dumps(state, ensure_ascii=False, indent=2)); return
    if a.action == 'run':
        raise SystemExit(run(root))
    if root.exists():
        p.error('Use a new output directory; preserve existing preparation evidence')
    if not all([a.spec, a.dataset, a.python]):
        p.error('start needs --spec, --dataset and --python')
    specpath = a.spec.resolve(); dataset = a.dataset.resolve(); interpreter = a.python.absolute()
    spec = json.loads(specpath.read_text())
    if sha(dataset) != spec['datasetSha256']:
        p.error('Dataset hash mismatch')
    cases=preparation_cases(spec)
    executor = a.fixture_executor.resolve() if a.fixture_executor else PROJECT / 'scripts/prepare-task-image.py'
    inputs = [specpath, Path(__file__).resolve(), executor]
    if not a.fixture_executor:
        inputs.append(PROJECT / 'scripts/probe-scorer.py')
    revision = subprocess.check_output(['git', '-C', str(PROJECT), 'rev-parse', 'HEAD'], text=True).strip()
    root.mkdir(parents=True); (root / 'logs').mkdir()
    freeze = {'specSha256': sha(specpath), 'dataset': str(dataset), 'datasetSha256': spec['datasetSha256'], 'python': str(interpreter), 'executor': str(executor), 'revision': revision, 'inputHashes': {str(v): sha(v) for v in inputs}, 'cases': cases, 'minimumFreeBytes': 15 * 1024**3, 'fixture': bool(a.fixture_executor), 'realModelRequests': 0, 'createdAt': time.time()}
    save(root / 'preparation.json', freeze)
    save(root / 'state.json', {'status': 'STARTING', 'completed': {}, 'current': None, 'pid': None, 'realModelRequests': 0})
    with (root / 'coordinator.log').open('ab') as log:
        worker = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), 'run', '--output', str(root)], stdout=log, stderr=subprocess.STDOUT, start_new_session=True, stdin=subprocess.DEVNULL)
    print(json.dumps({'pid': worker.pid, 'output': str(root), 'realModelRequests': 0}))

if __name__ == '__main__':
    main()
