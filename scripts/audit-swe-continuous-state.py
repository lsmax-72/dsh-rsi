#!/usr/bin/env python3
"""Offline acceptance of real own-history and native asset delivery; dispatches nothing."""
import argparse, hashlib, importlib.util, json
from pathlib import Path
P=Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location('continuous',P/'scripts/run-swe-continuous.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
def audit(root):
    s=m.load_protocol(root);m.require(s['purpose']=='development','This acceptance is scoped to exposed development tasks');records=m.rows(root);checks=[];memory=[];skills=[];errors=[]
    for arm in m.ARMS:
        own=sorted((r for r in records if r['arm']==arm),key=lambda r:r['position'])
        try:
            m.require(len(own)==2 and all(r['status'] in m.TERMINAL for r in own),'Development sequence not safely closed')
            for r in own:
                cp=m.checkpoint_check(root,r);pilot=Path(r['runDir'])/'state/pilot'/r['instanceId'];receipt=m.read(pilot/'receipt.json');ledger=m.read(pilot/'model-requests.json');recon=m.read(pilot/'reconstruction.json')
                m.require(receipt['fixture'] is False and receipt['nativeFiberDisposed'] is True,'Not real native state')
                m.require(ledger and all(q['matches'] for q in recon) and len(recon)==len(ledger),'Actual request not reconstructable')
                m.require(r.get('serviceThinkingEvidence',{}).get('requests')==len(ledger) and not r.get('executionError'),'Actual model/configuration audit failed')
                if r['position']==2:
                    inherited=m.read(pilot/'history-inheritance.json');first=next(q for q in ledger if q['sessionId']=='pilot-'+r['instanceId']+'-task');actual={msg['id']:msg for msg in first['messages']};intact=[]
                    # Native pruning may replace old tool results. Native
                    # compaction may summarize them, without deleting raw logs.
                    for prior in inherited['parentMessages']:
                        if prior['role'] in ['user','assistant'] and prior['id'] in actual:
                            digest=hashlib.sha256(json.dumps(actual[prior['id']]['content'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
                            if digest==prior['contentSha256']:intact.append(prior['id'])
                    m.require(r['directNativeHistoryInherited'] and r['ownPriorRawHistoryExact'] and intact,'No prior conversational content in actual next-task request')
                    checks.append({'arm':arm,'position':2,'parentSession':inherited['parentSessionId'],'inheritedEventCount':inherited['inheritedEventCount'],'exactPriorConversationIdsInFirstRequest':intact,'modelInputReconstructed':True})
                    previous=own[0]['assetInventory'];before_ids={q['id'] for q in inherited['parentMessages']}
                    for delivery in r.get('memoryDeliveries',[]):
                        if delivery['messageId'] in before_ids:continue
                        for ref in delivery['memories']:
                            if ref['completeBodyInRequest'] and any(ref['id']==a['id'] and ref['scope']==a['scope'] and ref['bodySha256']==a['bodySha256'] for a in previous['memories']):memory.append({'position':2,'messageId':delivery['messageId'],**ref})
                    for skill in r.get('skillLoads',[]):
                        if skill['currentTaskLoad'] and any(skill['bodySha256']==a['bodySha256'] for a in previous['skills']):skills.append({'position':2,**skill})
        except Exception as error:errors.append({'arm':arm,'error':str(error)})
    real=sum((r.get('foreground',{}).get('calls',0)+r.get('learning',{}).get('calls',0)) for r in records)
    passed=not errors and len(checks)==2 and bool(memory) and bool(skills)
    result={'status':'PASS_REAL_CONTINUOUS_STATE' if passed else 'REAL_STATE_INHERITANCE_VERIFIED_CONSUMPTION_GAP' if not errors else 'REAL_STATE_AUDIT_FAILED','arms':m.ARMS,'realModelRequests':real,'fixtureModel':False,'memoryBodyConsumed':bool(memory),'skillBodyConsumed':bool(skills),'nativeHistoryChecks':checks,'priorCheckpointMemoryDeliveries':memory,'priorCheckpointSkillLoads':skills,'errors':errors,'mechanismSha256':m.mechanism_hashes(s['codeHashes']),'officialScoresUsedInLearning':False,'formal100Allowed':False,'limitation':'Only the two exposed-task sequence is validated; no effect-size or general asset-relevance conclusion. No synthetic assets or forced named Skill loading.'}
    m.write(root/'inheritance-audit.json',result);print(json.dumps(result,ensure_ascii=False));return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args();audit(a.output.resolve())
