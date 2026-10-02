#!/usr/bin/env python3
"""Check qwen3.8-27b through the official dsh adapter and an isolated model-only gateway."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import urllib.parse
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream',required=True,help='Declared OpenAI-compatible endpoint ending in /v1; no embedded credential')
    parser.add_argument('--base-image',default='dsh-rsi-container-check:local')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    url=urllib.parse.urlsplit(args.upstream)
    if url.scheme not in ['http','https'] or not url.hostname or url.username or url.password or url.query or url.fragment or url.path.rstrip('/')!='/v1':
        parser.error('Use a declared HTTP(S) model endpoint ending in /v1 without embedded credentials.')
    sys.dont_write_bytecode=True
    project=Path(__file__).resolve().parent.parent
    spec=importlib.util.spec_from_file_location('container_probe',project/'scripts/probe-container.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    network='rsi-model-'+uuid.uuid4().hex[:10];image=network+':local';containers=[]
    policy=['--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--cpus','2','--memory','2g','--pids-limit','256',
            '--tmpfs','/tmp:rw,exec,uid=1000,gid=1000,mode=700,size=128m',
            '--tmpfs','/state:uid=1000,gid=1000,mode=700,size=256m',
            '--tmpfs','/workspace:uid=1000,gid=1000,mode=700,size=64m']
    def run(*command,**kwargs):return subprocess.run(command,check=True,text=True,**kwargs)
    with tempfile.TemporaryDirectory(prefix='rsi-model-') as temp:
        root=Path(temp)
        for file in ['model-gateway.py','model-probe.mjs']:shutil.copy2(project/'scripts'/file,root/file)
        overlay=helper.overlay('oneshot',str(root/'marker'))
        overlay[-1]['insert']=[r for r in overlay[-1]['insert'] if r['id']!='rsi-probe']
        overlay[-1]['insert'] += [
            {'id':'rsi-credentials','name':'@deepseek-ai/dsh-credentials-local','config':{'path':'/state/credentials.yml','watch':False}},
            {'id':'rsi-qwen','name':'@deepseek-ai/dsh-llm-pi-ai','config':{'providers':{'qwen':{'api':'openai-completions','apiKeyEnv':'QWEN_API_KEY','baseURL':'http://model:8080/v1','defaultContextWindow':262144,'models':[{'id':'qwen3.8-27b','name':'qwen3.8-27b'}],'retryPolicy':{'mode':'normal','maxRetries':0}}}}},
            {'id':'rsi-model-probe','name':'/opt/rsi/scripts/model-probe.mjs'},
        ]
        (root/'model.json').write_text(json.dumps(overlay))
        # A single FROM argument keeps caller-controlled image names outside Dockerfile syntax.
        (root/'Dockerfile').write_text('ARG BASE_IMAGE\nFROM ${BASE_IMAGE}\nUSER root\nCOPY model-gateway.py model-probe.mjs model.json /opt/rsi/scripts/\nUSER node\n')
        run('docker','build','--build-arg','BASE_IMAGE='+args.base_image,'-t',image,str(root))
        run('docker','network','create','--internal',network,stdout=subprocess.DEVNULL)
        try:
            gateway=subprocess.check_output(['docker','run','-d','--network',network,'--network-alias','model',*policy,
                '-e','RSI_MODEL_UPSTREAM='+args.upstream,'-e','RSI_MODEL_REQUEST_LIMIT=12',image,'python3','/opt/rsi/scripts/model-gateway.py'],text=True).strip()
            containers.append(gateway);run('docker','network','connect','bridge',gateway)
            check="""const assert=require('node:assert/strict'),net=require('node:net');(async()=>{
const r=await fetch('http://model:8080/v1/models');assert.equal(r.status,200);assert.ok((await r.json()).data.some(m=>m.id==='qwen3.8-27b'));
assert.equal((await fetch('http://model:8080/https://github.com')).status,403);
assert.equal((await fetch('http://model:8080/v1/chat/completions',{method:'POST',body:JSON.stringify({model:'wrong',messages:[]})})).status,400);
await new Promise((resolve,reject)=>{const s=net.connect({host:'1.1.1.1',port:443});s.once('connect',()=>{s.destroy();reject(Error('Public network reachable'))});s.once('error',resolve);s.setTimeout(1000,()=>{s.destroy();resolve()})});console.log('MODEL_EGRESS_PASS');})().catch(e=>{console.error(e);process.exit(1)});"""
            run('docker','run','--rm','--network',network,*policy,image,'node','-e',check)
            cid=subprocess.check_output(['docker','create','--init','--network',network,*policy,'-e','QWEN_API_KEY=EMPTY',image,'dsh','--profile','sdk-minimal','--patch','/opt/rsi/scripts/model.json'],text=True).strip()
            containers.append(cid)
            output=run('docker','start','-a',cid,capture_output=True,timeout=300)
            state=json.loads(subprocess.check_output(['docker','inspect',cid],text=True))[0]['State']
            if state['ExitCode'] or state['OOMKilled']:raise RuntimeError(output.stdout+output.stderr)
            receipt=next(json.loads(line) for line in output.stdout.splitlines() if line.startswith('{"status"'))
            count=len(subprocess.check_output(['docker','logs',gateway],text=True).splitlines())
            assert count==receipt['requests']
            receipt.update(networkInternal=True,modelGatewayOnly=True,gatewayRequests=count,
                           limitation='The declared model API is visible to every container process. Generic web and external network are blocked. No benchmark task.')
        finally:
            for cid in containers:run('docker','rm','-f',cid,stdout=subprocess.DEVNULL)
            run('docker','network','rm',network,stdout=subprocess.DEVNULL)
    encoded=json.dumps(receipt,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(encoded)
    print(encoded,end='')


if __name__=='__main__':main()
