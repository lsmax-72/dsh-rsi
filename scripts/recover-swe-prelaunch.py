#!/usr/bin/env python3
"""Audit and archive a storage failure before task launch; reuse the frozen runner."""
import argparse, fcntl, importlib.util, json, os, re, shutil, sqlite3, subprocess, sys, time
from pathlib import Path


def require(ok, message):
    if not ok: raise ValueError(message)


def read(path): return json.loads(path.read_text())


def evidence(root, spec, records, pool):
    terminal={'CLOSED_GRADED','CLOSED_INFRA'}
    schedule=[(p, arm) for p in range(1,len(spec['cases'])+1)
              for arm in (['baseline','rsi'] if p%2 else ['rsi','baseline'])]
    by={(r['position'],r['arm']):r for r in records}
    require(len(by)==len(records), 'Duplicate records')
    closed=[]; failed=None
    for item in schedule:
        row=by.get(item)
        if row and row['status'] in terminal and failed is None: closed.append(row); continue
        require(row is not None and failed is None, 'Missing or multiple interrupted attempts')
        failed=row; break
    require(failed and len(records)==len(closed)+1, 'Records do not form a closed prefix and one failure')
    for r in records:
        require(r['instanceId']==spec['cases'][r['position']-1]['instanceId'] and r['attempt']==0, 'Task ownership changed')
    r=failed; name=f"{r['position']:03d}-{r['arm']}"; out=root/name
    require(r['arm']=='rsi' and r['position']>1 and r['status']=='HALTED_STATE_OR_FREEZE'
            and r['resolved'] is None and r.get('runnerReturnCode')==1, 'Not a prelaunch RSI failure')
    require(Path(r['runDir'])==out and not out.is_symlink(), 'Unexpected run directory')
    require({p.name for p in out.iterdir()}=={'build.log','source-snapshot.json','budget-reservation.json','budget-settlement.json'}, 'Possible task/model/state evidence: refuse recovery')
    require(not (root/(name+'.checkpoint.json')).exists(), 'Failed attempt has checkpoint')
    log=(out/'build.log').read_text()
    require('ERROR: failed to build:' in log and 'input/output error' in log and 'exporting to image' in log, 'Not an evidenced storage build failure')
    reservation=read(out/'budget-reservation.json'); lease=reservation['leaseId']
    require(re.fullmatch(r'rsi-preflight-[0-9a-f]{10}',lease), 'Invalid resource prefix')
    require(pool['cap']==spec['budgets']['learningTotal'] and all(x['used'] is not None for x in pool['leases']), 'Budget cap differs or unsettled work remains')
    for snapshot in [pool,read(out/'budget-settlement.json')]:
        matches=[x for x in snapshot['leases'] if x['id']==lease]
        require(len(matches)==1 and matches[0]['used']==0 and matches[0]['evidence']=='NO_TASK_STARTED'
                and matches[0]['quota']==reservation['quota'], 'Task may have started or budget is ambiguous')
    prior=root/f"{r['position']-1:03d}-rsi.checkpoint.json"; cp=read(prior)
    require(r['previousOwnState']==cp['state'] and read(out/'source-snapshot.json')['inputSha256']=={k:cp[k] for k in ['sessions','assets']}, 'Prior own state delivery differs')
    return r, closed, lease


def load_frozen(root):
    spec=read(root/'protocol.json'); work=Path(spec['frozenWorktree'])
    q=importlib.util.spec_from_file_location('frozen_continuous',work/'scripts/run-swe-continuous.py')
    m=importlib.util.module_from_spec(q); q.loader.exec_module(m)
    require(m.load_protocol(root)==spec,'Protocol changed')
    return m,spec,work


