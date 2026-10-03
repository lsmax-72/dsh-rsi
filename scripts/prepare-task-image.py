#!/usr/bin/env python3
"""Prepare one authorized task image from its official scorer image, exporting public inputs only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True);p.add_argument('--instance',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if any(output.iterdir()):p.error('Preserve previous environment evidence; use an empty directory')
    loader=importlib.util.spec_from_file_location('scorer',Path(__file__).with_name('probe-scorer.py'))
    core=importlib.util.module_from_spec(loader);loader.loader.exec_module(core);distribution,files=core.verify_distribution()
    row=next(r for r in core.pq.read_table(args.dataset).to_pylist() if r['instance_id']==args.instance)
    spec=core.make_test_spec(row,namespace='swebench');spec.arch='x86_64'
    client=core.docker.from_env();key=spec.instance_image_key
    try:image=client.images.get(key)
    except core.docker.errors.ImageNotFound:
        print(json.dumps({'instanceId':args.instance,'phase':'pull-official-image'}),flush=True)
        image=client.images.pull(key,platform='linux/amd64')
    harness=client.images.get('dsh-rsi-container-check:amd64')
    inspect_code="""import subprocess,json,django
run=lambda *a:subprocess.check_output(['git','-C','/testbed',*a],universal_newlines=True).strip()
print(json.dumps({'headCommit':run('rev-parse','HEAD'),'headTime':run('show','-s','--format=%ct','HEAD'),
'headTree':run('rev-parse','HEAD^{tree}'),'baseTree':run('rev-parse',BASE+'^{tree}'),'djangoVersion':django.get_version()}))
""".replace('BASE',repr(row['base_commit']))
    command=['docker','run','--platform','linux/amd64','--rm','--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--memory','2g','--pids-limit','256','-w','/testbed','-e','PYTHONDONTWRITEBYTECODE=1',image.id,
        '/opt/miniconda3/envs/testbed/bin/python','-c',inspect_code]
    environment=json.loads(subprocess.check_output(command,text=True))
    if environment['headTree']!=environment['baseTree']:raise RuntimeError('Official image source is not the public base tree')
    # The dataset and hidden test/gold patches never enter the Docker build context.
    public={key:row[key] for key in ['instance_id','repo','base_commit','problem_statement','version']}
    (output/'task.json').write_text(json.dumps(public)+'\n')
    harness_tag='dsh-rsi-frozen-harness:'+harness.id.split(':')[1]
    scorer_tag='dsh-rsi-frozen-scorer:'+image.id.split(':')[1]
    harness.tag(harness_tag);image.tag(scorer_tag)
    dockerfile=f'''FROM {harness_tag} AS harness
FROM {scorer_tag}
RUN git -C /testbed reset --hard {row['base_commit']} && git -C /testbed clean -fdx && rm -rf /testbed/.git && mv /testbed /opt/task-source && ln -s /workspace /testbed && mkdir -p /state && chown 1000:1000 /state
RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8 LANGUAGE=en_US:en LC_ALL=en_US.UTF-8
COPY --from=harness /usr/local /usr/local
COPY --from=harness /opt/dsh /opt/dsh
COPY --from=harness /opt/rsi /opt/rsi
COPY --from=harness /usr/bin/rg /usr/local/bin/rg
COPY task.json /opt/rsi/task.json
ENV PATH=/opt/dsh/node_modules/.bin:/usr/local/bin:/opt/miniconda3/envs/testbed/bin:/usr/bin:/bin
ENV HOME=/state/user DSH_HOME=/state/home DSH_AGENTS_HOME=/state/agents PYTHONPATH=/workspace PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
USER 1000:1000
'''
    (output/'Dockerfile').write_text(dockerfile)
    tag='dsh-rsi-formal:'+args.instance
    print(json.dumps({'instanceId':args.instance,'phase':'build-task-image'}),flush=True)
    with (output/'build.log').open('w') as log:
        subprocess.run(['docker','build','--platform','linux/amd64','-t',tag,str(output)],check=True,stdout=log,stderr=subprocess.STDOUT)
    assert client.images.get(harness_tag).id==harness.id and client.images.get(scorer_tag).id==image.id
    task=client.images.get(tag)
    if task.attrs['Config']['User']!='1000:1000':raise RuntimeError('Task image must use the isolated UID')
    receipt={'instanceId':args.instance,'taskImage':task.id,'taskTag':tag,'scorerImage':image.id,'scorerKey':key,
        'scorerDigests':image.attrs.get('RepoDigests',[]),'harnessImage':harness.id,'environment':environment,
        'baselineDate':'@'+environment['headTime']+' +0000','swebenchVersion':distribution.version,'verifiedSourceFiles':len(files),
        'publicInputSha256':hashlib.sha256((output/'task.json').read_bytes()).hexdigest(),'modelRequests':0}
    (output/'environment.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt),flush=True)


if __name__=='__main__':main()
