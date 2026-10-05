#!/usr/bin/env python3
"""Inventory saved foreground log lookups; path mentions do not prove useful recall."""
import argparse, collections, hashlib, json, re
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    runs_path = args.root / 'runs.json'
    tasks = []
    for run in json.loads(runs_path.read_text()):
        assert run['status'] == 'CLOSED_GRADED'
        pilot = Path(run['runDir']) / 'state/pilot' / run['instanceId']
        requests_path = pilot / 'model-requests.json'
        tools_path = pilot / 'tool-results.json'
        requests = [r for r in json.loads(requests_path.read_text()) if r['phase'] == 'task']
        session_ids = {r['sessionId'] for r in requests}
        delivered = {m.get('toolCallId') for r in requests for m in r['messages'] if m.get('toolCallId')}
        # Persisted source messages identify actual output, including failed/empty lookups.
        outputs = {}
        for source in (Path(run['runDir']) / 'state/home/sessions').rglob('session.v4.jsonl'):
            for line in source.read_text().splitlines():
                event = json.loads(line)
                if event['type'] == 'tool/result':
                    m = event['data']['message']
                    outputs[m['toolCallId']] = {'sourceMessageId': m['id'], 'sourceEventSeq': event['seq'], 'text': '\n'.join(b.get('text', '') for b in m.get('content', []) if b.get('type') == 'text')}
        lookups = []
        for tool in json.loads(tools_path.read_text()):
            if tool['phase'] != 'task':
                continue
            raw = json.dumps(tool['args'], ensure_ascii=False)
            if '/sessions' not in raw and 'session.v4.jsonl' not in raw:
                continue
            named = sorted(set(re.findall(r'pilot-django__django-\d+-task|rsi-[a-f0-9-]{36}', raw)))
            output = outputs.get(tool['callId'])
            lookups.append({'requestOrdinal': tool['requestOrdinal'], 'toolName': tool['name'], 'callId': tool['callId'], 'args': tool['args'], 'explicitCurrentSessionTargets': sorted(session_ids.intersection(named)), 'explicitOtherSessionTargets': sorted(set(named) - session_ids), 'resultDeliveredToLaterTaskRequest': tool['callId'] in delivered, 'toolIsError': tool['isError'], 'actualResult': output, 'interpretation': 'Named targets may be directory listings, probes or failed reads. Wildcards may include current and prior logs; neither path mentions nor delivery establishes useful recall.'})
        tasks.append({'instanceId': run['instanceId'], 'arm': run['arm'], 'foregroundSessionIds': sorted(session_ids), 'hasPreviousOwnState': bool(run.get('previousOwnState')), 'requestFileSha256': hashlib.sha256(requests_path.read_bytes()).hexdigest(), 'toolFileSha256': hashlib.sha256(tools_path.read_bytes()).hexdigest(), 'foregroundToolCounts': dict(collections.Counter(t['name'] for t in json.loads(tools_path.read_text()) if t['phase'] == 'task')), 'logLookupCommands': len(lookups), 'explicitCurrentTargetCommands': sum(bool(x['explicitCurrentSessionTargets']) for x in lookups), 'explicitOtherTargetCommands': sum(bool(x['explicitOtherSessionTargets']) for x in lookups), 'lookups': lookups})
    result = {'status': 'SAVED_FOREGROUND_SESSION_LOOKUP_AUDIT', 'sourceRunsSha256': hashlib.sha256(runs_path.read_bytes()).hexdigest(), 'tasks': tasks, 'modelOrScorerCalls': 0, 'frozenMethodsOrAssetsChanged': False, 'causalityClaim': False}
    with args.output.open('x') as f:
        f.write(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'arms': len(tasks), 'lookups': sum(t['logLookupCommands'] for t in tasks), 'modelOrScorerCalls': 0}))

if __name__ == '__main__':
    main()
