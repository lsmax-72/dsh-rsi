#!/usr/bin/env python3
"""Verify official native-history import with explicit fixture chat/encoding; no real model calls."""
import sys,json,os,tempfile,subprocess,argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--system-boundaries',action='store_true');args=p.parse_args()
project=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(project/'scripts'))
from fixture_embedding_server import EmbeddingFixtureServer
with tempfile.TemporaryDirectory(prefix='rsi-personamem-import-') as temp,EmbeddingFixtureServer() as embedding:
 root=Path(temp)
 patch=[{'id':i,'disabled':True} for i in ['sdk-app-startup','sdk-jsonrpc-server','llm-deepseek']]+[{'insert':[{'id':'rsi-skills','name':'@deepseek-ai/dsh-skill'},{'id':'rsi-fixture','name':str(project/'lib/index.js'),'config':{'embedding':embedding.config,'dataDir':str(root/'assets'),'cwd':str(root),'provider':'personamem-fixture','model':'fixture','l2DelaySeconds':86400,'settings':{'idleSeconds':1} if args.system_boundaries else {}}},{'id':'personamem-import','name':str(project/'scripts/personamem-import-probe.mjs'),'config':{'root':str(root),'input':str(args.input.resolve()),'systemBoundaries':args.system_boundaries}}]}]
 (root/'patch.json').write_text(json.dumps(patch))
 env=dict(os.environ,DSH_HOME=str(root/'home'),DSH_AGENTS_HOME=str(root/'agents'))
 r=subprocess.run(['/Applications/DeepSeek Harness.app/Contents/Resources/runtime/cli/bin/dsh','--profile','sdk-minimal','--patch',str(root/'patch.json')],env=env,cwd=root,capture_output=True,text=True,timeout=90)
 if r.returncode or not (root/'receipt.json').exists():raise RuntimeError(r.stdout+r.stderr)
 receipt=(root/'receipt.json').read_text();args.output.write_text(receipt);print(receipt)
