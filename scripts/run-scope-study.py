#!/usr/bin/env python3
"""Batch the existing isolated scope runner and offline audits; never retry a case."""
import argparse,hashlib,json,os,re,subprocess,sys,time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED

PROJECT=Path(__file__).resolve().parent.parent
IMAGE='dsh-rsi-pilot2:django-11292'

def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,data):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,path)
def check(value,message):
    if not value:raise ValueError(message)
def checked(argv):return subprocess.check_output(argv,cwd=PROJECT,text=True).strip()
def protocol_check(p):
    check(p.get('model')=='qwen3.8-27b' and p.get('provider')=='qwen' and p.get('thinking')=='off','Unexpected model configuration')
    cases=p['cases'];ids=[c['id'] for c in cases]
    check(ids and len(set(ids))==len(ids) and all(re.fullmatch(r'[a-zA-Z0-9_-]+',x) for x in ids),'Invalid or duplicate case IDs')
    check(all(set(c)=={'id','historyBefore','historyAfter','question'} for c in cases),'Only public input fields may enter cases')
    b=p['budgets'];check(all(type(b[k]) is int and b[k]>0 for k in ['backgroundCalls','consumerCalls','totalCalls','wallSeconds']),'Invalid budgets')
    check(b['totalCalls']==b['backgroundCalls']+b['consumerCalls'],'Total call cap differs from stage caps')
    check((b['maxOutputTokens'],b['nativeMaxIterations'],b['nativeCallTimeoutMs'])==(4096,8,180000),'Unsupported native model limits')

def freeze(spec,root,image,workers):
    p=read(spec);protocol_check(p)
    check(not checked(['git','status','--porcelain']),'Commit changes before freezing')
    check(os.environ.get('RSI_MODEL_UPSTREAM'),'RSI_MODEL_UPSTREAM must be the authorized service')
    check(not root.exists() or not any(root.iterdir()),'Freeze requires a new empty output directory')
    files=[f for base in ['src','adapters','vendor','lib','scripts'] for f in (PROJECT/base).rglob('*') if f.is_file() and '__pycache__' not in f.parts and f.suffix not in ['.pyc','.pyo']]
    files += [PROJECT/'package.json',PROJECT/'package-lock.json',PROJECT/'cordis.patch.yml']
    check(any(f.parent==PROJECT/'lib' for f in files),'Build before freezing')
    p.update(status='FROZEN_SYNTHETIC_SCOPE_QUALITY',revision=checked(['git','rev-parse','HEAD']),taskImage=image,taskImageId=checked(['docker','image','inspect','--format','{{.Id}}',image]),upstreamSha256=hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest(),specSha256=sha(spec),inputSha256={str(f.relative_to(PROJECT)):sha(f) for f in sorted(files)},batchWorkers=workers,batchPolicy='Independent isolated cases only; fixed concurrency; no retries; finish in-flight cases but stop dispatch on unknown failure or failed audit')
    root.mkdir(parents=True,exist_ok=True);write(root/'protocol.json',p)
    return p

def validate(p):
    protocol_check(p);check(p['status']=='FROZEN_SYNTHETIC_SCOPE_QUALITY','Protocol is not frozen')
    check(checked(['git','rev-parse','HEAD'])==p['revision'] and not checked(['git','status','--porcelain']),'Frozen revision/clean checkout changed')
    for name,digest in p['inputSha256'].items():
        f=(PROJECT/name).resolve();check(f.is_relative_to(PROJECT) and f.is_file() and sha(f)==digest,'Frozen file changed: '+name)
    check(hashlib.sha256(os.environ.get('RSI_MODEL_UPSTREAM','').encode()).hexdigest()==p['upstreamSha256'],'Model service changed')
    check(checked(['docker','image','inspect','--format','{{.Id}}',p.get('taskImage',IMAGE)])==p['taskImageId'],'Runtime image changed')

def runner_command(p,protocol,root,cid):
    b=p['budgets']
    return [sys.executable,'-B',str(PROJECT/'scripts/probe-runner.py'),'--scope-quality-protocol',str(protocol),'--image',p.get('taskImage',IMAGE),'--arm','rsi','--instance',cid,'--output',str(root/cid),'--dispatch-limit',str(b['consumerCalls']),'--request-limit',str(b['totalCalls']),'--learning-call-budget',str(b['backgroundCalls']),'--learning-dispatch-limit',str(b['backgroundCalls']),'--wall-seconds',str(b['wallSeconds']),'--settle-seconds','0']

