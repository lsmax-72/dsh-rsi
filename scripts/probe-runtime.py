#!/usr/bin/env python3
"""Verify native assets and durable requests through an installed dsh, without API calls."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from fixture_embedding_server import EmbeddingFixtureServer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dsh', default=shutil.which('dsh') or '/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--probe',default='runtime-probe.mjs',choices=['runtime-probe.mjs','runtime-batch-probe.mjs','runtime-skill-window-probe.mjs'],help='Reuse the isolated native host for the selected fixture')
    args = parser.parse_args()
    cli = Path(args.dsh).expanduser().resolve()
    project = Path(__file__).resolve().parent.parent
    if not (project / 'lib/index.js').is_file():
        parser.error('Run npm run build first.')
    with tempfile.TemporaryDirectory(prefix='dsh-rsi-runtime-') as temp, EmbeddingFixtureServer() as embedding:
        root = Path(temp).resolve()
        env = dict(os.environ, DSH_HOME=str(root / 'home'), DSH_AGENTS_HOME=str(root / 'agents'))
        version = subprocess.run([str(cli), '--version'], env=env, cwd=root, capture_output=True, text=True, check=True, timeout=15)
        diagnostics = []
        for phase in ['extract', 'restore']:
            overlay = [
                {'id': 'sdk-app-startup', 'disabled': True},
                {'id': 'sdk-jsonrpc-server', 'disabled': True},
                {'id': 'llm-deepseek', 'disabled': True},
                {'insert': [
                    {'id':'rsi-typert', 'name':'@deepseek-ai/dsh-typert-registry'},
                    {'id':'rsi-gateway', 'name':'@deepseek-ai/dsh-api-gateway'},
                    {'id': 'rsi-host-skills', 'name': '@deepseek-ai/dsh-skill'},
                    {'id': 'rsi-host-tool-skill', 'name': '@deepseek-ai/dsh-tool-skill'},
                    {'id': 'rsi-integration', 'name': str(project / 'lib/index.js'), 'config': {
                        'embedding': embedding.config, 'dataDir': str(root / 'assets'), 'cwd': str(root), 'provider': 'rsi-probe', 'model': 'fixture', 'l2DelaySeconds': 86400,
                    }},
                    {'id': 'rsi-runtime-probe', 'name': str(project / 'scripts' / args.probe), 'config': {'root': str(root), 'phase': phase}},
                ]},
            ]
            patch = root / 'overlay.yml'
            patch.write_text(json.dumps(overlay, ensure_ascii=False), encoding='utf-8')
            process = subprocess.run([str(cli), '--profile', 'sdk-minimal', '--patch', str(patch)], env=env, cwd=root, capture_output=True, text=True, timeout=45)
            if process.returncode:
                raise SystemExit(f'{phase} failed:\n' + process.stdout + process.stderr)
            receipt = root / ('result.json' if phase == 'extract' else 'restored.json')
            if not receipt.is_file():
                raise SystemExit(f'{phase} produced no receipt:\n' + process.stdout + process.stderr)
            diagnostics.extend(process.stderr.strip().splitlines())
        result = json.loads((root / 'result.json').read_text())
        result['restart'] = json.loads((root / 'restored.json').read_text())
        assert result['status'] == result['restart']['status'] == 'PASS'
        result.update(hostVersion=version.stdout.strip(), checkedAt=datetime.now(timezone.utc).isoformat(), isolatedHome=True, diagnostics=diagnostics)
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding='utf-8')
    print(encoded, end='')


if __name__ == '__main__':
    main()
