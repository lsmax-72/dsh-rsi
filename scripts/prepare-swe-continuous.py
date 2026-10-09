#!/usr/bin/env python3
"""Create scoped development inputs or an unconfirmed formal draft; no execution."""
import argparse, importlib.util, json, random
from pathlib import Path
P=Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location('continuous',P/'scripts/run-swe-continuous.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--purpose',choices=['development','formal'],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();m.require(not a.output.exists(),'Preserve previous specifications')
    old=m.read(P/'docs/evidence/swe-expansion-spec-20261008.json')
    if a.purpose=='development':cases=m.read(P/'docs/evidence/thinking-environments-20261008.json')['environments'][:2]
    else:
        selected=old['manifest']['heldOut'];random.Random(20261008).shuffle(selected);cases=[]
        for item in selected:
            f=P/'.artifacts/swe-continuous-environments-20261009'/item['instanceId']/'environment.json'
            c=dict(item,environmentFile=str(f),environmentPending=not f.is_file())
            if f.is_file():
                e=m.read(f);c.update(environmentSha256=m.sha(f),publicInputSha256=m.sha(f.parent/'task.json'),taskTag=e['taskTag'],taskImageId=e['taskImage'],scorerKey=e['scorerKey'],scorerImageId=e['scorerImage'],baselineDate=e['baselineDate'],expectedTree=e['environment']['baseTree'],expectedVersion=e['environment']['djangoVersion'])
            cases.append(c)
    for c in cases:c['environmentFile']=str((P/c['environmentFile']).resolve())
    b={'foregroundCalls':40 if a.purpose=='development' else 60,'wallSeconds':1200,'maxOutputTokens':8192,'learningCallsPerTask':20,'learningTotal':len(cases)*20,'settleSeconds':900}
    s={'status':'SCOPED_DEVELOPMENT_INPUTS' if a.purpose=='development' else 'FORMAL_DRAFT_NOT_APPROVED_OR_FROZEN','purpose':a.purpose,'model':'qwen3.8-27b','thinking':'off','thinkingConfirmed':True,'budgetConfirmed':a.purpose=='development','serial':True,'emptyStart':True,'historyMode':'native-fork','stageSize':20,'confidenceInterval':None,'orderSeed':None if a.purpose=='development' else 20261008,'cases':cases,'budgets':b,'datasetSha256':old['datasetSha256'],'selection':'First two already exposed development tasks, original order, no outcome selection' if a.purpose=='development' else 'Preserve the original 100 heldOut IDs, remove all four prefix tasks; shuffle once with seed20261008','diagnosticPositions':list(range(1,len(cases)+1)) if a.purpose=='development' else [1,20,21,40,41,60,61,80,81,100],'sourceManifestSha256':m.sha(P/'docs/evidence/swe-expansion-spec-20261008.json'),'historyPolicy':'Native fork directly inherits own prior original session events into subsequent requests; ordered raw logs also remain tool-readable. RSI also restores natural native asset/checkpoint state. No grading data.','scorerFeedbackAllowed':False,'automaticRetries':False,'realModelRequests':0,'formal100Allowed':False}
    if a.purpose=='formal':s.update(excluded=old['excluded'],inheritanceAudit=None,budgetNote='60/1200/8192 and native20/900 are proposals, not confirmed formal budgets; real inheritance audit and all prepared environments required before freeze')
    m.write(a.output,s);print(json.dumps({'purpose':a.purpose,'cases':len(cases),'preparedEnvironmentFiles':sum(not c.get('environmentPending',False) for c in cases),'budgetConfirmed':s['budgetConfirmed'],'realModelRequests':0}))
if __name__=='__main__':main()