def execute(argv,log):
    with log.open('x') as stream:return subprocess.run(argv,cwd=PROJECT,stdout=stream,stderr=subprocess.STDOUT).returncode

def audit_case(root,cid,dest):
    dest.mkdir(parents=True,exist_ok=False);case=root/cid;pilot=case/'state/pilot'/cid
    check(execute([sys.executable,'-B',str(PROJECT/'scripts/audit-scope-quality.py'),'--run',str(case),'--case',cid,'--output',str(dest/'audit.json')],dest/'audit.log')==0,'Case audit failed: '+cid)
    check(execute(['node',str(PROJECT/'scripts/audit-scope-requests.mjs'),str(pilot/'model-requests.json'),str(case/'state/home/sessions'),str(dest/'reconstruction.json')],dest/'reconstruction.log')==0,'Request reconstruction failed: '+cid)
    return read(dest/'audit.json')

def may_continue(code,a,b):
    r=a['receipt'];checks=a['checks']
    common=checks['durablePrefixReconstruction'] and checks['gatewayMatchesDispatches'] and r['unknownActualUsage']==0 and r['backgroundCalls']<=b['backgroundCalls'] and r['consumerCalls']<=b['consumerCalls'] and r['actualRequests']<=b['totalCalls']
    if not common:return False
    if code==0 and r['status']=='COMPLETED_REQUIRES_CONTENT_REVIEW':return all(checks.values())
    # This closes the failed case; it never resumes its checkpoint or reallocates its quota.
    return code!=0 and r['status']=='ERROR' and r.get('code')=='BUDGET_EXHAUSTED' and (r['backgroundCalls']==b['backgroundCalls'] or r['consumerCalls']==b['consumerCalls'])

def summarize(root,p,dest,run_audits=True):
    dest.mkdir(parents=True,exist_ok=False);rows=[];cost={};missing_ledgers=0;embedding=dict(calls=0,failedCalls=0,inputCharacters=0,tokens=None,missingCaseAudits=0)
    for c in p['cases']:
        cid=c['id'];pilot=root/cid/'state/pilot'/cid;a=None;error=None
        receipt=read(pilot/'receipt.json') if (pilot/'receipt.json').exists() else {}
        ledger=pilot/'model-requests.json';requests=read(ledger) if ledger.exists() else []
        missing_ledgers+=not ledger.exists()
        try:
            if receipt:
                a=audit_case(root,cid,dest/cid) if run_audits else read(root/'case-audits'/cid/'audit.json')
                reconstruction=(dest/cid if run_audits else root/'case-audits'/cid)/'reconstruction.json'
                check(reconstruction.exists() and read(reconstruction)['status']=='PASS','Independent reconstruction unavailable or failed')
        except Exception as exc:error=str(exc);a=None
        if a:
            for key in ['calls','failedCalls','inputCharacters']:embedding[key]+=a['embedding'][key]
        else:embedding['missingCaseAudits']+=1
        known=0;unknown=0
        for r in requests:
            key=('background/' if r['background'] else 'consumer/')+r['taskId']
            group='background/skill' if key.startswith('background/skill-') else 'background/scene' if key.startswith('background/scene-') else key
            v=cost.setdefault(group,dict(requests=0,knownTokens=0,inputTokens=0,outputTokens=0,unknownUsage=0));v['requests']+=1
            u=r.get('usage') or {};total=u.get('totalTokens')
            if isinstance(total,(int,float)) and total>0:
                known+=total;v['knownTokens']+=total;v['inputTokens']+=u.get('inputTokens',0);v['outputTokens']+=u.get('outputTokens',0)
            else:unknown+=1;v['unknownUsage']+=1
        rows.append({'caseId':cid,'status':receipt.get('status','NOT_CLOSED'),'code':receipt.get('code'),'knownTokens':known if ledger.exists() else None,'unknownUsage':unknown if ledger.exists() else None,'backgroundCalls':sum(bool(r['background']) for r in requests),'consumerCalls':sum(not r['background'] for r in requests),'mechanism':a['status'] if a else 'AUDIT_UNAVAILABLE','auditError':error,'semanticQuality':'REVIEW_REQUIRED'})
    result={'status':'EXECUTION_SUMMARY_NOT_QUALITY_SCORE','workers':p.get('batchWorkers',1),'cases':rows,'knownChatTokens':sum(r['knownTokens'] or 0 for r in rows),'unknownUsage':sum(r['unknownUsage'] or 0 for r in rows),'missingLedgers':missing_ledgers,'missingReceipts':sum(r['status']=='NOT_CLOSED' for r in rows),'costByTask':cost,'embedding':embedding,'semanticQuality':'REVIEW_REQUIRED','independentEffectClaim':False,'assetAudit':'NOT_RUN_PARTIAL_BATCH'}
    write(dest/'batch-report.json',result)
    if all(r['status']!='NOT_CLOSED' for r in rows) and (root/'run-summary.json').exists():
        try:
            check([r['caseId'] for r in read(root/'run-summary.json')]==[c['id'] for c in p['cases']],'Saved case inventory differs from protocol')
            code=execute(['node',str(PROJECT/'scripts/audit-scope-assets.mjs'),str(root),str(dest/'asset-delivery.json')],dest/'asset-delivery.log')
            result['assetAudit']='PASS' if code==0 else 'FAIL'
        except Exception as exc:result.update(assetAudit='FAIL',assetAuditError=str(exc))
        write(dest/'batch-report.json',result)
    return result

