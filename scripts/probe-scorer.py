#!/usr/bin/env python3
"""Validate a clean official SWE-bench scorer with positive and nonempty negative Django patches."""
import argparse
import base64
import dataclasses
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import uuid
import docker
import pyarrow.parquet as pq
from swebench.harness.constants import RUN_EVALUATION_LOG_DIR
from swebench.harness.grading import get_logs_eval
from swebench.harness.run_evaluation import run_instance
from swebench.harness.test_spec.test_spec import make_test_spec


def verify_distribution():
    distribution=importlib.metadata.distribution('swebench')
    assert distribution.version=='3.0.0','Use the pinned clean official swebench==3.0.0 environment.'
    files=[f for f in distribution.files if str(f).endswith('.py') and f.hash]
    for file in files:
        digest=base64.urlsafe_b64encode(hashlib.sha256(distribution.locate_file(file).read_bytes()).digest()).decode().rstrip('=')
        assert digest==file.hash.value,'Modified scorer source: '+str(file)
    return distribution,files


def isolated_client():
    client=docker.from_env();create=client.containers.create
    def isolated_create(*a,**kwargs):
        # Only runtime resource/network setup changes; official test generation and grading stay intact.
        kwargs.update(network_mode='none',mem_limit='2g',pids_limit=256,cap_drop=['ALL'],security_opt=['no-new-privileges'])
        return create(*a,**kwargs)
    client.containers.create=isolated_create
    return client


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True,help='Official SWE-bench Verified parquet; grader-only data')
    parser.add_argument('--work-dir',type=Path,required=True,help='Separate scorer directory outside all Agent mounts')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    dataset=args.dataset.resolve();output=args.output.resolve();work=args.work_dir.resolve()
    distribution,files=verify_distribution()
    rows={r['instance_id']:r for r in pq.read_table(dataset).to_pylist()}
    work.mkdir(parents=True,exist_ok=True);os.chdir(work)
    client=isolated_client()
    cases=[]
    for instance in ['django__django-10973','django__django-11292']:
        row=rows[instance];spec=make_test_spec(row,namespace='swebench');spec.arch='x86_64'
        (work/(instance+'.spec.json')).write_text(json.dumps(dataclasses.asdict(spec)))
        for condition in ['oracle','wrong']:
            # Gold/test patches stay in this scorer process; never export them to task containers.
            patch=row['patch'] if condition=='oracle' else 'diff --git a/django/__init__.py b/django/__init__.py\n--- a/django/__init__.py\n+++ b/django/__init__.py\n@@ -0,0 +1 @@\n+# RSI incorrect preflight patch: deliberately leaves the issue unresolved.\n'
            prediction={'instance_id':instance,'model_name_or_path':'rsi-scorer-preflight','model_patch':patch}
            run_id='rsi-'+condition+'-'+uuid.uuid4().hex[:10]
            result=run_instance(spec,prediction,False,False,client,run_id,timeout=300)
            if result is None:raise RuntimeError('INFRA: no official report; inspect '+run_id)
            _,report=result
            log=RUN_EVALUATION_LOG_DIR/run_id/'rsi-scorer-preflight'/instance/'test_output.txt'
            states,parsed=get_logs_eval(spec,str(log))
            assert parsed and set(spec.FAIL_TO_PASS).issubset(states),'Missing real FAIL_TO_PASS test outcomes'
            assert report[instance]['resolved']==(condition=='oracle'),report
            case={'instanceId':instance,'condition':condition,'resolved':report[instance]['resolved'],
                  'failToPassTests':len(spec.FAIL_TO_PASS),'parsedTests':len(states),'runId':run_id,
                  'testLogSha256':hashlib.sha256(log.read_bytes()).hexdigest()}
            cases.append(case);print(json.dumps(case),flush=True)
    receipt={'status':'PASS','swebenchVersion':distribution.version,'verifiedSourceFiles':len(files),
             'datasetSha256':hashlib.sha256(dataset.read_bytes()).hexdigest(),'cases':cases,
             'realProviderRequests':0,'limitation':'Scorer controls only; no Agent task or product-effect claim.'}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(receipt,indent=2)+'\n')


if __name__=='__main__':main()
