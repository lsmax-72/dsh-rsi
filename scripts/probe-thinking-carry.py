#!/usr/bin/env python3
"""Read-only completed-case audit and actual controller skip test; no real task calls."""
import importlib.util,json,tempfile
from pathlib import Path
P=Path(__file__).resolve().parent.parent
s=importlib.util.spec_from_file_location('controller',P/'scripts/run-thinking-preexperiment.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
audit=P/'docs/evidence/thinking-completed-case-audit-20261008.json';rec,previous,evidence=m.load_carried(audit)
assert rec['status']=='CLOSED_GRADED' and rec['runnerReturnCode']==1 and rec['calls']==17 and rec['auditRepair']['rawWireBytesAvailable'] is False
calls=[]
def dispatch(root,protocol,e,mode):
 calls.append((e['instanceId'],mode));result={'instanceId':e['instanceId'],'thinking':mode,'status':'HALTED','resolved':None,'error':'fixture stop before real task'};m.write(root/(e['instanceId']+'-'+mode+'-0.record.json'),result);return result
m.run_case=dispatch
with tempfile.TemporaryDirectory() as td:
 root=Path(td);m.write(root/(rec['instanceId']+'-on-0.record.json'),rec);m.run(root,previous,True)
 assert calls==[(rec['instanceId'],'off')],calls
 assert m.read(root/(rec['instanceId']+'-on-0.record.json'))==rec
 summary=m.read(root/'summary.json');assert len(summary['rawWireEvidenceGaps'])==1 and summary['totals']['on']['graded']==1 and summary['totals']['on']['passRate'] is None
print(json.dumps({'status':'PASS_EXPLICIT_COMPLETED_CASE_CARRY','realProviderRequests':0,'dockerOperations':0,'checks':['existing completed original native/service/official score verified without replay','strict raw-byte gap retained explicitly','controller skips audited On and dispatches only next Off','original failed-export record remains unchanged','partial rate not reported as complete 8 pairs']}))
