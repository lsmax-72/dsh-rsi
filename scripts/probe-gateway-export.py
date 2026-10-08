#!/usr/bin/env python3
"""Actual network-none Docker tmpfs export; no Agent or model requests."""
import argparse,hashlib,importlib.util,json,subprocess,tempfile
from pathlib import Path
P=Path(__file__).resolve().parent.parent
p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
s=importlib.util.spec_from_file_location('runner',P/'scripts/probe-runner.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
cid=subprocess.check_output(['docker','run','-d','--platform','linux/amd64','--network','none','--read-only','--tmpfs','/tmp:rw,uid=1000,gid=1000,mode=700,size=1m','dsh-rsi-formal:django__django-11848','/usr/bin/python3','-c','import time; time.sleep(90)'],text=True).strip()
try:
 fixture=b'\x00 exact Unicode \xe4\xb8\xad\xe6\x96\x87\n'
 subprocess.run(['docker','exec',cid,'/usr/bin/python3','-c',"import pathlib; p=pathlib.Path('/tmp/gateway-evidence'); p.mkdir(); (p/'request-0001.response.bin').write_bytes("+repr(fixture)+"); (p/'request-0001.request.json').write_bytes(b'{}'); (p/'request-0001.summary.json').write_bytes(b'{}')"],check=True)
 with tempfile.TemporaryDirectory() as td:
  out=Path(td);old=subprocess.run(['docker','cp',cid+':/tmp/gateway-evidence',str(out/'old')],capture_output=True,text=True)
  r=m.export_gateway_evidence(cid,out);assert r['returncode']==0 and r['exportedFiles']==3
  assert (out/'gateway-evidence/request-0001.response.bin').read_bytes()==fixture
  info=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0];assert info['HostConfig']['ReadonlyRootfs'] and not info['HostConfig']['Binds'] and info['HostConfig']['NetworkMode']=='none' and info['Config']['User']=='1000:1000'
  result={'status':'PASS_ACTUAL_TMPFS_GATEWAY_EXPORT','containerRuns':1,'realProviderRequests':0,'taskAgentRuns':0,'network':'none','oldDockerCpReturnCode':old.returncode,'method':r['method'],'exportedFiles':3,'fixtureResponseSha256':hashlib.sha256(fixture).hexdigest(),'exactBytesMatch':True,'hostBinds':[],'rootfsReadOnly':True}
finally:subprocess.run(['docker','rm','-f',cid],capture_output=True)
if a.output:a.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
