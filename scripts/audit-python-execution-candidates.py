#!/usr/bin/env python3
"""Find saved Python executions missed by legacy inline-probe heuristics; no quality claim."""
import argparse,json,re,hashlib
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--diagnostics',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    data=json.loads(a.diagnostics.read_text());tasks=[]
    for task in data['tasks']:
        candidates=[]
        for command in task['commands']:
            if not re.search(r'\bpython(?:\d+(?:\.\d+)*)?\s+(?:-c\b|-(?:\s|$)|[^\n ;]+\.py\b)',command['command']):continue
            result=command.get('actualResult')
            candidates.append({'requestOrdinal':command['requestOrdinal'],'command':command['command'],'purposeDescription':command['purposeDescription'],'patchSha256':command['patchSha256'],'actualResult':result,'legacyInlineBehaviorProbe':command['inlineBehaviorProbe'],'legacyFrameworkTest':command['frameworkTest'],'legacyEnvironmentProbe':command['environmentProbe'],'classification':'PYTHON_EXECUTION_CANDIDATE_REQUIRES_REVIEW','limitation':'Execution may be environment/introspection/setup/behavior and may fail before reaching the intended test. It does not prove validation or quality.'})
        tasks.append({'instanceId':task['instanceId'],'arm':task['arm'],'pythonExecutionCandidates':candidates,'candidateCount':len(candidates),'legacyInlineBehaviorProbes':task['inlineBehaviorProbes']})
    out={'status':'OFFLINE_PYTHON_EXECUTION_CANDIDATES','diagnosticsSha256':hashlib.sha256(a.diagnostics.read_bytes()).hexdigest(),'tasks':tasks,'modelOrScorerCalls':0,'productionCodeOrAssetsChanged':False,'automaticQualityClaim':False,'limit':'A readonly candidate inventory. Intent/outcome review is required before counting behavior checks or repeated failures.'}
    with a.output.open('x') as f:f.write(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':out['status'],'tasks':len(tasks),'candidateCount':sum(t['candidateCount'] for t in tasks),'modelOrScorerCalls':0}))
if __name__=='__main__':main()
