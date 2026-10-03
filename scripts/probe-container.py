#!/usr/bin/env python3
"""Run official dsh tools and the existing RSI closure probe in isolated Linux containers."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def overlay(shell, sentinel):
    rows = [
        {'id': 'sdk-app-startup', 'disabled': True},
        {'id': 'sdk-jsonrpc-server', 'disabled': True},
        {'id': 'llm-deepseek', 'disabled': True},
        {'id': 'tools', 'config': {'mode': 'both'}},
    ]
    services = [
        ('rsi-registry', '@deepseek-ai/dsh-typert-registry', {}),
        ('rsi-gateway', '@deepseek-ai/dsh-api-gateway', {}),
        ('rsi-skills', '@deepseek-ai/dsh-skill', {}),
        ('rsi-tool-skill', '@deepseek-ai/dsh-tool-skill', {}),
        ('rsi-fs', '@deepseek-ai/dsh-fs-local', {'cwd': '/workspace'}),
        ('rsi-files', '@deepseek-ai/dsh-tool-fs', {}),
        ('rsi-search', '@deepseek-ai/dsh-tool-fs-search', {'sampleOverCapGlobResults': False}),
        ('rsi-ptc', '@deepseek-ai/dsh-ptc-runtime-node', {}),
        ('rsi', '/opt/rsi/lib/index.js', {'dataDir': '/state/assets', 'settings': {'learningEnabled': False}}),
        ('rsi-probe', '/opt/rsi/scripts/isolation-probe.mjs', {'shell': shell, 'sentinel': sentinel}),
    ]
    if shell == 'oneshot':
        rows.append({'id': 'persistent-bash', 'disabled': True})
        services.extend([
            ('rsi-shell', '@deepseek-ai/dsh-bash-local', {}),
            ('rsi-shell-env', '@deepseek-ai/dsh-shell-env', {}),
            ('rsi-bash', '@deepseek-ai/dsh-tool-bash', {'enableRunInBackground': False}),
        ])
    rows.append({'insert': [{'id': id_, 'name': name, 'config': config} for id_, name, config in services]})
    return rows


def run_container(image, command):
    # Only disposable tmpfs is writable; no bind, volume, socket, or host namespace is supplied.
    args = ['docker', 'create', '--init', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--cpus', '2', '--memory', '2g', '--pids-limit', '256',
            '--tmpfs', '/state:uid=1000,gid=1000,mode=700,size=256m',
            '--tmpfs', '/workspace:uid=1000,gid=1000,mode=700,size=64m',
            # The official native loader stages shared libraries here and needs executable mappings.
            '--tmpfs', '/tmp:rw,exec,uid=1000,gid=1000,mode=700,size=128m', image, *command]
    cid = subprocess.check_output(args, text=True).strip()
    try:
        facts = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
        host = facts['HostConfig']
        assert host['NetworkMode'] == 'none' and host['ReadonlyRootfs'] and not host['Privileged']
        assert not host['Binds'] and not host['PortBindings'] and not facts['Mounts']
        assert host['CapDrop'] == ['ALL'] and host['PidMode'] != 'host' and host['IpcMode'] != 'host'
        assert facts['Config']['User'] == 'node'
        output = subprocess.run(['docker', 'start', '-a', cid], capture_output=True, text=True, timeout=100)
        state = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]['State']
        if output.returncode or state['ExitCode'] or state['OOMKilled']:
            raise RuntimeError(output.stdout + output.stderr + '\n' + json.dumps(state))
        return output.stdout, {'network': 'none', 'rootfsReadOnly': True, 'uid': 1000, 'binds': [],
                               'capDrop': host['CapDrop'], 'memoryBytes': host['Memory'],
                               'nanoCpus': host['NanoCpus'], 'pidsLimit': host['PidsLimit']}
    finally:
        subprocess.run(['docker', 'rm', '-f', cid], check=True, stdout=subprocess.DEVNULL)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='dsh-rsi-container-check:local')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    with tempfile.TemporaryDirectory(prefix='dsh-rsi-container-') as tmp:
        root = Path(tmp)
        sentinel = root / 'host-only-marker'
        sentinel.write_text('must stay outside the container')
        for name in ['package.json', 'package-lock.json', 'cordis.patch.yml', 'scripts', 'src', 'adapters', 'vendor']:
            source, target = project / name, root / 'plugin' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
        shutil.copy2(project / 'scripts/container/Dockerfile', root / 'Dockerfile')
        for shell in ['persistent', 'oneshot']:
            (root / f'{shell}.json').write_text(json.dumps(overlay(shell, str(sentinel))))
        subprocess.run(['docker', 'build', '-t', args.image, str(root)], check=True)
        checks = []
        for shell in ['persistent', 'oneshot']:
            output, policy = run_container(args.image, ['dsh', '--profile', 'sdk-minimal', '--patch', f'/opt/rsi/scripts/{shell}.json'])
            receipt = next(json.loads(line) for line in output.splitlines() if line.startswith('{"status"'))
            assert receipt['status'] == 'PASS'
            checks.append(receipt)
        output, _ = run_container(args.image, ['python3', '/opt/rsi/scripts/probe-runtime.py', '--dsh', '/opt/dsh/node_modules/.bin/dsh'])
        native = json.loads(output)
        assert native['status'] == 'PASS' and native['realProviderRequests'] == 0
        assert sentinel.read_text() == 'must stay outside the container'
        image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', args.image], text=True))[0]
    result = {'status': 'PASS', 'checkedAt': datetime.now(timezone.utc).isoformat(), 'imageId': image['Id'],
              'hostVersion': native['hostVersion'], 'policy': policy, 'toolProbes': checks, 'nativeClosure': native,
              'limitation': 'No-network fixture only; real-model egress, official scoring and real tasks remain unverified.'}
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end='')


if __name__ == '__main__':
    main()
