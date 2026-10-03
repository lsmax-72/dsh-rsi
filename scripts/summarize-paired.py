#!/usr/bin/env python3
"""Summarize saved official outcomes and request usage. No model or scorer is executed."""
import argparse
import hashlib
import json
import random
import statistics
from pathlib import Path


def usage(rows,unavailable=0):
    result={'requests':len(rows),'usageUnavailableRuns':unavailable}
    for key in ['inputTokens','outputTokens','totalTokens']:
        values=[(r.get('usage') or {}).get(key) for r in rows]
        if any(v is not None and (type(v) is not int or v<0) for v in values): raise ValueError('Invalid usage '+key)
        missing=sum(v is None for v in values)
        known=sum(v for v in values if v is not None)
        result[key]=known if not missing and not unavailable else None
        result['known'+key[0].upper()+key[1:]]=known
        result['missing'+key[0].upper()+key[1:]]=missing
    return result


def read_run(record):
    root=Path(record['runDir']) if record.get('runDir') else None
    requests=json.loads((root/'model-requests.json').read_text()) if root and (root/'model-requests.json').is_file() else None
    if requests is None and root and (root/'failure.json').exists():
        saved=json.loads((root/'failure.json').read_text()).get('requests')
        if isinstance(saved,list): requests=saved
    foreground=[r for r in requests or [] if not r['sessionId'].startswith('rsi-')]
    learning=[r for r in requests or [] if r['sessionId'].startswith('rsi-')]
    grade=None
    if record.get('grading'):
        grade=json.loads(Path(record['grading']).read_text())
        if grade['instanceId']!=record['instanceId']: raise ValueError('Grade/task mismatch')
        if type(grade['resolved']) is not bool: raise ValueError('Resolved must be a bool from the saved report')
        patch=(root/'prediction.patch').read_bytes()
        if grade.get('patchSha256')!=hashlib.sha256(patch).hexdigest(): raise ValueError('Grade/patch mismatch')
        if not grade.get('officialReport') or grade['officialReport'][record['instanceId']]['resolved']!=grade['resolved']:
            raise ValueError('Missing or inconsistent official report')
    if record['arm']=='baseline' and any(m.get('source',{}).get('kind')=='dsh-rsi' for r in foreground for m in r.get('messages',[])): raise ValueError('Baseline has RSI memory injection')
    classification=record.get('classification','UNCLASSIFIED' if grade is None else 'GRADED')
    if classification not in ['GRADED','INFRA','UNCLASSIFIED']: raise ValueError('Invalid outcome classification')
    if (classification=='GRADED') != (grade is not None): raise ValueError('Official grade conflicts with run classification')
    receipt=json.loads((root/'receipt.json').read_text()) if root and (root/'receipt.json').exists() else {}
    stop=receipt.get('phases',receipt.get('stopReason'))
    if stop is None and record.get('sourceSessionFile'):
        header,*events=[json.loads(line) for line in Path(record['sourceSessionFile']).read_text().splitlines()]
        if header['id'] not in {r['sessionId'] for r in foreground}: raise ValueError('Source session/request mismatch')
        stop=next((e['data']['reason'] for e in reversed(events) if e['type']=='turn/end'),None)
    return {'instanceId':record['instanceId'],'arm':record['arm'],'stage':record['stage'],'attempt':record.get('attempt',0),
        'classification':classification,
        'resolved':grade['resolved'] if grade else None,
        'stopReasons':stop,
        'requests':requests,'foreground':foreground,'learning':learning,'usageUnavailable':requests is None}


