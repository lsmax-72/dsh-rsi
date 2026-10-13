#!/usr/bin/env python3
"""Detached supervision for proven zero-call build failures; never replay Agent tasks."""
import argparse, fcntl, json, os, subprocess, sys, time
from pathlib import Path


def read(p): return json.loads(p.read_text())


def write(p,v):
    tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(v,indent=2)+'\n');os.replace(tmp,p)


def alive(pid):
    if not pid:return False
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False


def action(state, worker_alive, stop):
    if stop or state['status'] in ['COMPLETE','STOPPED']:return 'FINISHED'
    if state['status']=='HALTED':return 'AUDIT_RECOVERY'
    if state['status']=='RUNNING' and worker_alive:return 'WAIT'
    raise ValueError('Worker state cannot be safely supervised')


def ensure_cache(launch, study):
    previous=launch/'cache-background-20261013.json'
    old=read(previous) if previous.exists() else {}
    if alive(old.get('cachePid')):
        command=subprocess.check_output(['ps','-p',str(old['cachePid']),'-o','command='],text=True).strip()
        if 'maintain-swe-build-cache.py' in command and str(launch) in command:return old['cachePid']
    work=Path(read(study/'protocol.json')['frozenWorktree'])
    with (launch/'cache-maintenance.log').open('ab') as log:
        child=subprocess.Popen([sys.executable,'-B',work/'scripts/maintain-swe-build-cache.py','--launch',launch],cwd=work,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    write(previous,{'cachePid':child.pid,'runnerPid':read(study/'background.json')['pid'],'restartedAt':time.time()})
    return child.pid


def run(launch):
    root=launch/'prelaunch-watch';root.mkdir(exist_ok=True)
    study=Path(read(launch/'launch.json')['study']);helper=Path(__file__).with_name('recover-swe-prelaunch.py')
    with (root/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            while True:
                state=read(study/'state.json');worker=read(study/'background.json')
                decision=action(state,alive(worker.get('pid')),(study/'STOP').exists() or (launch/'STOP').exists())
                if decision=='FINISHED':write(root/'state.json',{'status':'FINISHED','studyStatus':state['status'],'updatedAt':time.time()});return
                if decision=='AUDIT_RECOVERY':
                    # The helper checks every frozen input, closed checkpoint,
                    # zero-call lease, failure classifier and per-task retry cap.
                    # Any ambiguous/model-started failure is left HALTED.
                    with (root/(str(time.time_ns())+'.log')).open('w') as log:
                        subprocess.run([sys.executable,'-B',helper,'--output',study,'--apply'],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=300)
                    for _ in range(45):
                        state=read(study/'state.json')
                        if state['status']=='RUNNING':break
                        if state['status']!='STOPPED':raise ValueError('Recovery worker did not enter RUNNING')
                        time.sleep(1)
                    if state['status']!='RUNNING':raise ValueError('Recovery worker startup timed out')
                cache_pid=ensure_cache(launch,study)
                write(root/'state.json',{'status':'WATCHING','pid':os.getpid(),'runnerPid':read(study/'background.json')['pid'],'cachePid':cache_pid,'updatedAt':time.time()})
                time.sleep(30)
        except Exception as error:
            write(root/'state.json',{'status':'BLOCKED','error':str(error),'studyStatus':read(study/'state.json')['status'],'updatedAt':time.time()})
            raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--launch',type=Path,required=True);a=p.parse_args();run(a.launch.resolve())
