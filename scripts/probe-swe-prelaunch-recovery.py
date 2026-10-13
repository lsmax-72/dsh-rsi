#!/usr/bin/env python3
"""Offline negative controls for prelaunch recovery; no Docker or model dispatch."""
import copy, importlib.util, json, tempfile
from pathlib import Path
p=Path(__file__).with_name('recover-swe-prelaunch.py');q=importlib.util.spec_from_file_location('recovery',p);m=importlib.util.module_from_spec(q);q.loader.exec_module(m)

def write(p,value): p.write_text(json.dumps(value))

def fixture(root):
    spec={'cases':[{'instanceId':'django__django-1'},{'instanceId':'django__django-2'}],'budgets':{'learningTotal':40}}
    rows=[{'position':1,'arm':a,'instanceId':'django__django-1','attempt':0,'status':'CLOSED_GRADED'} for a in ['baseline','rsi']]
    cp={'state':str(root/'001-rsi/state'),'sessions':{'one':'hash'},'assets':{'two':'hash'}}
    write(root/'001-rsi.checkpoint.json',cp)
    rows.append({'position':2,'arm':'rsi','instanceId':'django__django-2','attempt':0,'status':'HALTED_STATE_OR_FREEZE','resolved':None,'runnerReturnCode':1,'runDir':str(root/'002-rsi'),'previousOwnState':cp['state']})
    out=root/'002-rsi';out.mkdir();(out/'build.log').write_text('exporting to image\nERROR: failed to build: input/output error')
    write(out/'source-snapshot.json',{'inputSha256':{k:cp[k] for k in ['sessions','assets']}})
    lease={'id':'rsi-preflight-0123456789','quota':20,'used':0,'evidence':'NO_TASK_STARTED'}
    pool={'cap':40,'leases':[lease]};write(out/'budget-settlement.json',pool)
    write(out/'budget-reservation.json',{'leaseId':lease['id'],'quota':20})
    return spec,rows,pool

checks=[]
for kind in ['valid','model-evidence','state-evidence','used-lease','unsettled-lease','wrong-budget','wrong-source','not-storage','later-record','checkpoint','duplicate','wrong-task','npm-timeout','npm-integrity','npm-lockfile','recovery-limit']:
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);spec,rows,pool=fixture(root);out=root/'002-rsi'
        if kind=='model-evidence': (out/'gateway.log').write_text('request')
        if kind=='state-evidence': (out/'state').mkdir()
        if kind=='used-lease': pool['leases'][0]['used']=1
        if kind=='unsettled-lease': pool['leases'].append({'id':'other','quota':20,'used':None,'evidence':None})
        if kind=='wrong-budget': pool['cap']=80
        if kind=='wrong-source': write(out/'source-snapshot.json',{'inputSha256':{}})
        if kind=='not-storage': (out/'build.log').write_text('network failure')
        if kind=='later-record': rows.append({'position':2,'arm':'baseline','instanceId':'django__django-2','attempt':0,'status':'CLOSED_GRADED'})
        if kind=='checkpoint': write(root/'002-rsi.checkpoint.json',{})
        if kind=='duplicate': rows.append(copy.deepcopy(rows[0]))
        if kind=='wrong-task': rows[-1]['instanceId']='django__django-3'
        if kind in ['npm-timeout','npm-integrity','npm-lockfile']:
            code={'npm-timeout':'EIDLETIMEOUT','npm-integrity':'EINTEGRITY','npm-lockfile':'EUSAGE'}[kind]
            (out/'build.log').write_text('RUN cd /opt/rsi && npm ci --ignore-scripts\nnpm error code '+code+'\nregistry.npmjs.org\ndid not complete successfully: exit code: 1\nERROR: failed to build: npm failed')
        if kind=='recovery-limit':
            for i in range(3):
                archive=root/'prelaunch-recovery'/str(i);archive.mkdir(parents=True)
                write(archive/'audit.json',{'position':2,'arm':'rsi'})
        try: m.evidence(root,spec,rows,pool); accepted=True
        except ValueError: accepted=False
        assert accepted==(kind in ['valid','npm-timeout']),kind
        checks.append(kind)
q=importlib.util.spec_from_file_location('watch',p.with_name('watch-swe-prelaunch.py'));watch=importlib.util.module_from_spec(q);q.loader.exec_module(watch)
watch_checks=[]
for status,alive,stop,wanted in [('RUNNING',True,False,'WAIT'),('HALTED',False,False,'AUDIT_RECOVERY'),('COMPLETE',False,False,'FINISHED'),('STOPPED',False,False,'FINISHED'),('RUNNING',True,True,'FINISHED')]:
    assert watch.action({'status':status},alive,stop)==wanted
    watch_checks.append(status+':'+wanted)
try: watch.action({'status':'RUNNING'},False,False)
except ValueError: watch_checks.append('dead worker blocks')
else: raise AssertionError('Unexpected dead worker must block')
print(json.dumps({'status':'PASS_PRELAUNCH_RECOVERY_CONTROLS','checks':checks,'watchChecks':watch_checks,'realModelRequests':0,'formalDispatches':0}))
