#!/usr/bin/env python3
"""Run a model-free API probe through an installed official dsh profile."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    default_cli = shutil.which('dsh') or '/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh'
    parser.add_argument('--dsh', default=default_cli, help='Path to the official dsh CLI')
    parser.add_argument('--output', type=Path, help='Save the probe receipt as JSON')
    args = parser.parse_args()
    cli = Path(args.dsh).expanduser().resolve()
    if not cli.is_file():
        parser.error('The official dsh CLI was not found; provide --dsh.')
    module = Path(__file__).with_name('host-probe.mjs').resolve()
    # A separate home prevents loading personal profiles, credentials, or skills.
    with tempfile.TemporaryDirectory(prefix='dsh-rsi-host-probe-') as temporary:
        root = Path(temporary).resolve()
        env = dict(os.environ)
        env['DSH_HOME'] = str(root / 'home')
        env['DSH_AGENTS_HOME'] = str(root / 'agents')
        fixture = root / 'skills/rsi-probe/SKILL.md'
        fixture.parent.mkdir(parents=True)
        fixture.write_text('---\nname: rsi-probe\ndescription: 独立目录加载探针\n---\n\n版本一：接口验证。\n', encoding='utf-8')
        # A JSON array is valid YAML; generate paths without YAML quoting ambiguity.
        overlay = [
            {'id': 'sdk-app-startup', 'disabled': True},
            {'id': 'sdk-jsonrpc-server', 'disabled': True},
            {'id': 'llm-deepseek', 'disabled': True},
            {'insert': [
                {'id': 'rsi-probe-skills', 'name': '@deepseek-ai/dsh-skill'},
                {'id': 'rsi-probe-skill-files', 'name': '@deepseek-ai/dsh-skill-filesystem', 'config': {
                    'providerName': 'dsh-rsi-probe-files', 'includeDefaultRoots': False,
                    'customSkillDirs': [str(root / 'skills')], 'watch': False,
                }},
                {'id': 'rsi-probe', 'name': str(module), 'config': {'dataRoot': str(root)}},
            ]},
        ]
        patch = root / 'overlay.yml'
        patch.write_text(json.dumps(overlay, ensure_ascii=False, indent=2), encoding='utf-8')
        version = subprocess.run([str(cli), '--version'], env=env, cwd=root,
                                 capture_output=True, text=True, timeout=15, check=True)
        process = subprocess.run([str(cli), '--profile', 'sdk-minimal', '--patch', str(patch)],
                                 env=env, cwd=root, capture_output=True, text=True, timeout=30)
        if process.returncode != 0:
            raise SystemExit(process.stdout + process.stderr)
        receipt = root / 'result.json'
        if not receipt.is_file():
            raise SystemExit('No probe receipt was produced.\n' + process.stdout + process.stderr)
        result = json.loads(receipt.read_text(encoding='utf-8'))
        if result.get('status') != 'PASS' or result.get('modelCalls') != 0:
            raise SystemExit('The probe did not complete without model calls.')
        result['hostVersion'] = version.stdout.strip()
        result['checkedAt'] = datetime.now(timezone.utc).isoformat()
        result['isolatedHome'] = True
        result['taskCommandsExecuted'] = 0
        result['diagnostics'] = process.stderr.strip().splitlines()
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding='utf-8')
    print(encoded, end='')


if __name__ == '__main__':
    main()