def run_case(root,p,cid):
    start=time.monotonic();result={'status':'HALTED'}
    try:
        code=execute(runner_command(p,root/'protocol.json',root,cid),root/(cid+'.runner.log'));result['exitCode']=code
        a=audit_case(root,cid,root/'case-audits'/cid)
        requests=read(root/cid/'state/pilot'/cid/'model-requests.json')
        service_error=any(r.get('status')=='ERROR' for r in requests)
        result.update(status='CLOSED' if may_continue(code,a,p['budgets']) and not service_error else 'HALTED',receiptStatus=a['receipt']['status'],knownTokens=a['receipt']['knownTokens'],modelRequestError=service_error)
    except Exception as error:result['error']=str(error)
    result['elapsedSeconds']=round(time.monotonic()-start,3)
    return result

def run_batch(root,p,resume):
    protocol=root/'protocol.json';statefile=root/'batch-state.json';lock=root/'batch.lock'
    workers=p.get('batchWorkers',1);check(type(workers) is int and 1<=workers<=3,'Invalid frozen concurrency')
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    try:
        os.write(fd,str(os.getpid()).encode());os.close(fd)
        state=read(statefile) if statefile.exists() else {'protocolSha256':sha(protocol),'workers':workers,'cases':[]}
        check(resume or not state['cases'],'Use --resume to continue unstarted cases')
        check(state['protocolSha256']==sha(protocol),'Protocol changed')
        check(all(r['status']=='CLOSED' for r in state['cases']),'Interrupted/unknown case requires investigation; no automatic retry')
        expected=[c['id'] for c in p['cases']];check([r['caseId'] for r in state['cases']]==expected[:len(state['cases'])],'Saved order differs from protocol')
        next_index=len(state['cases']);halted=False;stopped=False;pending={}
        with ThreadPoolExecutor(max_workers=workers) as pool:
            while next_index<len(expected) or pending:
                stopped=stopped or (root/'STOP').exists()
                while not halted and not stopped and next_index<len(expected) and len(pending)<workers:
                    cid=expected[next_index]
                    try:validate(p);check(not (root/cid).exists(),'Existing case directory must not be retried: '+cid)
                    except Exception as error:
                        state['dispatchError']=str(error);write(statefile,state);halted=True;break
                    row={'caseId':cid,'status':'RUNNING','startedAt':time.time()};state['cases'].append(row);write(statefile,state)
                    print('START '+cid,flush=True);pending[pool.submit(run_case,root,p,cid)]=row;next_index+=1
                if not pending:break
                done,_=wait(pending,return_when=FIRST_COMPLETED)
                # Process every already-completed result before scheduling another independent case.
                for future in done:
                    row=pending.pop(future)
                    try:row.update(future.result())
                    except Exception as error:row.update(status='HALTED',error=str(error))
                    halted=halted or row['status']!='CLOSED';write(statefile,state)
                    write(root/'run-summary.json',[{k:r[k] for k in ['caseId','exitCode','elapsedSeconds']} for r in state['cases'] if 'exitCode' in r])
                    print('END '+row['caseId']+' '+row['status'],flush=True)
        review=root/('batch-review-'+str(time.time_ns()))
        result=summarize(root,p,review,run_audits=False)
        state.update(status='HALTED' if halted else 'STOPPED' if next_index<len(expected) else 'CLOSED_REVIEW_REQUIRED',report=str(review/'batch-report.json'));write(statefile,state)
        print(json.dumps({'status':state['status'],'report':state['report'],'knownChatTokens':result['knownChatTokens']},ensure_ascii=False),flush=True)
        check(not halted and result['assetAudit']!='FAIL','Batch halted or audit failed; inspect saved report before continuing')
    finally:lock.unlink(missing_ok=True)

