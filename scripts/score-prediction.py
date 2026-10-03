#!/usr/bin/env python3
"""Grade one saved patch with the verified official scorer; no Agent or model is run."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import uuid


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--instance',required=True)
    parser.add_argument('--prediction',type=Path,required=True)
    parser.add_argument('--work-dir',type=Path,required=True,help='Grader-only directory, never passed to task images')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve();prediction=args.prediction.resolve();dataset=args.dataset.resolve();work=args.work_dir.resolve()
    if output.exists() or output in [prediction,dataset]: parser.error('Do not overwrite predictions, dataset or previous scores')
    path=Path(__file__).with_name('probe-scorer.py')
    loader=importlib.util.spec_from_file_location('verified_scorer',path);core=importlib.util.module_from_spec(loader);loader.loader.exec_module(core)
    from swebench.harness.grading import get_eval_report
    from swebench.harness.constants import APPLY_PATCH_FAIL,LOG_INSTANCE
    distribution,files=core.verify_distribution()
    row=next(r for r in core.pq.read_table(dataset).to_pylist() if r['instance_id']==args.instance)
    spec=core.make_test_spec(row,namespace='swebench');spec.arch='x86_64'
    client=core.isolated_client()
    client.images.get(spec.instance_image_key) # Fail before execution if the scorer image is not already cached.
    raw=prediction.read_bytes();patch=raw.decode();name='rsi-saved-prediction';run_id='rsi-score-'+uuid.uuid4().hex[:10]
    pred={'instance_id':args.instance,'model_name_or_path':name,'model_patch':patch if patch else None}
    work.mkdir(parents=True,exist_ok=True);os.chdir(work)
    report=None;method='official-run-instance';test_sha=None
    if not patch:
        report=get_eval_report(spec,pred,'unused-for-empty-prediction',True);method='official-empty-prediction-report'
    else:
        result=core.run_instance(spec,pred,False,False,client,run_id,timeout=300)
        logdir=core.RUN_EVALUATION_LOG_DIR/run_id/name/args.instance
        if result:
            _,report=result
            logfile=logdir/'test_output.txt';test_sha=hashlib.sha256(logfile.read_bytes()).hexdigest()
        elif (logdir/LOG_INSTANCE).is_file() and APPLY_PATCH_FAIL in (logdir/LOG_INSTANCE).read_text():
            # Preserve official invalid-patch semantics, without turning every missing report into INFRA.
            report=get_eval_report(spec,pred,str(logdir/LOG_INSTANCE),True);method='official-patch-apply-failure-report'
    receipt={'instanceId':args.instance,'status':'GRADED' if report else 'UNCLASSIFIED_NO_REPORT',
        'resolved':report[args.instance]['resolved'] if report else None,'officialReport':report,
        'method':method,'runId':run_id,'patchBytes':len(raw),'patchSha256':hashlib.sha256(raw).hexdigest(),
        'testOutputSha256':test_sha,'swebenchVersion':distribution.version,'verifiedSourceFiles':len(files),
        'modelRequests':0,'limitation':'Score for one saved patch only. Missing reports require independent fault classification; no paired-effect claim.'}
    output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps({k:v for k,v in receipt.items() if k!='officialReport'}))


if __name__=='__main__':main()
