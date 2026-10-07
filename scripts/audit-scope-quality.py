#!/usr/bin/env python3
"""Audit delivery and cost only; semantic judgments stay in a separate reviewer report."""
import argparse,base64,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path,required=True);p.add_argument('--case',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
root=a.run/'state/pilot'/a.case
read=lambda n:json.loads((root/n).read_text())
receipt=read('receipt.json');requests=read('model-requests.json');stages=read('stages.json');sources=read('sources.json')
source_ids={id for s in sources for id in s['messageIds']};cost={}
for r in requests:
    key=('background/' if r['background'] else 'consumer/')+r['taskId'];x=cost.setdefault(key,{'requests':0,'knownTokens':0,'inputTokens':0,'outputTokens':0,'unknownUsage':0})
    x['requests']+=1;u=r.get('usage') or {};known=isinstance(u.get('totalTokens'),(int,float)) and u['totalTokens']>0
    if known:
        for key2,key3 in [('knownTokens','totalTokens'),('inputTokens','inputTokens'),('outputTokens','outputTokens')]: x[key2]+=u.get(key3,0)
    else:x['unknownUsage']+=1
assets=read('final-assets.json');memories=[{'scope':v['scope'],**m} for v in assets.values() for m in v['memory']]
consumer=[r for r in requests if not r['background']]
deliveries=[]
for m in memories:
    rows=[]
    for i,r in enumerate(consumer,1):
        for msg in r['messages']:
            s=msg.get('source',{})
            if s.get('kind')=='dsh-rsi' and s.get('form')=='memory' and any(ref.get('scope')==m['scope'] and any(saved.get('id')==m['id'] and saved.get('version')==m['version'] and saved.get('content')==m['content'] for saved in ref.get('memories',[])) for ref in s.get('refs',[])) and any(m['content'] in b.get('text','') for b in msg['content']):rows.append(i)
    deliveries.append({'id':m['id'],'scope':m['scope'],'version':m['version'],'content':m['content'],'sourceIds':m.get('source_message_ids',[]),'sourceIdsKnown':bool(m.get('source_message_ids')) and set(m['source_message_ids'])<=source_ids,'consumerRequests':sorted(set(rows))})
old_ids=[m['id'] for m in stages[0]['globalMemory']] if stages else []
conflicts=[{'request':i+1,'visibleOldIds':[id for id in old_ids if id in json.dumps(r['messages'],ensure_ascii=False)],'scope':r.get('scope')} for i,r in enumerate(requests) if r['taskId']=='l1-conflict-detection' and r['phase']=='after' and r.get('scope')=='global']
profiles={key:[{'path':f['path'],'text':base64.b64decode(f['content']).decode() if f.get('encoding')=='base64' else f['content']} for f in v['profileFiles'] if f['path'].endswith('.md')] for key,v in assets.items()}
checks={'completed':receipt['status']=='COMPLETED_REQUIRES_CONTENT_REVIEW','oldSharedPersonaPresent':bool(old_ids),'oldSharedIdInAfterConflict':any(c['visibleOldIds'] for c in conflicts),'memoryDeliveredWithContentIdentity':any(d['consumerRequests'] for d in deliveries),'allMemorySourceIdsKnown':bool(deliveries) and all(d['sourceIdsKnown'] for d in deliveries),'durablePrefixReconstruction':bool(requests) and all(r['inputReconstructed'] for r in requests),'fullHistoryRetained':receipt.get('fullHistoryRetained',False),'consumerNotLearned':receipt.get('questionLearned') is False}
wire=[]
if (a.run/'gateway.log').exists():wire=[json.loads(x) for x in (a.run/'gateway.log').read_text().splitlines() if x.strip()]
sent=[r for r in wire if r.get('request')]
checks['gatewayMatchesDispatches']=bool(receipt.get('fixture')) or len(sent)==len(requests)
embedding=[]
for f in (a.run/'state/assets/scopes').glob('*/diagnostics/embedding.log'):
    for line in f.read_text().splitlines():
        if ' {' in line:
            try:embedding.append(json.loads(line[line.index(' {')+1:]))
            except ValueError:pass
result={'status':'MECHANISM_PASS_CONTENT_REVIEW_PENDING' if all(checks.values()) else 'MECHANISM_OR_RUN_NOT_PASSED','fixture':receipt.get('fixture'), 'caseId':a.case,'checks':checks,'receipt':receipt,'phaseCost':cost,'deliveries':deliveries,'sharedConflictVisibility':conflicts,'profiles':profiles,'answer':read('answer.json') if (root/'answer.json').exists() else None,'embedding':{'calls':len(embedding),'failedCalls':sum(x.get('status')=='failed' for x in embedding),'tokenUsage':None,'inputCharacters':sum(x.get('input_chars',0) for x in embedding)},'semanticQuality':None,'independentEffectClaim':False,'artifactSha256':{f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in root.glob('*.json')}}
a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
print(json.dumps({'status':result['status'],'caseId':a.case,'checks':checks,'requests':len(requests),'knownTokens':receipt['knownTokens']}))
