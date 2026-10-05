#!/usr/bin/env python3
"""Audit previously registered but unexecuted cases; preserve exact inputs, never retry old cases."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 project=Path(__file__).resolve().parent.parent;root=args.output.resolve();assert not root.exists(),'Preserve every preparation';studies=[];cases=[];source_cases=[];started=set();keys={};budgets=None;provenance=None;official=None
 for name in ['personamem-independent-20261004','personamem-fresh-independent-20261004']:
  old=project/'.artifacts'/name;freeze=json.loads((old/'freeze.json').read_text());records=json.loads((old/'runs.json').read_text());known={c['personaId'] for c in freeze['cases']};users=[];hashes={str(p.relative_to(project)):sha(p) for p in [old/'freeze.json',old/'runs.json',old/'results.json']}
  assert all(r['personaId'] in known for r in records)
  if budgets is None:budgets=freeze['budgets']
  assert budgets==freeze['budgets']
  if freeze.get('datasetProvenance'):provenance=freeze['datasetProvenance']
  for path,digest in freeze['scorerInputSha256'].items():assert sha(Path(path))==digest
  scorer_path=next(Path(p) for p in freeze['scorerInputSha256'] if Path(p).name=='answers.json');answers=json.loads(scorer_path.read_text())
  current_official=next(Path(p) for p in freeze['scorerInputSha256'] if Path(p).name=='inference_standalone_openai.py')
  if official is None:official=current_official
  assert sha(official)==sha(current_official)
  for case in freeze['cases']:
   uid=case['personaId'];public=old/'public'/('persona-'+uid+'.json');assert sha(public)==case['publicInputSha256'];hashes[str(public.relative_to(project))]=sha(public);records_user=[r for r in records if r['personaId']==uid];wire_count=0;stream_count=0;traces=[]
   for arm in ['baseline','rsi']:
    folder=old/('persona-'+uid+'-'+arm)
    if folder.exists():
     traces.append(folder.name);gateway=folder/'gateway.log';native=folder/'state/pilot'/('persona-'+uid)/'model-requests.json'
     assert gateway.exists() and native.exists(),'Missing original dispatch evidence'
     for path in [gateway,native]:hashes[str(path.relative_to(project))]=sha(path)
     wire=[json.loads(line) for line in gateway.read_text().splitlines() if line.strip()];requests=json.loads(native.read_text());count=sum(bool(r.get('request') and r.get('model')) for r in wire);assert count==len(requests);wire_count+=count;stream_count+=len(requests)
     assert any(r['arm']==arm for r in records_user),'Unregistered native run artifact'
    runner=old/('persona-'+uid+'-'+arm+'.runner.log')
    if runner.exists():traces.append(runner.name)
   users.append({'personaId':uid,'priorRegistered':True,'nativeRecords':len(records_user),'actualGatewayCalls':wire_count,'nativeStreamEntries':stream_count,'runArtifacts':traces,'publicInputSha256':case['publicInputSha256']})
   if records_user:started.add(uid)
   else:
    assert not traces and wire_count==0 and stream_count==0
    # Selection is completed without inspecting answer values; scorer lookup follows fixed prior case IDs.
    cases.append(case);source_cases.append({'study':name,**case});keys.update({qid:answers[qid] for qid in case['questionIds']})
  for arm in ['baseline','rsi']:
   for folder in old.glob('persona-*-'+arm):assert folder.name[len('persona-'):-len('-'+arm)] in known
  studies.append({'study':name,'freezeSha256':sha(old/'freeze.json'),'users':users,'actualGatewayCalls':sum(u['actualGatewayCalls'] for u in users),'preservationHashes':hashes})
 assert [c['personaId'] for c in cases]==['9','4','12','14','3','17','19','15'] and len(keys)==32 and provenance
 root.mkdir(parents=True);(root/'public').mkdir();(root/'scorer').mkdir()
 for source in source_cases:
  public=project/'.artifacts'/source['study']/'public'/('persona-'+source['personaId']+'.json');(root/'public'/public.name).write_bytes(public.read_bytes());assert sha(root/'public'/public.name)==source['publicInputSha256']
 (root/'scorer/answers.json').write_text(json.dumps(keys,indent=2)+'\n')
 audit={'status':'AUDITED_PREPARED_NOT_FROZEN_NOT_DISPATCHED','checkedAt':datetime.now(timezone.utc).isoformat(),'studies':studies,'unusedPriorRegisteredCases':source_cases,'selectionBasis':'No native run record, no task-arm directory or runner log, no wire/native dispatch in either preserved cohort. Preserve prior question IDs, cutoffs and exact public bytes; no answer or outcome used for selection.','populationPolicyChange':'Allow prior-registered unexecuted users rather than excluding all frozen users. Not never-registered users; no failed case retried or replaced in its original cohort.','scope':'The two preserved cohorts only; public data is not secret, model-training exposure cannot be proved absent.','newRealModelRequests':0}
 proposal=json.loads((project/'docs/evidence/personamem-fresh-proposal-20261004.json').read_text());proposal.pop('coding',None);proposal.update(status='PREPARED_UNUSED_REGISTERED_USERS_NOT_FROZEN_NOT_RUN',cohortKind='previously-registered-undispatched-users',recordedAt=audit['checkedAt'],purpose='New method on exact previously registered cases with no dispatch/run exposure in the preserved cohorts; old failed cohorts remain incomplete.',stagingOutput=str(root),realModelRequests=0,formalEvaluationStarted=False,remainingBeforeFreeze=['Validate current frozen driver/model/embedding/image hashes and preserve exact inputs.'],supersedesForNewDispatchOnly={'oldFreezeSha256':[s['freezeSha256'] for s in studies],'previouslyRegisteredButUnexecutedUsers':[c['personaId'] for c in cases],'selectionUsesNoAnswersOrOutcomes':True,'doesNotResumeOrReplaceOldCohorts':True,'exposureAuditSha256':hashlib.sha256((json.dumps(audit,ensure_ascii=False,indent=2)+'\n').encode()).hexdigest()})
 proposal['persona'].update(excludedDevelopmentUsers=sorted({'0'}|started,key=int),eligibleUsers=[c['personaId'] for c in cases],selectedUsers=[c['personaId'] for c in cases],cases=cases,budgetProposal=budgets,sameHistoricalTimeExplanationBothArms=True)
 proposal['qualityLimitsCarriedIntoEvaluation']=['Native Skill content/length quality has not passed (mixed-result overclaim, 7594-character body, no resources in latest development review).','Full-history fixture and time provenance are integration proofs, not accuracy improvement.','No causal attribution or full-benchmark claim; only eight user clusters.']
 for name,value in [('exposure-audit.json',audit),('proposal.json',proposal)]: (root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
 for study in studies:
  for rel,digest in study['preservationHashes'].items():assert sha(project/rel)==digest
 print(json.dumps({'status':audit['status'],'users':proposal['persona']['selectedUsers'],'questionCount':32,'oldActualCalls':[s['actualGatewayCalls'] for s in studies],'sourceFilesUnchanged':sum(len(s['preservationHashes']) for s in studies),'newRealModelRequests':0}))
if __name__=='__main__':main()
