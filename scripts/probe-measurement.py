#!/usr/bin/env python3
"""Offline controls for experiment budget durability and saved outcome accounting."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import tempfile
import hashlib


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    root=Path(__file__).resolve().parent
    budget=load(root/'learning-budget.py','budget');summary=load(root/'summarize-paired.py','summary')
    with tempfile.TemporaryDirectory(prefix='rsi-measurement-') as tmp:
        work=Path(tmp);path=work/'pool.sqlite';pool=budget.LearningBudget(path,7);pool.close()
        def reserve(n):
            p=budget.LearningBudget(path)
            try:return p.reserve(str(n),2)
            finally:p.close()
        with ThreadPoolExecutor(max_workers=8) as executor: quotas=list(executor.map(reserve,range(16)))
        assert sum(quotas)==7
        p=budget.LearningBudget(path);assert p.snapshot()['remaining']==0
        held=next(str(n) for n,q in enumerate(quotas) if q)
        assert any(r['used'] is None for r in p.snapshot()['leases'])
        p.close();p=budget.LearningBudget(path);assert p.snapshot()['remaining']==0
        p.settle(held,0,'verified-no-provider-dispatch');remaining=p.snapshot()['remaining'];assert remaining==quotas[int(held)]
        assert p.reserve('resumed',99)==remaining
        try:p.settle('resumed',remaining+1,'bad');raise AssertionError('Overcharge accepted')
        except ValueError:pass
        p.close()
        try:budget.LearningBudget(path,8);raise AssertionError('Pool reset accepted')
        except ValueError:pass
        manifest={'prefix':[],'heldOut':[{'instanceId':'fixture-1'},{'instanceId':'fixture-2'},{'instanceId':'fixture-3'}]}
        rows=[]
        def row(id_,arm,resolved,usage_value=20,classification='GRADED',attempt=0):
            run=work/(id_+arm+str(attempt));run.mkdir();patch=b'fixture-prediction';(run/'prediction.patch').write_bytes(patch)
            (run/'model-requests.json').write_text(json.dumps([{'sessionId':'pilot-'+id_,'usage':None if usage_value is None else {'inputTokens':13,'outputTokens':7,'totalTokens':usage_value}}]))
            (run/'receipt.json').write_text(json.dumps({'stopReason':{'kind':'error','error':{'message':'budget cap'}}}))
            grade=run/'grade.json'
            if resolved is not None:grade.write_text(json.dumps({'instanceId':id_,'resolved':resolved,'patchSha256':hashlib.sha256(patch).hexdigest(),'officialReport':{id_:{'resolved':resolved}}}))
            record={'instanceId':id_,'stage':'heldOut','arm':arm,'attempt':attempt,'classification':classification,'runDir':str(run),'grading':str(grade) if resolved is not None else None};rows.append(record);return record
        row('fixture-1','baseline',False);row('fixture-1','rsi',True)
        row('fixture-2','baseline',True);row('fixture-2','rsi',False)
        failed=row('fixture-3','baseline',None,None,'INFRA');row('fixture-3','rsi',True)
        partial=summary.summarize(manifest,rows)
        assert partial['newlyResolvedKnownPairs']==partial['newlyFailedKnownPairs']==1
        assert partial['netResolvedDifference'] is None and partial['arms']['baseline']['successRate'] is None
        assert partial['allChainTokenDelta'] is None and partial['arms']['baseline']['allAttemptsUsage']['knownTotalTokens']==40
        absent=summary.summarize(manifest,rows[:-1])
        assert absent['arms']['rsi']['usageByStage']['heldOut']['foreground']['totalTokens'] is None
        assert absent['arms']['rsi']['usageByStage']['heldOut']['learning']['totalTokens'] is None
        row('fixture-3','baseline',False,30,attempt=1)
        final=summary.summarize(manifest,rows)
        assert final['status']=='COMPLETE_SAVED_RESULTS' and final['netResolvedDifference']==1
        assert final['arms']['baseline']['allAttemptsUsage']['requests']==4 and final['allChainTokenDelta'] is None
        try:
            summary.summarize(manifest,[{**r,'classification':'TASK_FAIL'} if r is failed else r for r in rows]);raise AssertionError('Task-failure retry accepted')
        except ValueError:pass
        grade=Path(rows[0]['grading']);g=json.loads(grade.read_text());g['patchSha256']='wrong';grade.write_text(json.dumps(g))
        try:summary.summarize(manifest,rows);raise AssertionError('Mismatched patch grade accepted')
        except ValueError:pass
    result={'status':'PASS','syntheticData':True,'realProviderRequests':0,'officialScorerExecutions':0,'formalBenchmarkStarted':False,
        'checks':['concurrent-pool-cap','abandoned-reservation-survives-reopen','verified-refund-only','pool-cap-immutable',
        'no-overcharge','budget-stop-does-not-overwrite-official-success','fixed-denominator-missing-outcomes',
        'unknown-usage-not-zero','missing-stage-runs-not-zero-cost','all-retry-costs-counted','only-confirmed-INFRA-retried','grade-patch-hash-match']}
    args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))


if __name__=='__main__':main()
