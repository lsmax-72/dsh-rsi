#!/usr/bin/env python3
"""Detached preparation gate -> frozen native continuous runner; no live Codex required."""
import argparse, fcntl, importlib.util, json, os, subprocess, sys, time
from pathlib import Path
P=Path(__file__).resolve().parent.parent
q=importlib.util.spec_from_file_location('continuous',P/'scripts/run-swe-continuous.py');m=importlib.util.module_from_spec(q);q.loader.exec_module(m)
read,write,sha,require=m.read,m.write,m.sha,m.require

def alive(pid):
    if not pid:return False
    try:os.kill(pid,0);return True
    except ProcessLookupError:return False

def check_inputs(f):
    require(m.checked(['git','rev-parse','HEAD'])==f['revision'] and not m.checked(['git','status','--porcelain']),'Launch code checkout changed before freeze')
    require(m.base.codehash()==f['codeHashes'],'Launch implementation/build changed')
    for path,digest in f['inputs'].items():require(sha(Path(path))==digest,'Pinned preparation/acceptance input changed: '+path)
    require(sha(Path(f['dataset']))==f['datasetSha256'],'Dataset changed before freeze')
    require(sha(Path(f['embedding']))==m.EMBEDDING_SHA,'Native embedding changed before freeze')

def recover_empty_network_failure(f,p):
    # Only retry pre-model transport failures with no environment bytes. Never
    # reinterpret source/build/freeze failures or overwrite valid receipts.
    root=Path(f['environments']);instance=p.get('current');log=root/'logs'/(str(instance)+'.log');env=root/str(instance)
    if p.get('status')!='HALTED' or alive(p.get('pid')) or instance not in {c['instanceId'] for c in read(root/'preparation.json')['cases']} or instance in p['completed']:return False
    if not env.is_dir() or any(env.iterdir()) or not log.is_file():return False
    text=log.read_text();markers=['UNEXPECTED_EOF_WHILE_READING','requests.exceptions.ConnectionError','requests.exceptions.ReadTimeout','Temporary failure in name resolution']
    if not any(x in text for x in markers):return False
    recovery=root/'network-recovery';recovery.mkdir(exist_ok=True);attempt=len(list(recovery.glob(instance+'-*')))+1
    if attempt>3:return False
    archive=recovery/(instance+'-'+str(attempt));archive.mkdir();env.rename(archive/'empty-environment');log.rename(archive/'preparation.log');write(archive/'halted-state.json',p)
    write(root/'state.json',p|{'status':'STARTING','pid':None,'networkRecovery':str(archive)})
    with (root/'coordinator.log').open('ab') as output:child=subprocess.Popen([sys.executable,'-B',P/'scripts/prepare-swe-environments.py','run','--output',root],cwd=P,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
    # Worker owns the next state write. STARTING without a pid is tolerated
    # for one poll, avoiding a coordinator/worker state overwrite race.
    return True

def complete_spec(f):
    spec=read(Path(f['spec']));m.spec_check(spec)
    health=spec['scorerHealthAudit'];require(sha(Path(health['file']))==health['sha256'],'Scorer health evidence changed')
    h=read(Path(health['file']));require(h['status']=='PASS' and h['datasetSha256']==spec['datasetSha256'] and h['verifiedSourceFiles']==50 and h['swebenchVersion']=='3.0.0' and len(h['cases'])==4 and all(c['resolved']==(c['condition']=='oracle') for c in h['cases']),'Independent official scorer controls not verified')
    root=Path(f['environments']);state=read(root/'state.json');prep=read(root/'preparation.json')
    require(not prep['fixture'] and prep['realModelRequests']==0 and state['status']=='READY','Production environments are not all ready')
    require(prep['datasetSha256']==spec['datasetSha256'] and [c['instanceId'] for c in prep['cases']]==m.order(spec),'Environment dataset/task order mismatch')
    require(set(state['completed'])==set(m.order(spec)),'Missing or foreign prepared environment')
    for c in spec['cases']:
        instance=c['instanceId'];path=root/instance/'environment.json';r=read(path);public_path=path.parent/'task.json';public=read(public_path);saved=state['completed'][instance]
        require(sha(path)==saved['environmentSha256'] and sha(public_path)==saved['publicInputSha256']==r['publicInputSha256'],'Prepared receipt/public bytes changed: '+instance)
        require(r['instanceId']==public['instance_id']==instance and set(public)=={'instance_id','repo','base_commit','problem_statement','version'},'Non-public or mismatched task input')
        require(public['repo']==c['repo']=='django/django' and public['base_commit']==c['baseCommit'] and public['version']==c['version'],'Public task metadata mismatch')
        e=r['environment'];require(e['publicTreeAudit']['samePathsTypesAndBlobs'] and e['publicTreeAudit']['onlyExecutableModesDiffer'] and r['verifiedSourceFiles']==50 and r['swebenchVersion']=='3.0.0' and r['modelRequests']==0,'Source or official scorer provenance mismatch')
        c.pop('environmentPending',None)
        c.update(environmentFile=str(path.resolve()),environmentSha256=sha(path),publicInputSha256=sha(public_path),publicMetadata={k:public[k] for k in ['repo','base_commit','version']},taskTag=r['taskTag'],taskImageId=r['taskImage'],scorerKey=r['scorerKey'],scorerImageId=r['scorerImage'],baselineDate=r['baselineDate'],expectedTree=e['baseTree'],expectedVersion=e['djangoVersion'])
        for tag,key in [(c['taskTag'],'taskImageId'),(c['scorerKey'],'scorerImageId')]:require(m.checked(['docker','image','inspect','--format','{{.Id}}',tag])==c[key],'Prepared image changed: '+instance)
    spec['status']='APPROVED_ENVIRONMENTS_VALIDATED_PENDING_FREEZE';return spec

def run(root):
    with (root/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        f=read(root/'launch.json');state={'status':'WAITING_ENVIRONMENTS','pid':os.getpid(),'formal100Started':False}
        try:
            check_inputs(f)
            while True:
                if (root/'STOP').exists():state['status']='STOPPED';return
                check_inputs(f);p=read(Path(f['environments'])/'state.json')
                state.update(prepared=len(p['completed']),planned=100,environmentStatus=p['status'],updatedAt=time.time());write(root/'state.json',state)
                if p['status']=='READY':break
                if recover_empty_network_failure(f,p):time.sleep(30);continue
                require(p['status'] in ['STARTING','PREPARING'],'Environment preparation blocked: '+p.get('error',p['status']))
                require(alive(p.get('pid')),'Environment worker stopped unexpectedly; no automatic replay')
                time.sleep(30)
            check_inputs(f);state['status']='VALIDATING_FREEZE';write(root/'state.json',state)
            spec=complete_spec(f);path=root/'ready-spec.json';write(path,spec)
            study=Path(f['study']);require(not study.exists() and not study.with_name(study.name+'-code').exists(),'Existing study/frozen checkout needs manual audit')
            command=[sys.executable,'-B',P/'scripts/run-swe-continuous.py']
            with (root/'freeze.log').open('x') as log:subprocess.run([str(x) for x in command+['freeze','--output',study,'--spec',path,'--dataset',f['dataset'],'--scorer',f['scorer'],'--embedding',f['embedding']]],cwd=P,stdout=log,stderr=subprocess.STDOUT,check=True)
            # Freeze success is required before any formal foreground dispatch.
            state['status']='FROZEN';write(root/'state.json',state)
            with (root/'start.log').open('x') as log:subprocess.run([str(x) for x in command+['start','--output',study]],cwd=P,stdout=log,stderr=subprocess.STDOUT,check=True)
            state.update(status='RUNNER_LAUNCHED',study=str(study),runner=read(study/'background.json'),formal100Started=False,note='Runner validates deployment before dispatch; inspect study state/runs for actual task start.')
        except Exception as error:state.update(status='HALTED',error=str(error),automaticRetry=False)
        finally:state['updatedAt']=time.time();write(root/'state.json',state)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['start','run','status','stop']);p.add_argument('--output',type=Path,required=True)
    for name in ['spec','environments','study','dataset','scorer','embedding']:p.add_argument('--'+name,type=Path)
    a=p.parse_args();root=a.output.resolve();os.environ.setdefault('RSI_MODEL_UPSTREAM','http://10.195.214.152:8100/v1')
    if a.mode=='status':
        state=read(root/'state.json');f=read(root/'launch.json');state['launcherAlive']=alive(state.get('pid'));study=Path(f['study'])
        if (study/'state.json').exists():state['study']=read(study/'state.json');state['formal100Started']=bool(list(study.glob('*.record.json')))
        print(json.dumps(state,ensure_ascii=False,indent=2));return
    if a.mode=='stop':
        (root/'STOP').touch();study=Path(read(root/'launch.json')['study'])
        if study.exists():(study/'STOP').touch()
        print('STOP requested: no new tasks after safe closure');return
    if a.mode=='run':run(root);return
    require(not root.exists(),'Preserve prior launch evidence; do not replay a launch')
    require(all(getattr(a,k) for k in ['spec','environments','study','dataset','scorer','embedding']),'All explicit study/preparation inputs required')
    spec=read(a.spec.resolve());m.spec_check(spec);prep=read(a.environments.resolve()/'preparation.json')
    inputs={str(a.spec.resolve()):sha(a.spec.resolve()),str(a.environments.resolve()/'preparation.json'):sha(a.environments.resolve()/'preparation.json')}|prep['inputHashes']
    for name in ['inheritanceAudit','settlementAudit','scorerHealthAudit']:
        proof=spec[name];require(sha(Path(proof['file']))==proof['sha256'],'Acceptance evidence changed');inputs[proof['file']]=proof['sha256']
    f={k:str(getattr(a,k).absolute()) for k in ['spec','environments','study','dataset','scorer','embedding']}
    f.update(revision=m.checked(['git','rev-parse','HEAD']),codeHashes=m.base.codehash(),inputs=inputs,datasetSha256=spec['datasetSha256'],CodexRequiredWhileRunning=False)
    check_inputs(f);require(not Path(f['study']).exists(),'Formal study output already exists')
    root.mkdir(parents=True);write(root/'launch.json',f);write(root/'state.json',{'status':'STARTING','formal100Started':False})
    with (root/'background.log').open('ab') as log:child=subprocess.Popen([sys.executable,'-B',Path(__file__).resolve(),'run','--output',root],cwd=P,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    with (root/'cache-maintenance.log').open('ab') as log:cache=subprocess.Popen([sys.executable,'-B',P/'scripts/maintain-swe-build-cache.py','--launch',root],cwd=P,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    write(root/'background.json',{'pid':child.pid,'cachePid':cache.pid})
    print(json.dumps({'pid':child.pid,'cachePid':cache.pid,'output':str(root),'CodexRequiredWhileRunning':False}))
if __name__=='__main__':main()
