#!/usr/bin/env python3
"""Offline original scorer over saved snapshots; no outputs flow back to task state."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ['root','dataset','scorer-python','project']:p.add_argument('--'+n,type=Path,required=True)
 args=p.parse_args();freeze=json.loads((args.root/'freeze.json').read_text());assert sha(args.dataset)==freeze['datasetSha256'];rows=json.loads((args.root/'runs.json').read_text());assert len(rows)==16 and all(r['status']=='CLOSED_GRADED' for r in rows),'Only after the fixed sequence ends'
 for r in rows:
  run=Path(r['runDir']);instance=r['instanceId'];case=next(c for c in freeze['cases'] if c['instanceId']==instance);env=case['environment'];assert subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',env['scorerKey']],text=True).strip()==env['scorerImage'];pilot=run/'state/pilot'/instance;final=json.loads(Path(r['grading']).read_text());snapshots=json.loads((pilot/'patch-snapshots.json').read_text());requests=json.loads((pilot/'model-requests.json').read_text());front=[q for q in requests if q['phase']=='task'];checks=[];seen=set();first=None
  out=run/'snapshot-grader-only';out.mkdir(exist_ok=True)
  for s in snapshots:
   if not s['nonempty'] or s['sha256'] in seen:continue
   seen.add(s['sha256']);prediction=pilot/'patch-snapshots'/(s['sha256']+'.patch');assert sha(prediction)==s['sha256']
   if s['sha256']==final['patchSha256']:score=final;grade=Path(r['grading']);method='reuse identical final patch and frozen official environment'
   else:
    grade=out/(s['sha256']+'.json');method='official grading of saved original snapshot'
    if not grade.exists():
     with (out/(s['sha256']+'.log')).open('w') as log:code=subprocess.run([str(args.scorer_python),'-B',str(args.project/'scripts/score-prediction.py'),'--dataset',str(args.dataset),'--instance',instance,'--prediction',str(prediction),'--work-dir',str(out/s['sha256']),'--output',str(grade)],cwd=args.project,stdout=log,stderr=subprocess.STDOUT).returncode
     assert code==0,'Missing official report; retain attempts and stop without retry'
    score=json.loads(grade.read_text());assert score['patchSha256']==s['sha256'] and type(score['resolved']) is bool
   assert subprocess.check_output(['docker','image','inspect','--format','{{.Id}}',env['scorerKey']],text=True).strip()==env['scorerImage']
   checks.append({'snapshot':s,'resolved':score['resolved'],'grading':str(grade),'method':method})
   if score['resolved']:
    consumed=front[:s['requestOrdinal']];first={'requestOrdinal':s['requestOrdinal'],'patchSha256':s['sha256'],'observedAt':s['observedAt'],'cumulativeForegroundKnownTokens':sum(q['usage']['totalTokens'] for q in consumed if q.get('usage')),'unknownActualUsageBeforeSnapshot':sum(not q.get('usage') for q in consumed),'allEarlierUniqueNonemptySavedSnapshotsOfficiallyChecked':True};break
  report={'status':'OFFLINE_FIRST_EFFECTIVE_SAVED_SNAPSHOT_DIAGNOSTIC','instanceId':instance,'arm':r['arm'],'firstEffectiveSnapshot':first,'checks':checks,'modelRequests':0,'scoresReturnedToLearning':False,'limitation':'Earliest passing observed saved patch, not an unobserved filesystem moment. Final score and all earlier snapshot grades are isolated from learner state.'};(run/'first-effective-snapshot.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='checks'}),flush=True)
if __name__=='__main__':main()