def audit(root):
    m,spec,work=load_frozen(root)
    require(read(root/'state.json')['status']=='HALTED','Only a halted batch is eligible')
    old=read(root/'background.json')
    if old.get('pid'):
        try: os.kill(old['pid'],0)
        except ProcessLookupError: pass
        else: raise ValueError('Worker is still alive')
    os.environ.setdefault('RSI_MODEL_UPSTREAM','http://10.195.214.152:8100/v1')
    m.validate(spec)
    require(m.thinking.model_identity()==spec['modelIdentity'],'Model deployment changed')
    subprocess.run(['docker','system','df'],check=True,capture_output=True,text=True,timeout=60)
    require(shutil.disk_usage(root).free>=30*1024**3,'Insufficient recovery headroom (30 GiB required)')
    db=sqlite3.connect('file:'+str(root/'learning-budget.sqlite')+'?mode=ro',uri=True)
    try:
        cap=db.execute('SELECT cap FROM pool').fetchone()[0]
        pool={'cap':cap,'leases':[dict(zip(['id','quota','used','evidence'],row)) for row in db.execute('SELECT id,quota,used,evidence FROM leases')]}
    finally: db.close()
    r,closed,lease=evidence(root,spec,m.rows(root),pool)
    for row in closed: m.checkpoint_check(root,row)
    resources={
        'containers':subprocess.check_output(['docker','ps','-aq','--filter','label=dsh-rsi-output='+r['runDir']],text=True,timeout=30).split(),
        'containerNames':subprocess.check_output(['docker','ps','-a','--format','{{.Names}}'],text=True,timeout=30).split(),
        'volumes':subprocess.check_output(['docker','volume','ls','-q'],text=True,timeout=30).split(),
        'networks':subprocess.check_output(['docker','network','ls','--format','{{.Name}}'],text=True,timeout=30).split()}
    require(not resources['containers'] and not any(x.startswith(lease) for k,v in resources.items() if k!='containers' for x in v),'Task runtime resources still exist')
    hashes={p.name:m.sha(p) for p in root.glob('*.record.json') if read(p)['status'] in m.TERMINAL}
    return m,spec,work,r,hashes,pool


def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--output',type=Path,required=True)
    p.add_argument('--apply',action='store_true'); a=p.parse_args(); root=a.output.resolve()
    # Both controller locks are held through the state transition. A failed audit
    # leaves HALTED intact; no synthetic receipt, checkpoint or score is created.
    with (root/'launch.lock').open('a') as launch, (root/'worker.lock').open('a') as worker:
        for lock in [launch,worker]: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        m,s,work,r,hashes,pool=audit(root)
        result={'status':'PASS_SAFE_PRELAUNCH_RECOVERY','position':r['position'],'arm':r['arm'],
                'closedRecords':len(hashes),'closedRecordHashes':hashes,'frozenRevision':s['revision'],
                'protocolSha256':m.sha(root/'protocol.json'),'taskOrModelStarted':False,
                'learningCallsCharged':sum(x['used'] for x in pool['leases']),
                'learningLeasesUnchanged':True,'modelOrScorerRequests':0,'checkedAt':time.time()}
        if not a.apply: print(json.dumps({k:v for k,v in result.items() if k!='closedRecordHashes'})); return
        name=f"{r['position']:03d}-{r['arm']}"; archive=root/'prelaunch-recovery'/str(time.time_ns()); archive.mkdir(parents=True)
        result['archive']=str(archive); result['archivedEntryHashes']=m.base.files(root/name)
        m.write(archive/'audit.json',result)
        for filename in ['state.json','background.json','runs.json','summary.json','report.md']:
            if (root/filename).exists(): shutil.copy2(root/filename,archive/filename)
        # Archive only the unstarted transaction. Its zero-used lease remains in
        # the durable pool; a fresh lease is allocated by the same frozen runner.
        for source in [root/name,root/(name+'.record.json'),root/(name+'.runner.log'),root/(name+'.history-order.json')]:
            if source.exists(): source.rename(archive/source.name)
        require(m.base.files(archive/name)==result['archivedEntryHashes'],'Archived evidence bytes changed')
        require({p.name:m.sha(p) for p in root.glob('*.record.json')}==hashes,'Closed records changed')
        m.summarize(root,s)
        m.write(root/'state.json',{'status':'STOPPED','completedRuns':len(hashes),'plannedRuns':2*len(s['cases']),'safePrelaunchRecovery':str(archive)})
        print(json.dumps({k:v for k,v in result.items() if k not in ['closedRecordHashes','archivedEntryHashes']}))
    # Reuse the existing background entry and all original frozen gates.
    subprocess.run([sys.executable,'-B',work/'scripts/run-swe-continuous.py','start','--resume','--output',root],cwd=work,check=True)


if __name__=='__main__': main()
