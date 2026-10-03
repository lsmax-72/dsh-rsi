#!/usr/bin/env python3
"""Audit preserved fixed-response runner controls; makes no model requests."""
import argparse
import hashlib
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    def load(run,name): return json.loads((args.root/run/'state/pilot/preflight'/name).read_text())
    runs=['baseline-final','rsi-a2','rsi-b','rsi-final']
    initial={run:load(run,'initial.json') for run in runs}
    base=initial['baseline-final']
    assert base['assets'] is None and base['settings'] is None
    assert not any(s.startswith('rsi_') for s in base['toolSchemas'])
    assert not any(s['provider']=='dsh-rsi' for s in base['skillCandidates'])
    assert not (args.root/'baseline-final/state/assets').exists()
    baseline_requests=load('baseline-final','model-requests.json')
    assert all(not any(m.get('source',{}).get('kind')=='dsh-rsi' for m in r['messages']) for r in baseline_requests)
    def canonical_assets(run):
        value=dict(initial[run]['assets']); value.pop('createdAt')
        return json.dumps(value,sort_keys=True,ensure_ascii=False).encode()
    copies=['rsi-a2','rsi-b','rsi-final']
    first=canonical_assets(copies[0])
    for run in copies:
        assert initial[run]['baselineTree']==base['baselineTree']
        assert canonical_assets(run)==first, 'Frozen snapshot differs: '+run
        assert set(initial[run]['toolSchemas'])-set(base['toolSchemas'])=={'rsi_memory_search','rsi_conversation_search','rsi_profile_read'}
        assert initial[run]['assets']['memory'] and initial[run]['assets']['skills']
        assert load(run,'receipt.json')['backgroundDispatches']==0
        assert load(run,'receipt.json')['logReconstructionMatches']
    patch=(args.root/'baseline-final/state/pilot/preflight/prediction.patch').read_bytes()
    assert b'preflight-marker.txt' in patch
    for run in copies: assert (args.root/run/'state/pilot/preflight/prediction.patch').read_bytes()==patch
    interrupted=load('interrupted','model-requests.json')
    assert len(interrupted)==2 and interrupted[0]['usage']['totalTokens']==20
    assert interrupted[-1]['usage'] is None and interrupted[-1]['status']=='DISPATCHING'
    assert (args.root/'interrupted/state/pilot/preflight/prediction.patch').read_bytes()==patch
    assert (args.root/'interrupted/state/pilot/preflight/source-events.jsonl').stat().st_size>0
    assert json.loads((args.root/'interrupted/state.json').read_text())['container']['ExitCode']==137
    reconstruction=json.loads((args.root/'interrupted-audit.json').read_text())
    assert len(reconstruction)==2 and all(r['matches'] for r in reconstruction)
    assert reconstruction[-1]['responseFramePresent'] is False
    failed=load('rsi-a','failure.json')
    assert failed['runnerStatus']=='ERROR' and failed['classification']=='UNCLASSIFIED'
    assert failed['officialResolved'] is None and failed['observedRequests']==0
    receipt={'status':'PASS','formalBenchmarkStarted':False,'realProviderRequests':0,
        'baselineTree':base['baselineTree'],'frozenExportSha256':hashlib.sha256(first).hexdigest(),
        'patchSha256':hashlib.sha256(patch).hexdigest(),'successfulControls':runs,
        'interruption':{'exitCode':137,'observedRequests':2,'missingUsage':1,'reconstructedInputs':2,'patchSaved':True},
        'preservedFailures':[{'run':'rsi-a','reason':'Restored budget 30 differs from requested 15','providerRequests':0}],
        'checks':['baseline-service-assets-catalog-absent','same-source-tree','same-frozen-asset-state',
            'same-tool-edit-result','all-finished-inputs-reconstructable','unfinished-input-reconstructable',
            'SIGKILL-evidence-export','unknown-usage-not-zero','effective-budget-mismatch-rejected'],
        'limitation':'Fixed responses validate isolation and bookkeeping; they do not prove model effectiveness or natural Skill selection.'}
    args.output.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(receipt,ensure_ascii=False))


if __name__=='__main__': main()
