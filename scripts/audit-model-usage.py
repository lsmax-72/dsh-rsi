#!/usr/bin/env python3
"""Audit saved real chat usage; adapter zero defaults are not measured zero cost."""
import argparse,json
from collections import Counter
from pathlib import Path


def measured(usage):
    # Every dispatched real chat has input tokens. Cancellation can synthesize zeros.
    return isinstance(usage,dict) and isinstance(usage.get('totalTokens'),int) and usage['totalTokens']>0


def audit(run):
    pilot=run/'state/pilot';folders=[p for p in pilot.iterdir() if p.is_dir()]
    assert len(folders)==1,'One closed task per audit'
    rows=json.loads((folders[0]/'model-requests.json').read_text())
    corrections=[];seen=Counter();known=0
    for ordinal,row in enumerate(rows,1):
        index=seen[row['sessionId']];seen[row['sessionId']]+=1
        if measured(row.get('usage')):known+=row['usage']['totalTokens'];continue
        reason='MISSING_USAGE' if not row.get('usage') else 'ZERO_USAGE_UNMEASURED'
        item={'requestOrdinal':ordinal,'sessionId':row['sessionId'],'phase':row['phase'],'storedStatus':row['status'],'storedUsage':row.get('usage'),'classification':reason}
        if row.get('usage'):
            session_files=list((run/'state/home/sessions').glob('*/'+row['sessionId']+'/session.v4.jsonl'))
            assert len(session_files)==1,'Cannot locate zero-usage request trace'
            events=[json.loads(line) for line in session_files[0].read_text().splitlines() if line.strip()]
            traces=[e for e in events if e.get('type') in ['assistant/message','assistant/attempt']]
            assert index<len(traces),'Missing assistant trace; do not assign a guessed finish'
            chunks=[x['chunk'] for x in traces[index]['data'].get('stream',[]) if x.get('type')=='chunk']
            item['observedFinishes']=[c.get('reason') for c in chunks if c.get('type')=='finish']
            item['observedTextDeltaChars']=sum(len(c.get('text','')) for c in chunks if c.get('type')=='text-delta')
        corrections.append(item)
    return {'status':'SAVED_REAL_MODEL_USAGE_AUDITED','runDir':str(run),'requests':len(rows),'knownTokens':known,'storedUnknownUsage':sum(not row.get('usage') for row in rows),'unknownActualUsage':len(corrections),'unmeasuredRequests':corrections,'realModelRequestsByReader':0,'originalLedgersChanged':False,'limitation':'Positive supplied usage is counted; missing/all-zero usage remains unknown. This reader cannot recover provider usage for cancelled calls.'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=Path);p.add_argument('--output',type=Path);p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:
        assert measured({'inputTokens':10,'outputTokens':2,'totalTokens':12})
        assert not measured(None) and not measured({'inputTokens':0,'outputTokens':0,'totalTokens':0})
        assert not measured({})
        print(json.dumps({'status':'PASS_USAGE_CLASSIFICATION_CONTROLS','synthetic':True,'realModelRequests':0}));return
    assert a.run and a.output
    result=audit(a.run.resolve())
    with a.output.open('x') as f:f.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='unmeasuredRequests'}))
if __name__=='__main__':main()
