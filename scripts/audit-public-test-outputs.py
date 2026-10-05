#!/usr/bin/env python3
"""Read saved public execution outputs, including custom Python probes; no grading feedback."""
import argparse,json,re,hashlib
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--diagnostics',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();data=json.loads(a.diagnostics.read_text());tasks=[]
    for task in data['tasks']:
        observations=[]
        for command in task['commands']:
            python=bool(re.search(r'\bpython(?:\d+(?:\.\d+)*)?\s+(?:-c\b|-(?:\s|$)|[^\n ;]+\.py\b)',command['command']))
            if not (command['frameworkTest'] or python):continue
            result=command.get('actualResult');text=(result or {}).get('text','')
            failures=re.findall(r'(?m)^FAILED \([^\n]+\)',text);ok=re.findall(r'(?m)^OK(?: \([^\n]+\))?\s*$',text);mismatch=re.findall(r'(?m)^.*\bMISMATCH\s*->[^\n]*',text);exceptions=re.findall(r'(?m)^(?:[\w.]+Error|[\w.]+Exception):[^\n]*',text)
            all_ok=bool(re.search(r'(?m)^ALL OK\s*$',text));failure_present=bool(re.search(r'(?m)^FAILURES PRESENT\s*$',text))
            observations.append({'requestOrdinal':command['requestOrdinal'],'command':command['command'],'patchSha256':command['patchSha256'],'executionKind':'framework_candidate' if command['frameworkTest'] else 'custom_python_candidate','sourceResultMessageId':(result or {}).get('messageId'),'sourceEventSeq':(result or {}).get('eventSeq'),'failureSummaryLines':failures,'okaySummaryLines':[s.strip() for s in ok],'caseMismatchLines':mismatch,'printedAllOkay':all_ok,'printedFailuresPresent':failure_present,'exceptionLines':exceptions,'observedNonzeroExitCode':command['observedNonzeroExitCode'],'noRecognizedOutcome':not (failures or ok or mismatch or exceptions or all_ok or failure_present),'qualityConclusion':'NOT_ESTABLISHED_BY_OUTPUT_PARSING','limit':'Literal saved output only. Exceptions may be expected, setup can fail before the target, and printed success does not establish adequate coverage.'})
        tasks.append({'instanceId':task['instanceId'],'arm':task['arm'],'executionCandidateCommands':len(observations),'commandsWithFailureSummaries':sum(bool(o['failureSummaryLines']) for o in observations),'commandsWithOkaySummaries':sum(bool(o['okaySummaryLines']) for o in observations),'commandsWithCaseMismatches':sum(bool(o['caseMismatchLines']) for o in observations),'observations':observations})
    out={'status':'OFFLINE_PUBLIC_EXECUTION_OUTPUT_AUDIT','sourceDiagnosticsSha256':hashlib.sha256(a.diagnostics.read_bytes()).hexdigest(),'tasks':tasks,'modelOrScorerCalls':0,'originalLogsOrAssetsChanged':False,'fixedDiagnosticRubricChanged':False,'qualityOrCausalityClaim':False}
    with a.output.open('x') as f:f.write(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':out['status'],'savedArms':len(tasks),'modelOrScorerCalls':0}))
if __name__=='__main__':main()
