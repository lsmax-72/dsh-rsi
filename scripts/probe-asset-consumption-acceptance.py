#!/usr/bin/env python3
"""Audit saved real acceptance and reject catalog-only, inherited-only, or wire-missing bodies."""
import copy, importlib.util, json
from pathlib import Path
P=Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location('acceptance',P/'scripts/run-asset-consumption-acceptance.py');a=importlib.util.module_from_spec(sp);sp.loader.exec_module(a)
root=P/'.artifacts/swe-asset-acceptance-20261011-attempt3';seed=P/'.artifacts/swe-continuous-development-20261009/002-rsi/state';case=a.m.read(P/'docs/evidence/thinking-environments-20261008.json')['environments'][1];out=root/'002-rsi'
actual=a.audit(out,case,seed,'rsi');assert len(actual['memory'])==len(actual['skills'])==1
read=a.m.read
# Counterfactual parser inputs only; never alter original experimental bytes.
def missing_wire(path):
    value=read(path)
    if str(path).endswith('.request.json'):
        value=copy.deepcopy(value)
        for msg in value['messages']:
            if msg['role']=='tool':msg['content']='omitted for validator test'
            if msg['role']=='user' and '<available_skills>' not in str(msg.get('content')):msg['content']='omitted for validator test'
    return value
a.m.read=missing_wire
result=a.audit(out,case,seed,'rsi');assert result['memory']==[] and result['skills']==[]
a.m.read=read
# Skill tool presence/catalog never counts unless the current task loaded it.
def no_load(path):
    value=read(path)
    if Path(path).name=='tool-results.json':return [t for t in value if t['name']!='skill']
    return value
a.m.read=no_load
result=a.audit(out,case,seed,'rsi');assert result['skills']==[] and result['memory']
a.m.read=read
print(json.dumps({'status':'PASS_SAVED_ASSET_ACCEPTANCE_VALIDATOR','newModelRequests':0,'realTraceAudit':True,'checks':['fresh native prefix and old raw logs byte-exact','copied asset heads and relevance settings unchanged','full Memory and Skill in actual outbound request','catalog/tool-record without wire body rejected','inherited or absent current Skill load rejected'],'counterfactualInputsAreExperimentResults':False}))