def summarize(manifest,records):
    ids={stage:[r['instanceId'] for r in manifest[key]] for stage,key in [('prefix','prefix'),('heldOut','heldOut')]}
    all_ids=ids['prefix']+ids['heldOut']
    if len(all_ids)!=len(set(all_ids)) or not ids['heldOut']: raise ValueError('Invalid fixed task manifest')
    runs=[read_run(r) for r in records];groups={}
    for run in runs:
        if run['arm'] not in ['baseline','rsi'] or run['stage'] not in ids or run['instanceId'] not in ids[run['stage']]: raise ValueError('Run outside fixed manifest')
        groups.setdefault((run['stage'],run['instanceId'],run['arm']),[]).append(run)
    selected={}
    for key,attempts in groups.items():
        attempts.sort(key=lambda r:r['attempt'])
        if [r['attempt'] for r in attempts]!=list(range(len(attempts))) or len(attempts)>2: raise ValueError('Invalid retry sequence')
        if len(attempts)==2 and (attempts[0]['classification']!='INFRA' or attempts[0]['resolved'] is not None): raise ValueError('Only confirmed ungraded INFRA may be retried')
        selected[key]=attempts[-1]
    n=len(ids['heldOut']);arms={}
    for arm in ['baseline','rsi']:
        outcomes=[selected.get(('heldOut',id_,arm),{}).get('resolved') for id_ in ids['heldOut']]
        arm_runs=[r for r in runs if r['arm']==arm]
        if arm=='baseline' and any(r['learning'] for r in arm_runs): raise ValueError('Baseline contains RSI learning requests')
        costs={}
        for stage in ['prefix','heldOut']:
            subset=[r for r in arm_runs if r['stage']==stage]
            missing_stage=sum((stage,id_,arm) not in groups for id_ in ids[stage])
            costs[stage]={phase:usage([row for r in subset for row in r[phase]],sum(r['usageUnavailable'] for r in subset)+missing_stage) for phase in ['foreground','learning']}
        absent=sum((stage,id_,arm) not in groups for stage in ids for id_ in ids[stage])
        total=usage([row for r in arm_runs for row in r['requests'] or []],sum(r['usageUnavailable'] for r in arm_runs)+absent)
        successes=sum(v is True for v in outcomes);missing=sum(v is None for v in outcomes)
        total_value=total['totalTokens']
        learning_costs=[costs[s]['learning']['totalTokens'] for s in ids]
        learning_total=sum(learning_costs) if all(v is not None for v in learning_costs) and not absent else None
        task_costs=[]
        for id_ in ids['heldOut']:
            case=groups.get(('heldOut',id_,arm),[])
            task_costs.append(usage([row for r in case for row in r['foreground']],sum(r['usageUnavailable'] for r in case)+(not case))['totalTokens'])
        stats={'mean':statistics.mean(task_costs),'median':statistics.median(task_costs)} if all(v is not None for v in task_costs) else {'mean':None,'median':None}
        arms[arm]={'heldOutForegroundTokenStats':stats,'plannedHeldOut':n,'resolved':successes,'unresolved':sum(v is False for v in outcomes),
            'missingOutcomes':missing,'successRate':successes/n if not missing else None,
            'successRateBounds':[successes/n,(successes+missing)/n],
            'usageByStage':costs,'allAttemptsUsage':total,'missingPlannedRuns':absent,
            'learningTokensPerPlannedHeldOut':learning_total/n if learning_total is not None else None,
            'tokensPerHeldOutSuccess':total_value/successes if total_value is not None and not missing and successes else None}
    pairs=[]
    for id_ in ids['heldOut']:
        a=selected.get(('heldOut',id_,'baseline'),{}).get('resolved');b=selected.get(('heldOut',id_,'rsi'),{}).get('resolved')
        pair_costs={}
        for arm in ['baseline','rsi']:
            case=groups.get(('heldOut',id_,arm),[])
            pair_costs[arm]=usage([row for r in case for row in r['foreground']],sum(r['usageUnavailable'] for r in case)+(not case))['totalTokens']
        cost_delta=pair_costs['rsi']-pair_costs['baseline'] if all(v is not None for v in pair_costs.values()) else None
        pairs.append({'foregroundTokens':pair_costs,'foregroundTokenDelta':cost_delta,'instanceId':id_,'baseline':a,'rsi':b,'complete':a is not None and b is not None})
    complete=[p for p in pairs if p['complete']]
    gain=sum(p['rsi'] and not p['baseline'] for p in complete);loss=sum(p['baseline'] and not p['rsi'] for p in complete)
    totals=[arms[a]['allAttemptsUsage']['totalTokens'] for a in ['baseline','rsi']]
    delta=totals[1]-totals[0] if all(v is not None for v in totals) else None
    interval=None
    if len(complete)==n:
        differences=[int(p['rsi'])-int(p['baseline']) for p in complete]
        rng=random.Random(0)
        samples=sorted(sum(rng.choices(differences,k=n))/n for _ in range(10000))
        interval={'method':'paired-task-percentile-bootstrap','seed':0,'resamples':10000,'confidence':0.95,'low':samples[249],'high':samples[9749],'scope':'Task resampling only; does not estimate repeated-model variability.'}
    return {'status':'COMPLETE_SAVED_RESULTS' if len(complete)==n and all(not arms[a]['missingPlannedRuns'] for a in arms) else 'INCOMPLETE_SAVED_RESULTS',
        'startedModelOrScorer':False,'plannedPairs':n,'completePairs':len(complete),
        'newlyResolvedKnownPairs':gain,'newlyFailedKnownPairs':loss,
        'netResolvedDifference':gain-loss if len(complete)==n else None,'successRateDifferenceInterval':interval,
        'allChainTokenDelta':delta,'allChainTokenRelativeDelta':delta/totals[0] if delta is not None and totals[0] else None,
        'arms':arms,'pairs':pairs,'attempts':[{k:v for k,v in r.items() if k not in ['requests','foreground','learning']} for r in runs],
        'interpretation':'Incomplete pairs or usage are not imputed as failures or zero cost; retries remain in total cost.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--runs',type=Path,required=True,help='JSON list with instanceId,stage,arm,attempt,runDir,grading and classification')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.resolve() in [args.manifest.resolve(),args.runs.resolve()] or args.output.exists(): parser.error('Do not overwrite inputs or prior summaries')
    result=summarize(json.loads(args.manifest.read_text()),json.loads(args.runs.read_text()))
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['arms','pairs','attempts']},ensure_ascii=False))


if __name__=='__main__':main()
