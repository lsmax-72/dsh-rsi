#!/usr/bin/env python3
"""Replay exposed public tasks using unchanged natural assets; never grade or learn."""
import argparse, hashlib, html, importlib.util, json, os, re, subprocess, sys, time
from pathlib import Path
P=Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location('continuous',P/'scripts/run-swe-continuous.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)

def audit(out,c,seed,arm):
    pilot=out/'state/pilot'/c['instanceId'];receipt=m.read(pilot/'receipt.json');ledger=m.read(pilot/'model-requests.json');initial=m.read(pilot/'initial.json');recon=m.read(pilot/'reconstruction.json');policy=m.read(out/'policy.json')
    m.require(receipt['runnerStatus']=='COMPLETED' and not receipt['fixture'] and receipt['nativeFiberDisposed'] and receipt['backgroundDispatches']==0,'Real run not safely closed or learning dispatched')
    m.require(ledger and len(recon)==len(ledger) and all(r['matches'] for r in recon),'Actual native input not reconstructed')
    m.require(initial['baselineTree']==c['expectedTree'] and initial['djangoVersion']==c['expectedVersion'],'Source reset failed')
    m.require(policy['hostBinds']==[] and policy['networkInternal'] and policy['rootfsReadOnly'],'Isolation failed')
    snap=m.read(out/'source-snapshot.json');m.require(snap['inputSha256']['sessions']==m.files(seed/'home/sessions'),'Wrong source history')
    m.require(all(m.sha(out/'state/home/sessions'/f)==h for f,h in m.files(seed/'home/sessions').items()),'Prior raw logs changed')
    inherited=m.read(pilot/'history-inheritance.json');parent=seed/'home/sessions/--workspace--'/inherited['parentSessionId']/'session.v4.jsonl'
    parent_events=[json.loads(line) for line in parent.read_text().splitlines()][1:]
    child_id=receipt['phases'][0]['sessionId'];child=[json.loads(line) for line in (out/'state/home/sessions/--workspace--'/child_id/'session.v4.jsonl').read_text().splitlines()]
    m.require(child[0].get('isSeeded') is True and child[0].get('parentSession')==inherited['parentSessionId'] and inherited['inheritedEventCount']==len(parent_events) and child[1:1+len(parent_events)]==parent_events,'Native child prefix differs from parent events')
    if arm=='rsi':
        m.require(snap['inputSha256']['assets']==m.files(seed/'assets'),'Natural source asset snapshot not byte-identical')
        previous=m.read(seed/'pilot/django__django-11551/receipt.json')['after']['settings']
        m.require(initial['settings']==previous|{'learningEnabled':False,'dailyCallBudget':0},'Consumption changed relevance or extraction settings')
    first={msg['id']:msg for msg in ledger[0]['messages']}
    intact=[p['id'] for p in inherited['parentMessages'] if p['role'] in ['user','assistant'] and p['id'] in first and hashlib.sha256(json.dumps(first[p['id']]['content'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()==p['contentSha256']]
    m.require(intact,'Own prior conversation absent from first request')
    wire=m.native.verify_thinking_wire(out,'off',shutdown_receipt=receipt,write_result=False)
    raw=[m.read(f) for f in sorted((out/'gateway-evidence').glob('*.request.json'))]
    m.require(len(raw)==len(ledger),'Native/wire request count differs')
    # Check the exact content in the actual outbound request, not only the
    # diagnostic initial catalog or a successful tool-call return.
    wire_text=['\n'.join(str(msg.get('content','')) for msg in req['messages']) for req in raw]
    tools=m.read(pilot/'tool-results.json');current={t['callId'] for t in tools if t['name']=='skill' and not t['isError']};parents={p['id'] for p in inherited['parentMessages']}
    frozen=m.asset_inventory(seed) if arm=='rsi' else {'memories':[],'skills':[]};memories={};skills={};catalogs={}
    for n,r in enumerate(ledger):
        for msg in r['messages']:
            text='\n'.join(b.get('text','') for b in msg.get('content',[]) if b.get('type')=='text');source=msg.get('source') or {}
            if source.get('kind')=='skill-catalog':
                for entry in source.get('entries',[]):
                    if entry['name'] in wire_text[n]:catalogs[entry['name']]=n+1
            if msg.get('id') not in parents and source.get('kind')=='dsh-rsi' and source.get('form')=='memory':
                for scope in source.get('refs',[]):
                    for ref in scope.get('memories',[]):
                        digest=hashlib.sha256(ref.get('content','').encode()).hexdigest()
                        if ref.get('content') and ref['content'] in text and any(w.get('role')=='user' and text in str(w.get('content','')) for w in raw[n]['messages']) and any(a['id']==ref['id'] and a['scope']==scope['scope'] and a['bodySha256']==digest for a in frozen['memories']):
                            memories.setdefault(ref['id'],{'id':ref['id'],'scope':scope['scope'],'bodySha256':digest,'messageId':msg['id'],'requestOrdinal':n+1})
            name=re.search(r'<skill_content name="([^"]+)">',text);body=re.search(r'<skill_instructions>\s*([\s\S]*?)\s*</skill_instructions>',text)
            if name and body and msg.get('toolCallId') in current:
                digest=hashlib.sha256(html.unescape(body[1]).encode()).hexdigest()
                if any(w.get('role')=='tool' and w.get('tool_call_id')==msg.get('toolCallId') and body[1] in str(w.get('content','')) for w in raw[n]['messages']) and any(a['bodySha256']==digest for a in frozen['skills']):skills.setdefault(name[1],{'name':name[1],'bodySha256':digest,'toolCallId':msg['toolCallId'],'requestOrdinal':n+1})
    after=m.asset_inventory(out/'state');m.require(after==frozen,'Frozen assets were changed or baseline contains assets')
    return {'arm':arm,'instanceId':c['instanceId'],'realModelRequests':len(ledger),'nativeHistory':{'parentSessionId':inherited['parentSessionId'],'inheritedEventCount':inherited['inheritedEventCount'],'exactPriorConversationIdsInFirstRequest':intact},'memory':list(memories.values()),'skills':list(skills.values()),'catalogNames':sorted(catalogs),'assetInventoryUnchanged':True,'actualWireVerified':True,'nativeRequestsReconstructed':True,'learningCalls':0,'thinkingEvidence':wire,'metrics':m.token_groups(ledger),'trace':str(pilot/'model-requests.json'),'wire':str(out/'gateway-evidence'),'toolErrors':sum(t['isError'] for t in tools)}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--run',action='store_true');p.add_argument('--audit-only',action='store_true',help='Recheck saved real bytes; no dispatch or overwrite');a=p.parse_args();root=a.output.resolve()
    if a.audit_only:
        plan=m.read(root/'plan.json');m.require(plan['mechanismSha256']==m.mechanism_hashes(),'Acceptance implementation changed')
        env=m.read(P/'docs/evidence/thinking-environments-20261008.json')['environments'][:2];source=P/'.artifacts/swe-continuous-development-20261009'
        runs=[('rsi',c,source/'002-rsi/state') for c in env]+[('baseline',env[1],source/'001-baseline/state')]
        results=[audit(root/(f'{i:03d}-'+arm),c,seed,arm) for i,(arm,c,seed) in enumerate(runs,1)]
        original=m.read(root/'acceptance.json');reviewed=dict(original,results=results,auditOnly=True,reviewedAt=time.time())
        reviewed['memoryBodyConsumed']=any(r['memory'] for r in results if r['instanceId']=='django__django-11551' and r['arm']=='rsi')
        reviewed['bothFrozenSkillsConsumed']=len({q['bodySha256'] for r in results for q in r['skills']})==2
        reviewed['status']='PASS_REAL_CONTINUOUS_STATE' if reviewed['memoryBodyConsumed'] and reviewed['bothFrozenSkillsConsumed'] and not original['errors'] else 'ASSET_ACCEPTANCE_NOT_COMPLETE'
        target=root/'acceptance-reviewed.json';m.require(not target.exists(),'Preserve previous reviewed proof');m.write(target,reviewed);print(json.dumps({'status':reviewed['status'],'file':str(target),'newModelRequests':0}));return
    m.require(os.environ.get('RSI_MODEL_UPSTREAM'),'Set the authorized Qwen endpoint before starting a batch')
    if not a.run:
        m.require(not root.exists(),'Preserve previous acceptance');root.mkdir(parents=True)
        with (root/'batch.log').open('w') as log:child=subprocess.Popen([sys.executable,'-B',__file__,'--run','--output',root],cwd=P,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,env=os.environ.copy())
        m.write(root/'process.json',{'pid':child.pid,'status':'STARTED_EXPOSED_ONLY','formal100Started':False});print(json.dumps({'pid':child.pid,'output':str(root),'log':str(root/'batch.log')}));return
    env=m.read(P/'docs/evidence/thinking-environments-20261008.json')['environments'][:2];source=P/'.artifacts/swe-continuous-development-20261009';
    prior=m.read(source/'002-rsi/state/pilot/django__django-11551/receipt.json');m.require(all(j['status']=='completed' for j in prior['after']['jobs']),'Consumption seed must have no unfinished learning jobs')
    frozen=m.asset_inventory(source/'002-rsi/state');m.require(len(frozen['memories'])==1 and len(frozen['skills'])==2,'Expected previous natural 1 Memory and 2 Skills')
    results=[];errors=[];m.write(root/'plan.json',{'formal100Started':False,'tasks':[c['instanceId'] for c in env],'assetInventory':frozen,'learning':False,'noScorer':True,'limitation':'Same public tasks as asset sources; mechanism acceptance only, not transfer effectiveness','mechanismSha256':m.mechanism_hashes()})
    runs=[('rsi',c,source/'002-rsi/state',[x['instanceId'] for x in env]) for c in env]+[('baseline',env[1],source/'001-baseline/state',[env[0]['instanceId']])]
    for i,(arm,c,seed,history) in enumerate(runs,1):
        out=root/(f'{i:03d}-'+arm);orderfile=root/f'{i:03d}.order.json';m.write(orderfile,history)
        argv=[sys.executable,'-B',P/'scripts/probe-runner.py','--arm',arm,'--thinking','off','--instance',c['instanceId'],'--image',c['taskTag'],'--output',out,'--history-order',orderfile,'--dispatch-limit','16' if arm=='rsi' else '1','--request-limit','16' if arm=='rsi' else '1','--learning-call-budget','0','--learning-dispatch-limit','0','--wall-seconds','300','--settle-seconds','0','--baseline-date',c['baselineDate'],'--expected-tree',c['expectedTree'],'--expected-version',c['expectedVersion']]
        if arm=='rsi':argv+=['--asset-consumption-only','--seed-assets',seed/'assets','--seed-sessions',seed/'home/sessions']
        else:argv+=['--formal','--baseline-history',seed/'home/sessions']
        try:
            rc=m.thinking.execute(argv,root/(f'{i:03d}.runner.log'),timeout=600);m.require(rc==0,'Runner failed, see preserved log')
            results.append(audit(out,c,seed,arm))
        except Exception as e:errors.append({'arm':arm,'instanceId':c['instanceId'],'error':str(e)})
        m.write(root/'progress.json',{'completed':i,'planned':len(runs),'results':results,'errors':errors,'formal100Started':False})
    memory=[q for r in results if r['instanceId']=='django__django-11551' for q in r['memory']];skills=[q for r in results for q in r['skills']];arms=sorted({r['arm'] for r in results});passed=not errors and bool(memory) and len({q['bodySha256'] for q in skills})==2 and arms==m.ARMS
    report={'status':'PASS_REAL_CONTINUOUS_STATE' if passed else 'ASSET_ACCEPTANCE_NOT_COMPLETE','arms':arms,'realModelRequests':sum(r['realModelRequests'] for r in results),'memoryBodyConsumed':bool(memory),'skillBodyConsumed':bool(skills),'bothFrozenSkillsConsumed':len({q['bodySha256'] for q in skills})==2,'nativeHistoryChecks':[{'arm':r['arm'],**r['nativeHistory']} for r in results],'results':results,'errors':errors,'mechanismSha256':m.mechanism_hashes(),'fixtureModel':False,'officialScoresUsedInLearning':False,'formal100Allowed':False,'formal100Started':False,'limitation':'Natural assets reused byte-identically on their already exposed source tasks. Proves delivery and current native history, not cross-task transfer or quality improvement.'}
    m.write(root/'acceptance.json',report);print(json.dumps({'status':report['status'],'completed':len(runs),'errors':errors,'formal100Started':False}))
if __name__=='__main__':main()
