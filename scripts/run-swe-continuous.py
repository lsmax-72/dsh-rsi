#!/usr/bin/env python3
"""Serial, persistent SWE sequence using the existing native task and official scorer."""
import argparse, fcntl, hashlib, importlib.util, json, os, random, re, shutil, sqlite3, subprocess, sys, tempfile, time
from pathlib import Path
P=Path(__file__).resolve().parent.parent
ARMS=['baseline','rsi'];TERMINAL={'CLOSED_GRADED','CLOSED_INFRA'}
EMBEDDING_SHA='6fa0c02a9c302be6f977521d399b4de3a46310a4f2621ee0063747881b673f67'
def load(name):
    spec=importlib.util.spec_from_file_location(name,P/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
base=load('run-swe-expansion');thinking=load('run-thinking-preexperiment');native=load('probe-runner');budget=load('learning-budget')
read,write,sha,require=base.read,base.write,base.sha,base.check

def checked(argv):return subprocess.check_output([str(x) for x in argv],cwd=P,text=True,timeout=30).strip()
def files(root):
    require(root.is_dir(),'Missing closed state directory')
    require(not any(p.is_symlink() for p in root.rglob('*')),'State symlinks cannot enter another task')
    return base.files(root)
def rows(root):return [read(p) for p in sorted(root.glob('*.record.json'))]
def key(position,arm):return f'{position:03d}-{arm}'
def record_file(root,position,arm):return root/(key(position,arm)+'.record.json')
def order(s):return [c['instanceId'] for c in s['cases']]

def mechanism_hashes(allcode=None):
    # Pin the production core and actual task/gateway implementation tested by
    # the development acceptance. Report-only changes do not claim new proof.
    allcode=base.codehash() if allcode is None else allcode
    inputs={'scripts/run-swe-continuous.py','scripts/probe-runner.py','scripts/pilot-task.mjs','scripts/task-input.mjs','scripts/model-gateway.py','scripts/audit-session-requests.mjs'}
    return {k:v for k,v in allcode.items() if not k.startswith('scripts/') or k in inputs}

def asset_inventory(state):
    memories=[];skills=[]
    if not (state/'assets').exists():return {'memories':memories,'skills':skills}
    # Analyze copies so opening SQLite/WAL cannot alter the carried native state.
    with tempfile.TemporaryDirectory() as td:
        for index,f in enumerate((state/'assets').rglob('*.sqlite')):
            if f.name not in ['memory.sqlite','skills.sqlite']:continue
            target=Path(td)/str(index);shutil.copyfile(f,target)
            for suffix in ['-wal','-shm']:
                if Path(str(f)+suffix).exists():shutil.copyfile(Path(str(f)+suffix),Path(str(target)+suffix))
            db=sqlite3.connect(target);db.row_factory=sqlite3.Row
            try:
                if f.name=='memory.sqlite':
                    for r in db.execute('SELECT record_id,content FROM l1_records'):
                        memories.append({'scope':f.parent.name,'id':r['record_id'],'bodyChars':len(r['content']),'bodySha256':hashlib.sha256(r['content'].encode()).hexdigest()})
                else:
                    for r in db.execute('SELECT skill_id,name,version,content FROM skills WHERE is_head=1'):
                        body=re.sub(r'^---\s*\n[\s\S]*?\n---\s*\n','',r['content']).strip()
                        skills.append({'scope':f.parent.name,'id':r['skill_id'],'name':r['name'],'version':r['version'],'bodyChars':len(body),'bodySha256':hashlib.sha256(body.encode()).hexdigest()})
            finally:db.close()
    return {'memories':memories,'skills':skills}

def asset_delta(before,after):
    result={}
    for kind in ['memories','skills']:
        old={(r['scope'],r['id']):r for r in before[kind]};new={(r['scope'],r['id']):r for r in after[kind]}
        result[kind]={'created':sum(k not in old for k in new),'updated':sum(k in old and old[k]!=r for k,r in new.items()),'removed':sum(k not in new for k in old),'headCount':len(new),'headBodyChars':sum(r['bodyChars'] for r in new.values())}
    return result

def embedding_cost(state,previous):
    calls=[];gaps=[]
    for f in (state/'assets').rglob('embedding.log'):
        text=f.read_text();relative=f.relative_to(state);old=previous/relative if previous else None
        if old and old.exists():
            prior=old.read_text()
            if not text.startswith(prior):gaps.append(str(relative));continue
            text=text[len(prior):]
        for line in text.splitlines():
            if 'rsi.embedding.call ' in line:calls.append(json.loads(line.split('rsi.embedding.call ',1)[1]))
    return {'calls':len(calls),'inputChars':sum(r['input_chars'] for r in calls),'wallMs':sum(r['duration_ms'] for r in calls),'errors':sum(r['status']!='completed' for r in calls),'unknownTokenUsageCalls':sum(r.get('token_usage') is None for r in calls),'inheritedLogOrRotationGaps':gaps,'tokens':None,'note':'Native local embedding cost is separate; characters are not estimated tokens. Carried historical calls excluded.'}

def spec_check(s):
    ids=order(s);b=s['budgets']
    require(s['model']=='qwen3.8-27b' and s['thinking']=='off' and s['thinkingConfirmed'] is True,'Only confirmed Thinking Off deployment is supported')
    require(s['budgetConfirmed'] is True,'Confirm all scoped budgets before freeze or dispatch')
    require(ids and len(ids)==len(set(ids)) and all(re.fullmatch(r'django__django-\d+',id) for id in ids),'Invalid ordered Django tasks')
    require(s['serial'] is True and s['emptyStart'] is True and s['stageSize']==20 and s['confidenceInterval'] is None and s['historyMode']=='native-fork','Wrong continuous protocol')
    require(all(type(b.get(k)) is int and b[k]>0 for k in ['foregroundCalls','wallSeconds','maxOutputTokens','learningCallsPerTask','learningTotal','settleSeconds']),'Missing positive frozen budgets')
    require(b['maxOutputTokens']==8192 and b['learningTotal']==len(ids)*b['learningCallsPerTask'] and b['learningTotal']<=100000,'Invalid output or whole-study learning pool')
    if s['purpose']=='development':
        require(ids==thinking.IDS[:2],'Development handoff uses the first two exposed tasks in original order')
    elif s['purpose']=='formal':
        origin=read(P/'docs/evidence/swe-expansion-spec-20261008.json');expected=[c['instanceId'] for c in origin['manifest']['heldOut']];random.Random(20261008).shuffle(expected)
        require(s['orderSeed']==20261008 and s['sourceManifestSha256']==sha(P/'docs/evidence/swe-expansion-spec-20261008.json'),'Wrong formal selection provenance')
        require(len(ids)==100 and ids==expected and not set(ids)&set(origin['excluded']),'Formal tasks/order differ or contain exposed cases')
        audit=s.get('inheritanceAudit');require(audit and Path(audit['file']).is_file() and sha(Path(audit['file']))==audit['sha256'],'Missing frozen real inheritance evidence')
        proof=read(Path(audit['file']));require(proof['status']=='PASS_REAL_CONTINUOUS_STATE' and proof['realModelRequests']>0 and proof['arms']==ARMS and proof['memoryBodyConsumed'] and proof['skillBodyConsumed'],'Real raw-history and both-asset consumption proof required')
        require(proof.get('mechanismSha256')==mechanism_hashes(),'Inherited-state proof was not generated by the current implementation')
    else:raise ValueError('Unknown experiment purpose')

def validate(s,case=None):
    spec_check(s)
    require(checked(['git','rev-parse','HEAD'])==s['revision'] and not checked(['git','status','--porcelain']),'Frozen checkout changed')
    require(base.codehash()==s['codeHashes'],'Frozen code inventory changed')
    require(sha(Path(s['dataset']))==s['datasetSha256'] and sha(Path(s['embeddingModel']))==s['embeddingSha256'],'Frozen data/embedding changed')
    require(hashlib.sha256(os.environ.get('RSI_MODEL_UPSTREAM','').encode()).hexdigest()==s['upstreamSha256'],'Frozen service endpoint changed')
    for c in ([case] if case else s['cases']):
        f=Path(c['environmentFile']);require(sha(f)==c['environmentSha256'] and sha(f.parent/'task.json')==c['publicInputSha256'],'Frozen public bytes changed')
        for tag,keyname in [(c['taskTag'],'taskImageId'),(c['scorerKey'],'scorerImageId')]:require(checked(['docker','image','inspect','--format','{{.Id}}',tag])==c[keyname],'Frozen task/scorer image changed')

def freeze_here(a):
    root=a.output.resolve();require(not root.exists(),'Preserve prior experiment output');s=read(a.spec);spec_check(s)
    require(not checked(['git','status','--porcelain']),'Commit implementation before freeze')
    require((P/'lib/index.js').is_file(),'Build artifacts missing')
    require(sha(a.dataset)==s['datasetSha256'] and sha(a.embedding)==EMBEDDING_SHA,'Wrong dataset/native embedding')
    checked([a.scorer,'-B','-c',"import importlib.util; q=importlib.util.spec_from_file_location('scorer','scripts/probe-scorer.py'); m=importlib.util.module_from_spec(q); q.loader.exec_module(m); m.verify_distribution()"])
    s.update(revision=checked(['git','rev-parse','HEAD']),codeHashes=base.codehash(),dataset=str(a.dataset.resolve()),scorerPython=str(a.scorer.absolute()),embeddingModel=str(a.embedding.resolve()),embeddingSha256=sha(a.embedding),upstreamSha256=hashlib.sha256(os.environ['RSI_MODEL_UPSTREAM'].encode()).hexdigest(),modelIdentity=thinking.model_identity(),weightsHash=None,frozenWorktree=str(P),frozenAt=time.time())
    validate(s);root.mkdir(parents=True);write(root/'protocol.json',s);(root/'protocol.sha256').write_text(sha(root/'protocol.json')+'\n')
    write(root/'state.json',{'status':'FROZEN','completedRuns':0,'plannedRuns':2*len(s['cases'])});return s

def freeze(a):
    # Freeze a separate checkout, including ignored built artifacts. A user's
    # edits/branch changes in the main checkout must not stop the background run.
    if a.frozen_here:return freeze_here(a)
    require(not checked(['git','status','--porcelain']),'Commit implementation before freeze')
    spec_check(read(a.spec));root=a.output.resolve();require(not root.exists(),'Output already exists')
    work=root.with_name(root.name+'-code');require(not work.exists(),'Frozen code checkout already exists')
    revision=checked(['git','rev-parse','HEAD']);checked(['git','worktree','add','--detach',work,revision]);checked(['git','worktree','lock','--reason','Frozen independent continuous study',work])
    shutil.copytree(P/'lib',work/'lib')
    require(base.files(P/'lib')==base.files(work/'lib'),'Built bytes changed during copy')
    argv=[sys.executable,'-B',work/'scripts/run-swe-continuous.py','freeze','--frozen-here','--output',root,'--spec',a.spec.resolve(),'--dataset',a.dataset.resolve(),'--scorer',a.scorer.absolute(),'--embedding',a.embedding.resolve()]
    subprocess.run([str(x) for x in argv],cwd=work,check=True);return read(root/'protocol.json')

def load_protocol(root):
    require((root/'protocol.sha256').read_text().strip()==sha(root/'protocol.json'),'Frozen protocol hash changed')
    return read(root/'protocol.json')
def checkpoint_check(root,r):
    p=root/(key(r['position'],r['arm'])+'.checkpoint.json');cp=read(p);state=Path(cp['state'])
    require(cp['position']==r['position'] and cp['arm']==r['arm'] and cp['instanceId']==r['instanceId'],'Checkpoint ownership mismatch')
    require(cp['sessions']==files(state/'home/sessions') and (r['arm']!='rsi' or cp['assets']==files(state/'assets')),'Closed checkpoint bytes changed')
    native.verify_seed(state/'assets' if r['arm']=='rsi' else None,state/'home/sessions');return cp

def checkpoint(root,r,s,previous):
    state=Path(r['runDir'])/'state';receipt=read(state/'pilot'/r['instanceId']/'receipt.json');initial=read(state/'pilot'/r['instanceId']/'initial.json')
    require(receipt['runnerStatus']=='COMPLETED' and receipt['formalBenchmark'] is True and receipt['fixture'] is False and receipt['arm']==r['arm'] and receipt['instanceId']==r['instanceId'] and receipt.get('nativeFiberDisposed') is True,'Native state did not close safely')
    own=order(s)[:r['position']-1];expected=['pilot-'+id+'-task' for id in own]
    require([p['sessionId'] for p in initial.get('priorTaskLogs',[])]==expected,'Restored logs are not in frozen task order')
    if previous:
        old=Path(previous['state']);snap=read(Path(r['runDir'])/'source-snapshot.json');wanted={'sessions':previous['sessions']}
        if r['arm']=='rsi':wanted['assets']=previous['assets']
        require(snap['inputSha256']==wanted,'Wrong prior own state delivered')
        require(all(sha(state/'home/sessions'/n)==h for n,h in previous['sessions'].items()),'Old raw history was modified by current task')
        inherited=read(state/'pilot'/r['instanceId']/'history-inheritance.json');parent='pilot-'+own[-1]+'-task'
        require(inherited['parentSessionId']==parent,'Wrong inherited parent session')
        parent_events=[json.loads(line) for line in (old/'home/sessions/--workspace--'/parent/'session.v4.jsonl').read_text().splitlines()][1:]
        child=[json.loads(line) for line in (state/'home/sessions/--workspace--'/('pilot-'+r['instanceId']+'-task')/'session.v4.jsonl').read_text().splitlines()]
        cut=inherited['inheritedEventCount'];require(child[0]['isSeeded'] is True and child[0]['parentSession']==parent and cut==len(parent_events) and child[1:1+cut]==parent_events,'Native inherited prefix differs from exact parent events')
        r['directNativeHistoryInherited']=True;r['inheritedEventCount']=cut
        r['ownPriorRawHistoryExact']=True
    else:
        require(not (Path(r['runDir'])/'source-snapshot.json').exists(),'First task has inherited state')
        require(initial['assets'] is None if r['arm']=='baseline' else not initial['assets']['memory'] and not initial['assets']['skills'],'First task has prior assets')
    if r['arm']=='baseline':require(initial['assets'] is None and receipt['backgroundDispatches']==0 and not any(n.startswith('rsi_') for n in initial['toolSchemas']),'Baseline contains RSI')
    restored=native.verify_seed(state/'assets' if r['arm']=='rsi' else None,state/'home/sessions')
    require({p['sessionId'] for p in restored['priorTaskLogs']}==set(expected+['pilot-'+r['instanceId']+'-task']),'State missing own task or containing other tasks')
    cp={'position':r['position'],'instanceId':r['instanceId'],'arm':r['arm'],'state':str(state),'sessions':files(state/'home/sessions'),'assets':files(state/'assets') if r['arm']=='rsi' else None,'previousPosition':previous['position'] if previous else None,'scorerNeverCarried':True}
    write(root/(key(r['position'],r['arm'])+'.checkpoint.json'),cp);r['checkpointVerified']=True;return cp

def token_groups(ledger):
    metrics={}
    for group in ['foreground','learning']:
        items=[r for r in ledger if (r['phase']=='learning')==(group=='learning')];good=[r for r in items if all(type((r.get('usage') or {}).get(k)) is int and r['usage'][k]>=0 for k in ['inputTokens','outputTokens','totalTokens']) and r['usage']['totalTokens']>0]
        metrics[group]={'calls':len(items),'inputTokens':sum(r['usage']['inputTokens'] for r in good),'outputTokens':sum(r['usage']['outputTokens'] for r in good),'knownTotalTokens':sum(r['usage']['totalTokens'] for r in good),'unknownUsageRequests':len(items)-len(good)}
    return metrics

def usage_and_delivery(out,instance):
    pilot=out/'state/pilot'/instance;ledger=read(pilot/'model-requests.json');metrics=token_groups(ledger)
    front=[r for r in ledger if r['phase']!='learning'];deliveries={};skills={};history=set()
    for ordinal,r in enumerate(front,1):
        for m in r['messages']:
            text='\n'.join(b.get('text','') for b in m.get('content',[]) if b.get('type')=='text')
            source=m.get('source') or {}
            if source.get('kind')=='dsh-rsi' and source.get('form')=='memory':
                delivered=[{'scope':scope['scope'],'id':ref.get('id'),'version':ref.get('version'),'bodySha256':hashlib.sha256(ref.get('content','').encode()).hexdigest(),'completeBodyInRequest':bool(ref.get('content')) and ref['content'] in text} for scope in source.get('refs',[]) for ref in scope.get('memories',[])]
                deliveries.setdefault(m.get('id',str(source)),{'firstRequest':ordinal,'bodyChars':len(text),'source':source,'memories':delivered})
            match=re.search(r'<skill_content name="([^"]+)">',text);body=re.search(r'<skill_instructions>\s*([\s\S]*?)\s*</skill_instructions>',text)
            if match and body:skills.setdefault(m.get('toolCallId',m.get('id',match[1])),{'name':match[1],'firstRequest':ordinal,'bodyChars':len(body[1]),'bodySha256':hashlib.sha256(body[1].encode()).hexdigest()})
            if m.get('toolCallId') and 'session.v4.jsonl' in text:history.add(m['toolCallId'])
    tools=read(pilot/'tool-results.json');phases=read(pilot/'phases.json')
    current_calls={t['callId'] for t in tools}
    for call,skill in skills.items():skill['currentTaskLoad']=call in current_calls
    for delivery in deliveries.values():delivery['messageId']=next((mid for mid,item in deliveries.items() if item is delivery),None)
    metrics.update(compactionCalls=sum(r.get('purpose')=='compaction' for r in front),memoryDeliveries=list(deliveries.values()),skillLoads=list(skills.values()),historyToolResultCandidates=sorted(history),toolErrors=sum(t['isError'] for t in tools),modelErrors=sum(r['status']=='ERROR' for r in ledger),outputTruncations=sum((r.get('finish') or {}).get('kind')=='max-tokens' for r in ledger),agentWallSeconds=sum(p['wallMs']/1000 for p in phases),phaseStops=[p.get('stopReason') for p in phases],timedOut=any('wall time' in json.dumps(p.get('stopReason')) for p in phases),diagnosticSnapshotPaths=str(pilot/'patch-snapshots.json'),diagnosticsLimitation='Body delivery/path candidates do not establish relevance or decision causality; earliest passing edit requires offline snapshot scoring.')
    return metrics,ledger

def run_arm(root,s,c,position,arm,previous):
    out=root/key(position,arm);record=record_file(root,position,arm);require(not out.exists() and not record.exists(),'Attempt may not be replayed')
    r={'position':position,'instanceId':c['instanceId'],'arm':arm,'attempt':0,'status':'RUNNING','resolved':None,'runDir':str(out),'previousOwnState':previous['state'] if previous else None,'startedAt':time.time()};write(record,r)
    fatal=True;b=s['budgets'];cp=None
    try:
        validate(s,c)
        if previous:checkpoint_check(root,{'position':position-1,'arm':arm,'instanceId':s['cases'][position-2]['instanceId']})
        orderfile=root/(key(position,arm)+'.history-order.json');write(orderfile,order(s)[:position-1]);learning=b['learningCallsPerTask'] if arm=='rsi' else 0
        argv=[sys.executable,'-B',P/'scripts/probe-runner.py','--formal','--arm',arm,'--thinking','off','--history-order',orderfile,'--image',c['taskTag'],'--instance',c['instanceId'],'--output',out,'--dispatch-limit',b['foregroundCalls'],'--request-limit',b['foregroundCalls']+learning,'--learning-call-budget',b['learningTotal'] if arm=='rsi' else 0,'--learning-dispatch-limit',learning,'--wall-seconds',b['wallSeconds'],'--settle-seconds',b['settleSeconds'] if arm=='rsi' else 0,'--baseline-date',c['baselineDate'],'--expected-tree',c['expectedTree'],'--expected-version',c['expectedVersion']]
        if arm=='rsi':
            argv+=['--learning-pool',root/'learning-budget.sqlite','--embedding-model',s['embeddingModel']]
            if previous:argv+=['--seed-assets',Path(previous['state'])/'assets','--seed-sessions',Path(previous['state'])/'home/sessions']
        elif previous:argv+=['--baseline-history',Path(previous['state'])/'home/sessions']
        r['runnerReturnCode']=thinking.execute(argv,root/(key(position,arm)+'.runner.log'),timeout=b['wallSeconds']+(b['settleSeconds'] if arm=='rsi' else 0)+300)
        # Commit learner state independently of the score. A scoring error must
        # neither erase natural history nor prevent later tasks from learning.
        require(not (out/'budget-settlement-error.json').exists(),'Durable learning budget settlement failed; further dispatch forbidden')
        cp=checkpoint(root,r,s,previous);fatal=False
        r['assetInventory']=asset_inventory(out/'state')
        before=asset_inventory(Path(previous['state'])) if previous else {'memories':[],'skills':[]}
        r['assetDelta']=asset_delta(before,r['assetInventory']);r['embedding']=embedding_cost(out/'state',Path(previous['state']) if previous else None)
        try:
            m,ledger=usage_and_delivery(out,c['instanceId']);r.update(m)
            require(len(ledger)==m['foreground']['calls']+m['learning']['calls'] and 0<m['foreground']['calls']<=b['foregroundCalls'] and m['learning']['calls']<=learning,'Native dispatch bounds differ')
            wire=native.verify_thinking_wire(out,'off',write_result=True,shutdown_receipt=read(out/'state/pilot'/c['instanceId']/'receipt.json'));r['serviceThinkingEvidence']=wire
            require(wire['requests']==len(ledger),'Native/wire dispatch counts differ')
            sent=[w for w in (json.loads(l) for l in (out/'gateway.log').read_text().splitlines() if l.strip()) if w.get('request') and w.get('model')]
            require(all(w['model']=='qwen3.8-27b' and w['maxOutputTokens']<=8192 for w in sent),'Model/output configuration changed')
            recon=read(out/'state/pilot'/c['instanceId']/'reconstruction.json');require(len(recon)==len(ledger) and all(q.get('matches') is True for q in recon),'Native request reconstruction differs')
            require(r['runnerReturnCode']==0 and not (out/'budget-settlement-error.json').exists(),'Runner or durable budget settlement error')
            require(m['modelErrors']==0,'Model/service errors require separate classification')
        except Exception as error:r['executionError']=str(error)
        pilot=out/'state/pilot'/c['instanceId'];grade=out/'grading.json'
        if (pilot/'prediction.patch').is_file():
            code=thinking.execute([s['scorerPython'],'-B',P/'scripts/score-prediction.py','--dataset',s['dataset'],'--instance',c['instanceId'],'--prediction',pilot/'prediction.patch','--work-dir',out/'grader-only','--output',grade],root/(key(position,arm)+'.scorer.log'),timeout=420);r['scorerReturnCode']=code
            if grade.exists():
                g=read(grade);require(g['instanceId']==c['instanceId'] and g['patchSha256']==sha(pilot/'prediction.patch') and g['verifiedSourceFiles']==50 and g['modelRequests']==0,'Official prediction/score provenance differs')
                r.update(resolved=g['resolved'],grading=str(grade))
        r['status']='CLOSED_GRADED' if not r.get('executionError') and r.get('scorerReturnCode')==0 and type(r['resolved']) is bool else 'CLOSED_INFRA'
        if r['status']=='CLOSED_INFRA':r['error']=r.get('executionError','Official scorer produced no valid report')
    except Exception as error:r.update(status='HALTED_STATE_OR_FREEZE' if fatal else 'CLOSED_INFRA',error=str(error))
    # Preserve measurable cost even when missing/unsafe state halts the chain.
    # A partial ledger is a lower bound, never an invented zero-cost attempt.
    if not r.get('foreground'):
        partial=out/'state/pilot'/c['instanceId']/'model-requests.json'
        if partial.is_file():
            try:r.update(token_groups(read(partial)));r['partialCostEvidence']=True
            except Exception as error:r['costAuditError']=str(error)
    r['finishedAt']=time.time();write(record,r);return r,cp

def summarize(root,s):
    saved=rows(root);by={(r['position'],r['arm']):r for r in saved};require(len(by)==len(saved),'Duplicate records')
    require(all(1<=r['position']<=len(s['cases']) and r['arm'] in ARMS and r['instanceId']==s['cases'][r['position']-1]['instanceId'] and r['attempt']==0 for r in saved),'Unexpected attempts')
    write(root/'runs.json',sorted(saved,key=lambda r:(r['position'],r['arm'])))
    def group(start,end):
        out={'start':start,'end':end,'plannedPairs':end-start+1,'arms':{},'confidenceInterval':None}
        for arm in ARMS:
            allrows=[r for r in saved if start<=r['position']<=end and r['arm']==arm];graded=[r for r in allrows if r['status']=='CLOSED_GRADED'];n=end-start+1;cost={}
            for part in ['foreground','learning']:
                cost[part]={k:sum(r.get(part,{}).get(k,0) for r in allrows) for k in ['calls','inputTokens','outputTokens','knownTotalTokens','unknownUsageRequests']}
            out['arms'][arm]={'closed':sum(r['status'] in TERMINAL for r in allrows),'graded':len(graded),'infrastructureCases':sum(r['status']=='CLOSED_INFRA' for r in allrows),'solved':sum(r['resolved'] for r in graded),'officialPassRate':sum(r['resolved'] for r in graded)/n if len(graded)==n else None,'observedGradedPassRate':sum(r['resolved'] for r in graded)/len(graded) if graded else None,'usage':cost,'partialLedgerAttempts':sum(r.get('partialCostEvidence',False) for r in allrows),'unmeteredAttempts':sum(not r.get('foreground') for r in allrows),'agentWallSeconds':sum(r.get('agentWallSeconds',0) for r in allrows),'endToEndSeconds':sum(r.get('finishedAt',r.get('startedAt',0))-r.get('startedAt',0) for r in allrows),'memoryDeliveries':sum(len(r.get('memoryDeliveries',[])) for r in allrows),'skillLoads':sum(len(r.get('skillLoads',[])) for r in allrows),'timeouts':sum(r.get('timedOut',False) for r in allrows),'outputTruncations':sum(r.get('outputTruncations',0) for r in allrows),'modelErrors':sum(r.get('modelErrors',0) for r in allrows),'toolErrors':sum(r.get('toolErrors',0) for r in allrows),'compactionCalls':sum(r.get('compactionCalls',0) for r in allrows),'assetChanges':{kind:{metric:sum(r.get('assetDelta',{}).get(kind,{}).get(metric,0) for r in allrows) for metric in ['created','updated','removed']} for kind in ['memories','skills']},'localEmbedding':{metric:sum(r.get('embedding',{}).get(metric,0) for r in allrows) for metric in ['calls','inputChars','wallMs','errors','unknownTokenUsageCalls']}}
        good=[(by.get((i,'baseline')),by.get((i,'rsi'))) for i in range(start,end+1)];valid=[(a,b) for a,b in good if a and b and a['status']==b['status']=='CLOSED_GRADED']
        out.update(validPairs=len(valid),rsiOnly=sum(b['resolved'] and not a['resolved'] for a,b in valid),baselineOnly=sum(a['resolved'] and not b['resolved'] for a,b in valid),pairedNet=sum(int(b['resolved'])-int(a['resolved']) for a,b in valid) if len(valid)==end-start+1 else None);return out
    n=len(s['cases']);complete=len(saved)==2*n and all(r['status'] in TERMINAL for r in saved)
    stages=[{'stage':group(i,min(i+19,n)),'cumulative':group(1,min(i+19,n))} for i in range(1,n+1,20)]
    result={'status':'COMPLETE' if complete else 'PARTIAL','purpose':s['purpose'],'completedRuns':sum(r['status'] in TERMINAL for r in saved),'plannedRuns':2*n,'overall':group(1,n),'stages':stages,'formal100Started':s['purpose']=='formal' and bool(saved),'scoresReturnedToLearning':False,'confidenceInterval':None,'limitations':['One dependent sequence; stages are descriptive, not iid samples.','Body delivery alone does not prove asset relevance or decision causality.','Unmetered attempts and unknown usage prevent an exact full-chain token total.']}
    write(root/'summary.json',result)
    md=['# SWE 连续学习批次','',f"状态：{result['status']}；{result['completedRuns']}/{2*n}次关闭。Thinking Off；预算与题序见冻结protocol.json。",'','|位置|任务|Baseline|RSI|','|---:|---|---|---|']
    for i,c in enumerate(s['cases'],1):
        def val(arm):
            r=by.get((i,arm));return '未执行' if not r else ('通过' if r['resolved'] else '失败') if r['status']=='CLOSED_GRADED' else r['status']
        md.append(f"|{i}|{c['instanceId']}|{val('baseline')}|{val('rsi')}|")
    md+=['','逐题Token、阶段/累计统计及无效结果见summary.json和各record.json。单题异常不自动计为失败或重跑；安全关闭的自然状态照常交接。两组用原生fork直接继承自己的原始会话，源码逐题重置；日志也通过相同工具协议可读，RSI另有原生资产消费。隐藏测试、官方答案与评分不回流。','', '单条依赖序列不计算iid置信区间；基础设施缺口存在时完整通过率及净差为空，已判分观察值单列。']
    (root/'report.md').write_text('\n'.join(md)+'\n');return result

def run(root,s,resume=False):
    with (root/'worker.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        saved=rows(root);require(resume or not saved,'Explicit resume required');require(all(r['status'] in TERMINAL for r in saved),'Interrupted/unsafe attempts need audit; never replay')
        summarize(root,s);pool=budget.LearningBudget(root/'learning-budget.sqlite',s['budgets']['learningTotal']);pool.close();seeds={a:None for a in ARMS}
        try:
            validate(s);require(thinking.model_identity()==s['modelIdentity'],'Reported deployment changed')
            for position,c in enumerate(s['cases'],1):
                for arm in (ARMS if position%2 else list(reversed(ARMS))):
                    prior=next((r for r in saved if r['position']==position and r['arm']==arm),None)
                    if prior:seeds[arm]=checkpoint_check(root,prior);continue
                    if (root/'STOP').exists():write(root/'state.json',{'status':'STOPPED','completedRuns':len(saved),'plannedRuns':2*len(s['cases'])});summarize(root,s);return
                    write(root/'state.json',{'status':'RUNNING','position':position,'arm':arm,'completedRuns':len(saved),'plannedRuns':2*len(s['cases']),'pid':os.getpid()})
                    r,cp=run_arm(root,s,c,position,arm,seeds[arm]);saved.append(r);summarize(root,s)
                    if r['status'] not in TERMINAL or cp is None:raise ValueError('Unsafe closed-state/frozen input chain; further dispatch forbidden: '+r.get('error',''))
                    seeds[arm]=cp
            result=summarize(root,s);require(result['status']=='COMPLETE','Missing planned run');write(root/'state.json',{'status':'COMPLETE','completedRuns':len(saved),'plannedRuns':2*len(s['cases']),'summary':str(root/'summary.json')})
        except Exception as error:
            write(root/'state.json',{'status':'HALTED','error':str(error),'completedRuns':sum(r['status'] in TERMINAL for r in rows(root)),'plannedRuns':2*len(s['cases'])});summarize(root,s)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['freeze','start','run','status','stop','report','validate']);p.add_argument('--output',type=Path,required=True);p.add_argument('--spec',type=Path);p.add_argument('--dataset',type=Path);p.add_argument('--scorer',type=Path);p.add_argument('--embedding',type=Path);p.add_argument('--resume',action='store_true');p.add_argument('--frozen-here',action='store_true',help=argparse.SUPPRESS);a=p.parse_args();root=a.output.resolve();os.environ.setdefault('RSI_MODEL_UPSTREAM','http://10.195.214.152:8100/v1')
    if a.mode=='freeze':require(all([a.spec,a.dataset,a.scorer,a.embedding]),'Freeze requires all explicit inputs');print(json.dumps({'status':'FROZEN','revision':freeze(a)['revision'],'modelRequests':0}));return
    s=load_protocol(root)
    if a.mode=='status':print(json.dumps(read(root/'state.json'),ensure_ascii=False,indent=2));return
    if a.mode=='stop':(root/'STOP').touch();print('STOP requested: close the current task and retain state');return
    if a.mode=='report':print(json.dumps(summarize(root,s),ensure_ascii=False));return
    # The public entry always dispatches the frozen checkout, not this mutable one.
    work=Path(s['frozenWorktree']);require(work.is_dir(),'Frozen checkout missing')
    if a.mode=='validate':
        if P!=work:
            subprocess.run([sys.executable,'-B',work/'scripts/run-swe-continuous.py','validate','--output',root],cwd=work,check=True)
        else:validate(s);print('PASS_FROZEN_CONTINUOUS_INPUTS')
        return
    if a.mode=='start':
        # Validate using the frozen implementation even when the user's main
        # checkout has moved on. The worker also validates before every task.
        subprocess.run([sys.executable,'-B',work/'scripts/run-swe-continuous.py','validate','--output',root],cwd=work,check=True)
        if (root/'STOP').exists():
            require(a.resume,'Use explicit --resume to clear a requested STOP')
            require(all(r['status'] in TERMINAL for r in rows(root)),'Unsafe interrupted attempt cannot resume')
            (root/'STOP').unlink()
        with (root/'launch.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            old=read(root/'background.json') if (root/'background.json').exists() else {}
            if old.get('pid'):
                try:os.kill(old['pid'],0)
                except ProcessLookupError:pass
                else:raise ValueError('Background worker is still alive')
            require(not (root/'state.json').exists() or read(root/'state.json')['status'] not in ['HALTED','COMPLETE'],'Closed or HALTED study cannot be restarted')
            with (root/'background.log').open('ab') as log:child=subprocess.Popen([sys.executable,'-B',work/'scripts/run-swe-continuous.py','run','--output',root]+(['--resume'] if a.resume else []),cwd=work,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            write(root/'background.json',{'pid':child.pid,'frozenWorktree':str(work)});print(json.dumps({'pid':child.pid,'output':str(root),'CodexRequiredWhileRunning':False}));return
    require(P==work,'Run through the frozen checkout');run(root,s,a.resume)
    if s['purpose']=='development' and read(root/'state.json')['status']=='COMPLETE':
        # Pure post-run diagnostics; never feed scores back to the learner.
        try:load('audit-swe-continuous-state').audit(root)
        except Exception as error:write(root/'inheritance-audit.json',{'status':'REAL_STATE_AUDIT_FAILED','error':str(error),'formal100Allowed':False})
if __name__=='__main__':main()
