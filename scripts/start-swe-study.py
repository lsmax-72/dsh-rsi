#!/usr/bin/env python3
"""Detached preparation -> build -> freeze -> run -> report; no automatic failed-attempt retry."""
import argparse, fcntl, hashlib, importlib.util, json, os, subprocess, sys, time
from pathlib import Path
P = Path(__file__).resolve().parent.parent

def read(p): return json.loads(p.read_text())
def write(p, value):
    tmp = p.with_suffix(p.suffix + '.tmp'); tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n'); os.replace(tmp,p)
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok, message):
    if not ok: raise RuntimeError(message)
def live(pid):
    try: os.kill(pid,0); return True
    except PermissionError: return True
    except ProcessLookupError: return False

def fingerprint():
    module = importlib.util.spec_from_file_location('runner',P/'scripts/run-swe-expansion.py')
    runner = importlib.util.module_from_spec(module); module.loader.exec_module(runner)
    return {'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=P,text=True).strip(),'code':runner.codehash()}

def command(config, phase):
    """Public import seam for offline tests; production CLI has no fixture switch."""
    prep = [sys.executable,'-B',str(P/'scripts/prepare-swe-environments.py')]
    runner = [sys.executable,'-B',str(P/'scripts/run-swe-expansion.py')]
    if phase == 'prepare-start': return prep+['start','--output',config['environments'],'--spec',config['spec'],'--dataset',config['dataset'],'--python',config['scorer']]
    if phase == 'prepare-run': return prep+['run','--output',config['environments']]
    if phase == 'build': return ['npm','run','build']
    if phase == 'freeze': return runner+['freeze','--output',config['output'],'--spec',config['spec'],'--dataset',config['dataset'],'--scorer-python',config['scorer'],'--environments',config['environments'],'--embedding-model',config['embedding']]
    if phase == 'run': return runner+['run','--output',config['output'],'--resume']
    if phase == 'report': return runner+['report','--output',config['output']]
    raise ValueError(phase)

def execute(argv, log):
    with log.open('x') as stream:
        return subprocess.run(argv,cwd=P,stdout=stream,stderr=subprocess.STDOUT).returncode

def orchestrate(config, control, execute_command=execute, make_command=command, snapshot=fingerprint, pause=time.sleep):
    state = read(control/'state.json'); baseline = read(control/'launch.json')['fingerprint']
    envroot = Path(config['environments']); output = Path(config['output'])
    def stopped(): return (control/'STOP').exists()
    def check_inputs(): require(snapshot()==baseline,'Launch HEAD/code changed; preserve evidence and audit')
    def step(phase):
        state.update(status='RUNNING',phase=phase,updatedAt=time.time()); write(control/'state.json',state)
        require(execute_command(make_command(config,phase),control/(phase+'-'+str(time.time_ns())+'.log'))==0,phase+' failed; no automatic retry')
    try:
        check_inputs()
        if envroot.exists():
            prep = read(envroot/'state.json'); require(prep['status']!='HALTED','Preparation HALTED; manual audit required')
            require(not read(envroot/'preparation.json').get('fixture'),'Fixture environments cannot run a real study')
        else:
            if stopped(): state.update(status='STOPPED',phase='before-prepare'); return
            step('prepare-start'); prep = read(envroot/'state.json')
        if prep['status'] in ['STOPPED','STOPPED_LOW_DISK']:
            if stopped(): state.update(status='STOPPED',phase='before-prepare-resume'); return
            step('prepare-run')
        elif prep['status'] not in ['READY']:
            state.update(phase='prepare-wait'); write(control/'state.json',state)
            while True:
                check_inputs(); prep=read(envroot/'state.json')
                if stopped(): (envroot/'STOP').touch()
                if prep['status'] not in ['PREPARING','STARTING']: break
                require((prep.get('pid') and live(prep['pid'])) or (prep['status']=='STARTING' and time.time()-state.get('updatedAt',time.time())<30),'Preparation worker disappeared; manual audit required')
                pause(5)
        prep=read(envroot/'state.json')
        if stopped() or prep['status'] in ['STOPPED','STOPPED_LOW_DISK']:
            state.update(status='STOPPED',phase='prepare',reason=prep['status']); return
        require(prep['status']=='READY' and len(prep['completed'])==104,'104 environments are not READY')
        check_inputs()
        if stopped(): state.update(status='STOPPED'); return
        if not (output/'protocol.json').exists():
            step('build')
            # Only this explicit pre-freeze build may change generated code bytes.
            after=snapshot(); require(after['head']==baseline['head'],'HEAD changed during build')
            before_source={k:v for k,v in baseline['code'].items() if not k.startswith('lib/')}
            after_source={k:v for k,v in after['code'].items() if not k.startswith('lib/')}
            require(before_source==after_source,'Source changed during build')
            baseline=after; launch=read(control/'launch.json'); launch['fingerprint']=baseline; write(control/'launch.json',launch)
            if stopped(): state.update(status='STOPPED',phase='before-freeze'); return
            step('freeze')
        require(not (output/'HALT').exists(),'Study HALTED; manual audit required')
        check_inputs()
        if stopped(): (output/'STOP').touch(); state.update(status='STOPPED',phase='before-run'); return
        step('run')
        batch=read(output/'batch-state.json'); require(batch['status']!='HALTED','Study HALTED; no automatic retry')
        step('report'); state.update(status=batch['status'],phase='report',summary=batch.get('summary'),output=str(output))
    except Exception as error:
        state.update(status='HALTED',error=str(error))
    finally:
        state['updatedAt']=time.time(); write(control/'state.json',state)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['start','status','stop','_run'])
    p.add_argument('--output',type=Path,default=P/'.artifacts/swe-expansion-study-20261008')
    p.add_argument('--spec',type=Path,default=P/'docs/evidence/swe-expansion-spec-20261008.json')
    p.add_argument('--dataset',type=Path,default=Path('/Users/lsmax/Coder/EvoAgentBench/data/swebench/data/test-00000-of-00001.parquet'))
    p.add_argument('--scorer',type=Path,default=P/'.artifacts/swe-scorer-venv/bin/python')
    p.add_argument('--embedding',type=Path,default=P/'.artifacts/models/embeddinggemma-300m-qat-Q8_0.gguf')
    p.add_argument('--environments',type=Path,default=P/'.artifacts/swe-expansion-environments-v2-20261008')
    a=p.parse_args(); output=a.output.absolute();control=output.with_name(output.name+'-launcher')
    config={k:str(getattr(a,k).absolute()) for k in ['output','spec','dataset','scorer','embedding','environments']}
    if a.action=='status':
        state=read(control/'state.json') if (control/'state.json').exists() else {'status':'NOT_STARTED'}
        state['workerAlive']=bool(state.get('pid') and live(state['pid']))
        if (control/'launch.json').exists():
            saved=read(control/'launch.json')['config']; envstate=Path(saved['environments'])/'state.json'; batch=Path(saved['output'])/'batch-state.json'
            if envstate.exists():
                prep=read(envstate); state['preparation']={k:prep.get(k) for k in ['status','current','error']}; state['preparation']['completed']=len(prep.get('completed',{}))
            if batch.exists():
                study=read(batch); state['study']={'status':study['status'],'closedRuns':sum(r.get('status')=='CLOSED_GRADED' for r in study.get('records',[])),'summary':study.get('summary')}
        print(json.dumps(state,ensure_ascii=False,indent=2));return
    if a.action=='stop':
        require((control/'launch.json').exists(),'Launcher not started');(control/'STOP').touch()
        saved=read(control/'launch.json')['config']
        for root in [Path(saved['environments']),Path(saved['output'])]:
            if root.exists(): (root/'STOP').touch()
        print('STOP requested; in-flight work finishes and preserves evidence');return
    os.environ.setdefault('RSI_MODEL_UPSTREAM','http://10.195.214.152:8100/v1')
    if a.action=='_run':
        with (control/'worker.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);(control/'launch.lock').unlink(missing_ok=True)
            state=read(control/'state.json');state['pid']=os.getpid();write(control/'state.json',state)
            orchestrate(config,control)
        return
    control.mkdir(parents=True,exist_ok=True)
    with (control/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fd=os.open(control/'launch.lock',os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
        try:
            prior=read(control/'state.json') if (control/'state.json').exists() else {}
            require(prior.get('status')!='HALTED','Launcher HALTED; audit before restart')
            require(not (output/'HALT').exists(),'Study HALTED; audit before restart')
            envroot=Path(config['environments'])
            if envroot.exists(): require(read(envroot/'state.json')['status']!='HALTED','Preparation HALTED; audit before restart')
            if (control/'launch.json').exists():
                saved=read(control/'launch.json');require(saved['config']==config and saved['fingerprint']==fingerprint(),'Launch config/HEAD/code changed')
            else: write(control/'launch.json',{'config':config,'fingerprint':fingerprint(),'createdAt':time.time()})
            # Only a new explicit user start clears requested STOP markers.
            for root in [control,envroot,output]: (root/'STOP').unlink(missing_ok=True)
            write(control/'state.json',{'status':'STARTING','phase':'launch','pid':None,'updatedAt':time.time()})
            with (control/('background-'+str(time.time_ns())+'.log')).open('x') as log:
                # Release before worker acquisition; launch.lock rejects intervening starts.
                fcntl.flock(lock,fcntl.LOCK_UN)
                child=subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'_run','--output',config['output'],'--spec',config['spec'],'--dataset',config['dataset'],'--scorer',config['scorer'],'--embedding',config['embedding'],'--environments',config['environments']],cwd=P,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            print(json.dumps({'pid':child.pid,'control':str(control),'output':str(output)}))
        except Exception:
            (control/'launch.lock').unlink(missing_ok=True);raise

if __name__=='__main__':main()
