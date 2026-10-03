#!/usr/bin/env python3
"""Audit saved two-task pilot evidence without executing tools or calling a model."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--grading', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    grading = read(args.grading)
    cases = []
    for grade in grading['cases']:
        root = args.results / grade['instanceId']
        receipt = read(root / 'receipt.json')
        events = read(root / 'source-events.json')
        requests = read(root / 'model-requests.json')
        assets = read(root / 'assets.json')
        reason = next(e['data']['reason'] for e in reversed(events) if e['type'] == 'turn/end')
        assert reason == receipt['stopReason']
        assert len(requests) == receipt['taskDispatches'] + receipt['backgroundDispatches']
        assert (root / 'prediction.patch').stat().st_size == receipt['patchBytes'] == grade['patchBytes']
        # Preserve the raw receipt, but never equate process success with task success.
        status = {'completed': 'TURN_COMPLETED', 'max-tokens': 'TOKEN_LIMIT', 'aborted': 'ABORTED'}.get(reason['kind'], 'TURN_FAILED')
        calls = [e['data'] for e in events if e['type'] == 'tool/call']
        usage = {key: sum(r.get('usage', {}).get(key, 0) for r in requests)
                 for key in ['inputTokens', 'outputTokens', 'totalTokens']}
        probes = [c for c in calls if 'golden' in c.get('arguments', '') or 'reflog' in c.get('arguments', '')]
        cases.append({
            'instanceId': grade['instanceId'], 'status': status,
            'rawReceiptStatus': receipt['status'], 'stopReason': reason,
            'taskDispatches': receipt['taskDispatches'], 'backgroundDispatches': receipt['backgroundDispatches'],
            'patchBytes': receipt['patchBytes'], 'before': receipt['before'], 'after': receipt['after'],
            'memoryInjections': receipt['memoryInjections'], 'skillLoads': receipt['skillLoads'],
            'toolCalls': dict(Counter(c['name'] for c in calls)), 'artifactSearchAttempts': len(probes),
            'usage': usage, 'missingUsageRequests': sum('usage' not in r for r in requests),
            'logReconstructionMatches': receipt['logReconstructionMatches'], 'grading': grade,
            'generatedSkills': [{'name': s['head']['name'], 'version': s['head']['version'],
                                 'contentSha256': hashlib.sha256(s['head']['content'].encode()).hexdigest()}
                                for s in assets['skills']],
            'evidenceSha256': {name: digest(root / name) for name in
                              ['receipt.json', 'source-events.json', 'model-requests.json', 'prediction.patch', 'assets.json']},
        })
    gateway = [json.loads(line) for line in (args.results / 'gateway.log').read_text().splitlines() if line.strip()]
    dispatches = sum(c['taskDispatches'] + c['backgroundDispatches'] for c in cases)
    assert len(gateway) == dispatches and [g['request'] for g in gateway] == list(range(1, dispatches + 1))
    output = {
        'status': 'INTEGRATION_INCOMPLETE', 'provider': 'qwen', 'model': 'qwen3.8-27b',
        'pairedBenchmarkStarted': False, 'resolved': sum(c['grading']['resolved'] for c in cases),
        'tasks': len(cases), 'gatewayRequests': len(gateway), 'loggedDispatches': dispatches,
        'usage': {k: sum(c['usage'][k] for c in cases) for k in ['inputTokens', 'outputTokens', 'totalTokens']},
        'assetConsumptionInRealFollowup': 'UNPROVEN', 'cases': cases,
        'limitation': 'Two integration attempts only. No baseline, no paired comparison, no product-effect claim. ERROR tests are preserved in the official report; the pinned official parser omits their entries.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in output.items() if k != 'cases'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
