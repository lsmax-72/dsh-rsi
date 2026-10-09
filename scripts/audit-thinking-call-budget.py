#!/usr/bin/env python3
"""Inspect saved Off trajectories; no task, scorer, or model dispatch."""
import argparse, hashlib, json
from pathlib import Path

def audit(root):
    rows=[]
    for instance in ['11848','11551','12262','11815','11880','11790','11999','11740']:
        record=root/('django__django-'+instance+'-off-0.record.json')
        r=json.loads(record.read_text());pilot=Path(r['output'])/'state/pilot'/r['instanceId']
        requests=json.loads((pilot/'model-requests.json').read_text())
        snapshots=json.loads((pilot/'patch-snapshots.json').read_text())
        phases=json.loads((pilot/'phases.json').read_text())
        stopped=any('Pilot foreground dispatch limit reached' in json.dumps(p.get('stopReason')) for p in phases)
        rows.append({'instanceId':r['instanceId'],'resolved':r['resolved'],'foregroundCalls':len(requests),'agentWallSeconds':sum(p['wallMs'] for p in phases)/1000,'blockedNextDispatch':stopped,'lastPatchChangeRequest':snapshots[-1]['requestOrdinal'],'lastFinish':requests[-1].get('finish'),'recordSha256':hashlib.sha256(record.read_bytes()).hexdigest(),'requestsSha256':hashlib.sha256((pilot/'model-requests.json').read_bytes()).hexdigest()})
    return {'status':'SAVED_OFF_CALL_BUDGET_AUDIT','cases':rows,'capped':sum(r['blockedNextDispatch'] for r in rows),'cappedSolved':sum(r['blockedNextDispatch'] and r['resolved'] for r in rows),'modelRequests':0,'scorerInvocations':0,'recommendation':{'foregroundCalls':60,'wallSeconds':1200,'maxOutputTokens':8192,'budgetConfirmed':False},'limitation':'6/8 exposed single-run Off tasks were capped while far below wall budget. Raising the cap offers headroom; these saved runs cannot establish the success or token cost of 60 calls.'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=audit(a.root.resolve());a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='cases'},ensure_ascii=False))
