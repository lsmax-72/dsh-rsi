#!/usr/bin/env python3
"""Offline paired accuracy summary; resample users, never correlated questions as independent units."""
import argparse,json,math,random,statistics
from pathlib import Path

def paired_user_summary(data,draws=10000,seed=20261004):
    planned=data['plannedUserIds'];rows=data['users']
    if not planned or len(set(planned))!=len(planned):raise ValueError('Planned user IDs must be nonempty and unique')
    if len({r['personaId'] for r in rows})!=len(rows) or {r['personaId'] for r in rows}!=set(planned):raise ValueError('Do not duplicate or omit planned users')
    if draws<1000:raise ValueError('At least 1000 fixed bootstrap draws are required')
    users=[];incomplete=[]
    for row in rows:
        expected=row['expectedQuestionIds']
        if not expected or len(set(expected))!=len(expected):raise ValueError('Question IDs must be nonempty and unique per user')
        arms={}
        for arm in ['baseline','rsi']:
            observed=row[arm];mapping={q['questionId']:q['correct'] for q in observed}
            if len(mapping)!=len(observed) or not set(mapping)<=set(expected):raise ValueError('Unexpected or duplicate question score')
            if any(type(v) is not bool for v in mapping.values()):raise ValueError('Missing outcomes must not be cast to wrong answers')
            if set(mapping)!=set(expected):incomplete.append({'personaId':row['personaId'],'arm':arm,'missingQuestions':sorted(set(expected)-set(mapping))})
            arms[arm]=mapping
        if all(len(arms[a])==len(expected) for a in arms):
            users.append({'personaId':row['personaId'],'questionCount':len(expected),'baselineAccuracy':statistics.mean(arms['baseline'].values()),'rsiAccuracy':statistics.mean(arms['rsi'].values())})
    result={'plannedUsers':len(planned),'completePairedUsers':len(users),'incomplete':incomplete,'perUser':users,'macroAccuracyDifference':None,'confidenceInterval95':None,'bootstrapUnit':'user','draws':draws,'seed':seed,'completionIsNotCorrectness':True}
    if incomplete:
        result['limitation']='Paired estimates withheld: do not silently exclude planned users missing answers.';return result
    differences=[u['rsiAccuracy']-u['baselineAccuracy'] for u in users];result.update(macroBaselineAccuracy=statistics.mean(u['baselineAccuracy'] for u in users),macroRsiAccuracy=statistics.mean(u['rsiAccuracy'] for u in users),macroAccuracyDifference=statistics.mean(differences))
    if len(users)<2:
        result['limitation']='One user supplies no across-user uncertainty estimate.';return result
    rng=random.Random(seed);samples=sorted(statistics.mean(rng.choices(differences,k=len(differences))) for _ in range(draws))
    result['confidenceInterval95']=[samples[math.ceil(.025*draws)-1],samples[math.ceil(.975*draws)-1]]
    result['method']='Paired user-cluster percentile bootstrap, inverse empirical CDF; macro accuracy difference.'
    result['limitation']='Small user counts produce coarse sample-dependent intervals, not population or repeated-model-run coverage guarantees.'
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--draws',type=int,default=10000);p.add_argument('--seed',type=int,default=20261004);args=p.parse_args()
    if args.output.exists():p.error('Preserve previous reports')
    result=paired_user_summary(json.loads(args.input.read_text()),args.draws,args.seed);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
if __name__=='__main__':main()
