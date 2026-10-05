#!/usr/bin/env python3
"""Find saved framework invocation repeats after removing output-only pipelines."""
import argparse, collections, hashlib, json, re, shlex
from pathlib import Path

def invocations(command):
    # The recorded patch is after the tool call, so an in-call revert cannot identify tested state.
    if re.search(r'\bgit\s+(?:stash|checkout|restore|reset|revert|apply)\b', command):
        return [], 'workspace_mutated_inside_command'
    try:
        tokens = list(shlex.shlex(command, posix=True, punctuation_chars=';&|<>'))
    except ValueError:
        return [], 'shell_lexing_failed'
    result = []
    for i, token in enumerate(tokens):
        if not re.fullmatch(r'python(?:\d+(?:\.\d+)*)?', token):
            continue
        tail = tokens[i + 1:]
        if not tail or not (tail[0].endswith('runtests.py') or tail[:2] in [['-m', 'pytest'], ['-m', 'unittest']]):
            continue
        args = [token]
        for arg in tail:
            if any(c in arg for c in ';&|<>'):
                # shlex emits the fd number as a separate token for 2>&1.
                if '>' in arg and args[-1] == '2':
                    args.pop()
                break
            args.append(arg)
        if any(a in args for a in ['-h', '--help', '--collect-only']):
            continue
        result.append(args)
    return result, None

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--diagnostics', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    data = json.loads(args.diagnostics.read_text())
    tasks = []
    for task in data['tasks']:
        groups = collections.defaultdict(list)
        exclusions = []
        for command in task['commands']:
            if not command['frameworkTest']:
                continue
            found, reason = invocations(command['command'])
            if reason:
                exclusions.append({'requestOrdinal': command['requestOrdinal'], 'reason': reason})
            for argv in found:
                key = (json.dumps(argv), command['patchSha256'])
                observed = command.get('actualResult') or {}
                groups[key].append({'requestOrdinal': command['requestOrdinal'], 'command': command['command'], 'sourceMessageId': observed.get('messageId'), 'sourceEventSeq': observed.get('eventSeq'), 'literalOutcomeExcerpt': observed.get('text', '')[-900:]})
        repeated = [{'frameworkArgv': json.loads(k[0]), 'recordedPatchSha256': k[1], 'invocationCandidates': len(v), 'observations': v} for k, v in groups.items() if len(v) > 1]
        tasks.append({'instanceId': task['instanceId'], 'arm': task['arm'], 'repeatCandidatesAtSameRecordedPatch': sum(g['invocationCandidates'] - 1 for g in repeated), 'repeatGroups': repeated, 'excludedInCallWorkspaceMutationsOrParsing': exclusions})
    out = {'status': 'OFFLINE_FRAMEWORK_REPEAT_CANDIDATES', 'sourceDiagnosticsSha256': hashlib.sha256(args.diagnostics.read_bytes()).hexdigest(), 'tasks': tasks, 'modelOrScorerCalls': 0, 'frozenMethodsOrAssetsChanged': False, 'limitations': ['Invocation arguments and recorded post-call workspace patches match; output-only tail/grep differences are removed.', 'In-call stash/checkout/restore commands are excluded because post-call patch does not establish the tested state.', 'Shell conditional commands are invocation candidates; selection, environment, untracked files and test side effects may differ.', 'Re-running to obtain fuller failure output may be purposeful. These are candidates for review, not counts of avoidable tests or causal waste.']}
    with args.output.open('x') as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'arms': len(tasks), 'repeatCandidates': {a: sum(t['repeatCandidatesAtSameRecordedPatch'] for t in tasks if t['arm'] == a) for a in ['baseline', 'rsi']}}))

if __name__ == '__main__':
    main()
