#!/usr/bin/env python3
"""Reclaim only unused project build cache under disk pressure; never remove images or state."""
import argparse, hashlib, json, os, re, shutil, subprocess, tempfile, time
from pathlib import Path
MARKERS=('/opt/rsi','/opt/dsh','/opt/task-source','@deepseek-ai/dsh@')
def candidates(rows):
 return [r for r in rows if r.get('Reclaimable') is True and r.get('Shared') is False and re.fullmatch(r'[a-z0-9]+',r.get('ID','')) and any(x in r.get('Description','') for x in MARKERS)]
def alive(pid):
 if not pid:return False
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False

def compact_history(study,audit):
 # Native checkpoints repeatedly carry identical closed logs. APFS clones keep
 # separate inodes and exact bytes while sharing physical blocks, unlike links.
 for file in sorted(study.glob('*.record.json')):
  r=json.loads(file.read_text());pos=r['position'];arm=r['arm'];mark=audit/(f'cloned-{pos:03d}-{arm}.json')
  if r['status'] not in ['CLOSED_GRADED','CLOSED_INFRA'] or pos<2 or mark.exists():continue
  if arm not in ['baseline','rsi']:raise ValueError('Invalid clone checkpoint arm')
  current=json.loads((study/(f'{pos:03d}-{arm}.checkpoint.json')).read_text());old=json.loads((study/(f'{pos-1:03d}-{arm}.checkpoint.json')).read_text())
  if current['arm']!=arm or old['arm']!=arm or current['position']!=pos or old['position']!=pos-1:raise ValueError('Clone checkpoint ownership differs')
  if Path(current['state']).resolve()!=(study/f'{pos:03d}-{arm}/state').resolve() or Path(old['state']).resolve()!=(study/f'{pos-1:03d}-{arm}/state').resolve():raise ValueError('Clone state crossed task/group ownership')
  srcroot=Path(old['state'])/'home/sessions';dstroot=Path(current['state'])/'home/sessions';count=0
  for relative,digest in old['sessions'].items():
   src=srcroot/relative;dst=dstroot/relative
   if not src.resolve().is_relative_to(srcroot.resolve()) or not dst.resolve().is_relative_to(dstroot.resolve()) or src.is_symlink() or dst.is_symlink():raise ValueError('Clone path escapes own study')
   if current['sessions'].get(relative)!=digest or any(hashlib.sha256(p.read_bytes()).hexdigest()!=digest for p in [src,dst]):raise ValueError('Closed historical bytes differ before clone')
   with tempfile.TemporaryDirectory(prefix='history-clone-',dir=audit) as td:
    temporary=Path(td)/'copy';subprocess.run(['/bin/cp','-c','-p',str(src),str(temporary)],check=True)
    if hashlib.sha256(temporary.read_bytes()).hexdigest()!=digest or temporary.stat().st_ino==src.stat().st_ino:raise ValueError('Independent history clone failed')
    os.replace(temporary,dst);count+=1
  mark.write_text(json.dumps({'position':pos,'arm':arm,'files':count,'contentHashesUnchanged':True,'independentInodes':True})+'\n')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--launch',type=Path,required=True);a=p.parse_args();root=a.launch.resolve();f=json.loads((root/'launch.json').read_text());study=Path(f['study']);environment=Path(f['environments']);audit=root/'cache-maintenance';audit.mkdir(exist_ok=True)
 while True:
  state=json.loads((root/'state.json').read_text());prep=json.loads((environment/'state.json').read_text());worker=json.loads((study/'background.json').read_text()) if (study/'background.json').exists() else {}
  if state['status'] in ['HALTED','STOPPED'] or (study/'state.json').exists() and json.loads((study/'state.json').read_text())['status'] in ['COMPLETE','HALTED','STOPPED']:return
  if state['status']=='RUNNER_LAUNCHED' and not alive(worker.get('pid')):return
  if state['status']=='WAITING_ENVIRONMENTS' and not alive(state.get('pid')):return
  if study.exists():compact_history(study,audit)
  if shutil.disk_usage(root).free<30*1024**3:
   output=subprocess.check_output(['docker','buildx','du','--format','{{json .}}'],text=True,timeout=120)
   selected=candidates([json.loads(x) for x in output.splitlines() if x.startswith('{')]);stamp=str(time.time_ns());(audit/(stamp+'.json')).write_text(json.dumps({'freeBytes':shutil.disk_usage(root).free,'selected':selected,'imagesAndAssetsRemoved':False},indent=2))
   for r in selected:
    with (audit/(stamp+'-'+r['ID']+'.log')).open('w') as log:subprocess.run(['docker','buildx','prune','--force','--filter','id='+r['ID']],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=120)
  time.sleep(60)
if __name__=='__main__':main()
