#!/usr/bin/env python3
"""Offline launcher checks using real phase subprocesses; no Docker or model calls."""
import argparse,fcntl,importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
P=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('launcher',P/'scripts/start-swe-study.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args();checks=[]
 with tempfile.TemporaryDirectory() as td:
  base=Path(td);fixture=base/'phase.py'
  fixture.write_text('''import json,sys\nfrom pathlib import Path\nphase,env,out,mode,events=sys.argv[1:]\nE=Path(env);O=Path(out)\nwith open(events,'a') as f:f.write(phase+'\\n')\nif phase=='prepare-run':\n E.mkdir(exist_ok=True);(E/'state.json').write_text(json.dumps({'status':'HALTED' if mode=='fail' else 'READY','completed':list(range(104))}))\n if mode=='fail':sys.exit(7)\nelif phase=='freeze':\n O.mkdir(exist_ok=True);(O/'protocol.json').write_text('{}')\nelif phase=='run':\n (O/'batch-state.json').write_text(json.dumps({'status':'STOPPED' if mode=='stop' else 'COMPLETE','summary':'fixture-summary'}))\n''')
  def setup(name,prep='READY'):
   root=base/name;root.mkdir();env=root/'env';env.mkdir();out=root/'out';control=root/'out-launcher';control.mkdir();events=root/'events'
   m.write(env/'state.json',{'status':prep,'completed':list(range(104))});m.write(env/'preparation.json',{'fixture':False})
   cfg={'output':str(out),'environments':str(env),'spec':'fixture-spec','dataset':'fixture-data','scorer':'fixture-python','embedding':'fixture-gguf'};finger={'head':'fixture-head','code':{'scripts/source.py':'same'}}
   m.write(control/'state.json',{'status':'STARTING'});m.write(control/'launch.json',{'fingerprint':finger,'config':cfg})
   return cfg,control,events,finger
  def commands(cfg,events,mode='ok'):
   return lambda cfg,phase:[sys.executable,'-B',str(fixture),phase,cfg['environments'],cfg['output'],mode,str(events)]
  cfg,control,events,finger=setup('complete');m.orchestrate(cfg,control,make_command=commands(cfg,events),snapshot=lambda:finger)
  assert m.read(control/'state.json')['status']=='COMPLETE';assert events.read_text().splitlines()==['build','freeze','run','report'];checks.append('real phase subprocesses complete build freeze run report and independent controller returns')
  cfg,control,events,finger=setup('detached');harness=base/'controller.py';harness.write_text('''import importlib.util,json,sys\nfrom pathlib import Path\ns=importlib.util.spec_from_file_location('launcher',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)\ncfg=json.loads(sys.argv[2]);control=Path(sys.argv[3]);fixture=sys.argv[4];events=sys.argv[5];finger=json.loads(sys.argv[6])\nm.orchestrate(cfg,control,make_command=lambda cfg,phase:[sys.executable,'-B',fixture,phase,cfg['environments'],cfg['output'],'ok',events],snapshot=lambda:finger)\nassert m.read(control/'state.json')['status']=='COMPLETE'\n''')
  child=subprocess.Popen([sys.executable,'-B',str(harness),str(P/'scripts/start-swe-study.py'),json.dumps(cfg),str(control),str(fixture),str(events),json.dumps(finger)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
  stdout,stderr=child.communicate(timeout=20);assert child.returncode==0,stderr.decode();assert events.read_text().splitlines()==['build','freeze','run','report'];checks.append('separate detached controller process completes all phases and exits without live caller orchestration')
  cfg,control,events,finger=setup('prepare-fail','STOPPED');m.orchestrate(cfg,control,make_command=commands(cfg,events,'fail'),snapshot=lambda:finger)
  assert m.read(control/'state.json')['status']=='HALTED';assert events.read_text().splitlines()==['prepare-run'];assert not Path(cfg['output']).exists();checks.append('preparation subprocess failure is HALTED and never freezes or runs')
  cfg,control,events,finger=setup('codechange');m.orchestrate(cfg,control,make_command=commands(cfg,events),snapshot=lambda:{'head':'changed','code':finger['code']})
  assert m.read(control/'state.json')['status']=='HALTED' and not events.exists();checks.append('launch fingerprint change rejects every phase before dispatch')
  cfg,control,events,finger=setup('stop');(control/'STOP').touch();m.orchestrate(cfg,control,make_command=commands(cfg,events),snapshot=lambda:finger)
  assert m.read(control/'state.json')['status']=='STOPPED' and not events.exists();(control/'STOP').unlink();m.orchestrate(cfg,control,make_command=commands(cfg,events,'stop'),snapshot=lambda:finger)
  assert m.read(control/'state.json')['status']=='STOPPED';m.orchestrate(cfg,control,make_command=commands(cfg,events),snapshot=lambda:finger)
  assert m.read(control/'state.json')['status']=='COMPLETE';assert events.read_text().splitlines()==['build','freeze','run','report','run','report'];checks.append('STOP dispatches nothing and explicit closed-state continuation reuses frozen protocol')
  cfg,control,events,finger=setup('halted','HALTED');m.orchestrate(cfg,control,make_command=commands(cfg,events),snapshot=lambda:finger)
  assert m.read(control/'state.json')['status']=='HALTED' and not events.exists();checks.append('HALTED preparation has no automatic retry')
  cfg,control,events,finger=setup('cli');argv=[sys.executable,'-B',str(P/'scripts/start-swe-study.py')]
  flags=['--output',cfg['output'],'--environments',cfg['environments']]
  result=subprocess.run(argv+['status']+flags,capture_output=True,text=True);assert result.returncode==0 and json.loads(result.stdout)['status']=='STARTING'
  result=subprocess.run(argv+['stop']+flags,capture_output=True,text=True);assert result.returncode==0 and (control/'STOP').exists() and (Path(cfg['environments'])/'STOP').exists()
  with (control/'worker.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);result=subprocess.run(argv+['start']+flags,capture_output=True,text=True);assert result.returncode!=0 and not (control/'launch.lock').exists()
  checks.append('actual CLI subprocess status and STOP work and live worker lock rejects second start')
 result={'status':'PASS_OFFLINE_STUDY_CONTROLLER','realModelRequests':0,'dockerOperations':0,'checks':checks,'phaseExecution':'real local fixture subprocesses; public orchestration import seam'}
 if args.output:m.write(args.output,result)
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
