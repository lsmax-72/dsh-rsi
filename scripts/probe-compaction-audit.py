#!/usr/bin/env python3
"""Offline tamper checks on an actual native compaction fixture; no dispatch."""
import argparse, copy, importlib.util, json, os, subprocess, tempfile
from pathlib import Path
P=Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location('continuous',P/'scripts/run-swe-continuous.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--native-module',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();proof=m.read(a.evidence/'audit.json');m.require(proof['fixtureModel'] and proof['realModelRequests']==0,'Only fixture evidence');checks=[]
    with tempfile.TemporaryDirectory() as td:
        td=Path(td);env=dict(os.environ,RSI_NATIVE_COMPACTION_MODULE=str(a.native_module.resolve()))
        for arm in m.ARMS:
            run=a.evidence/m.key(2,arm);pilot=run/'state/pilot'/m.thinking.IDS[1];ledger=m.read(pilot/'model-requests.json');receipt=m.read(pilot/'receipt.json');m.require(receipt['taskDispatches']==len(ledger)==4 and sum(r['purpose']=='compaction' for r in ledger)==1,'Native compaction not charged to foreground')
            def audit(data):
                file=td/(arm+'.requests.json');m.write(file,data);return subprocess.run(['node',P/'scripts/audit-session-requests.mjs',file,run/'state/home/sessions',td/(arm+'.recon.json')],env=env,text=True,capture_output=True)
            observed=audit(ledger);m.require(observed.returncode==0,observed.stderr[-1000:]);recon=m.read(td/(arm+'.recon.json'));m.require(all(r['matches'] for r in recon),'Observed native reconstruction failed')
            digest=next(r['nativeCompactionModuleSha256'] for r in recon if r['purpose']=='compaction');m.require(digest==m.sha(a.native_module),'Wrong native instruction source')
            for kind in ['directive','source-body']:
                bad=copy.deepcopy(ledger);item=next(r for r in bad if r['purpose']=='compaction');item['messages'][-1 if kind=='directive' else 0]['content']=[{'type':'text','text':'tampered'}];m.require(audit(bad).returncode!=0,'Modified '+kind+' accepted')
            checks.append({'arm':arm,'nativeCalls':4,'compactionCalls':1,'exactNativeInstructionSource':digest,'persistedPrefixReconstructed':True,'alteredDirectiveRejected':True,'alteredSourceBodyRejected':True})
    result={'status':'PASS_OFFLINE_NATIVE_COMPACTION_AUDIT','realModelRequests':0,'officialScorerInvocations':0,'checks':checks};m.write(a.output,result);print(json.dumps(result))
if __name__=='__main__':main()