def start(root,p,resume):
    validate(p);check(not (root/'batch.lock').exists(),'Batch lock exists; inspect status before launch')
    if (root/'batch-state.json').exists():
        previous=read(root/'batch-state.json')['cases']
        check(resume or not previous,'Use --resume for unstarted cases')
        check(all(r['status']=='CLOSED' for r in previous),'Unknown/interrupted cases require investigation before launch')
        check(len(previous)<len(p['cases']),'Batch already finished; use status or report')
    check(not (root/'STOP').exists(),'Remove STOP only when ready to resume unstarted cases')
    argv=[sys.executable,'-B',str(Path(__file__).resolve()),'run','--output',str(root)]
    if resume:argv.append('--resume')
    log=root/('background-'+str(time.time_ns())+'.log')
    # Detached OS process: subsequent dispatch and reporting do not need a live Codex turn.
    with log.open('x') as stream:
        child=subprocess.Popen(argv,cwd=PROJECT,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    receipt={'pid':child.pid,'log':str(log),'startedAt':time.time(),'status':'LAUNCHED_NOT_COMPLETED','model':'qwen3.8-27b','workers':p.get('batchWorkers',1)}
    write(root/'background.json',receipt);print(json.dumps(receipt),flush=True)

def status(root,p):
    state=read(root/'batch-state.json') if (root/'batch-state.json').exists() else {'status':'NOT_STARTED','cases':[]}
    if not (root/'batch-state.json').exists() and (root/'run-summary.json').exists():
        state={'status':'EXTERNAL_RUNS_PRESENT','cases':read(root/'run-summary.json')}
    launch=read(root/'background.json') if (root/'background.json').exists() else None
    lock=root/'batch.lock';pid=int(lock.read_text()) if lock.exists() and lock.read_text().strip() else None
    alive=False
    if pid:
        try:os.kill(pid,0);alive=True
        except ProcessLookupError:pass
    print(json.dumps({'state':state,'launch':launch,'lockPid':pid,'lockPidExists':alive,'plannedCases':len(p['cases']),'maxCalls':len(p['cases'])*p['budgets']['totalCalls']},ensure_ascii=False,indent=2))

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['freeze','plan','run','start','status','report']);parser.add_argument('--output',type=Path,required=True,help='Experiment root; contains protocol.json');parser.add_argument('--spec',type=Path);parser.add_argument('--image',default=IMAGE);parser.add_argument('--workers',type=int,choices=[1,2,3],help='Freeze only: independent cases in flight; default 1');parser.add_argument('--report-dir',type=Path);parser.add_argument('--resume',action='store_true');args=parser.parse_args();root=args.output.resolve()
    if args.mode=='freeze':
        check(args.spec is not None,'freeze requires --spec');p=freeze(args.spec,root,args.image,args.workers or 1);print(json.dumps({'status':p['status'],'cases':len(p['cases']),'newModelCalls':0}));return
    check(args.workers is None,'Concurrency must be chosen during freeze, not changed during a run')
    p=read(root/'protocol.json');protocol_check(p)
    if args.mode=='plan':
        print(json.dumps({'cases':[{'caseId':c['id'],'command':runner_command(p,root/'protocol.json',root,c['id'])} for c in p['cases']],'workers':p.get('batchWorkers',1),'maxBackgroundCalls':len(p['cases'])*p['budgets']['backgroundCalls'],'maxConsumerCalls':len(p['cases'])*p['budgets']['consumerCalls'],'newModelCalls':0},ensure_ascii=False,indent=2));return
    if args.mode=='status':status(root,p);return
    if args.mode=='start':start(root,p,args.resume);return
    if args.mode=='report':
        check(args.report_dir is not None,'report requires a new --report-dir, keeping original outputs intact');r=summarize(root,p,args.report_dir.resolve());print(json.dumps(r,ensure_ascii=False));return
    validate(p);run_batch(root,p,args.resume)

if __name__=='__main__':main()
