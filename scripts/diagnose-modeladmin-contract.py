#!/usr/bin/env python3
"""Read-only public diagnostic for a saved development patch; no model, gold or learning."""
import argparse,json,subprocess,hashlib
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--image',default='dsh-rsi-formal:django__django-11095');args=p.parse_args();assert not args.output.exists()
patch=args.patch.read_text()
probe='''from django.conf import settings
settings.configure(INSTALLED_APPS=[], SECRET_KEY='isolated-public-diagnostic')
import django
django.setup()
from django.db import models
from django.contrib.admin import AdminSite, ModelAdmin
class Target(models.Model):
    external_key=models.CharField(max_length=10, unique=True)
    class Meta:
        app_label='public_contract_diagnostic'
class RequestGuardAdmin(ModelAdmin):
    def get_inlines(self, request, obj=None):
        assert request is not None, 'public regression: request contract violated'
        return []
site=AdminSite()
site.register(Target, RequestGuardAdmin)
print(site._registry[Target].to_field_allowed(object(), 'external_key'))
'''
container='''import json,sys,shutil,subprocess,hashlib
from pathlib import Path
x=json.load(sys.stdin);root=Path('/tmp/public-source');shutil.copytree('/opt/task-source',root)
path=root/'django/contrib/admin/options.py';original=path.read_text();signature='def to_field_allowed(self, request, to_field):';assert signature in original
before=subprocess.run([sys.executable,'-c',x['probe']],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
apply=subprocess.run(['git','apply','-'],input=x['patch'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True);assert apply.returncode==0,apply.stderr
# Each process imports from its own current source tree; bytecode writes are disabled by the image.
after=subprocess.run([sys.executable,'-c',x['probe']],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True)
assert before.returncode==0,before.stderr
assert after.returncode!=0 and 'public regression: request contract violated' in after.stderr,after.stdout+after.stderr
print(json.dumps({'status':'REGRESSION_REPRODUCED','baseline':{'exitCode':before.returncode,'stdout':before.stdout,'stderr':before.stderr},'savedPatch':{'exitCode':after.returncode,'stdout':after.stdout,'stderr':after.stderr},'sourceMethodSignature':signature,'sourceSha256':hashlib.sha256(original.encode()).hexdigest(),'patchSha256':hashlib.sha256(x['patch'].encode()).hexdigest(),'probeSha256':hashlib.sha256(x['probe'].encode()).hexdigest(),'modelRequests':0,'hiddenTestsOrGoldUsed':False,'scorerResultsReturnedToLearning':False,'limitation':'Public caller-contract counterexample only. Does not overwrite the saved official resolved score.'}))
'''
image=json.loads(subprocess.check_output(['docker','image','inspect',args.image],text=True))[0]['Id']
r=subprocess.run(['docker','run','--rm','-i','--platform','linux/amd64','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--pids-limit','64','--tmpfs','/tmp:rw,exec,uid=1000,gid=1000,mode=700,size=512m',args.image,'/opt/miniconda3/envs/testbed/bin/python','-c',container],input=json.dumps({'patch':patch,'probe':probe}),stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=90)
assert r.returncode==0,r.stdout+r.stderr
receipt=json.loads(r.stdout);receipt['imageId']=image;receipt['imageTag']=args.image;args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
