#!/usr/bin/env python3
"""Audit the one completed preexperiment case without replaying model or scoring calls."""
import argparse, hashlib, json
from pathlib import Path
P=Path(__file__).resolve().parent.parent
SOURCE=P/'.artifacts/thinking-preexperiment-v2-20261008'
ID='django__django-11848'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify():
 out=SOURCE/(ID+'-on-0');pilot=out/'state/pilot'/ID
 original=SOURCE/(ID+'-on-0.record.json');rec=read(original)
 assert rec['status']=='HALTED' and rec['runnerReturnCode']==1 and rec['modelErrors']==0 and rec['unknownUsageRequests']==0
 assert not (out/'gateway-evidence').exists(), 'This exception is only for the original lost tmpfs archive'
 logs=[json.loads(l) for l in (out/'gateway.log').read_text().splitlines() if l.strip()]
 sent=[r for r in logs if r.get('request') and r.get('model')];responses=[r for r in logs if 'responseRequest' in r]
 native=read(pilot/'model-requests.json');receipt=read(pilot/'receipt.json');policy=read(out/'policy.json');initial=read(pilot/'initial.json');reconstruction=read(pilot/'reconstruction.json');grade=read(out/'grading.json')
 assert len(sent)==len(responses)==len(native)==rec['calls']==17
 assert [r['request'] for r in sent]==[r['responseRequest'] for r in responses]==list(range(1,18))
 assert all(r['model']=='qwen3.8-27b' and r['enableThinking'] is True and r['maxOutputTokens']==8192 for r in sent)
 assert all(r['responseComplete'] is True and r['sseDone'] is True and r['parseErrors']==0 and r['error'] is None and r['responseModels']==['qwen3.8-27b'] for r in responses)
 for a,b in zip(native,responses):
  assert a['status']=='RETURNED' and a['phase']=='task' and a['reasoningChars']==b['reasoningChars']
  u=b['usage'][-1];n=a['usage'];assert (u['prompt_tokens'],u['completion_tokens'],u['total_tokens'])==(n['inputTokens'],n['outputTokens'],n['totalTokens'])
 assert sum(r['reasoningChars'] for r in responses)>0
 assert receipt['runnerStatus']=='COMPLETED' and receipt['formalBenchmark'] is True and receipt['fixture'] is False and receipt['arm']=='baseline' and receipt['instanceId']==ID and receipt['backgroundDispatches']==0
 assert receipt['logReconstructionMatches'] is True and len(reconstruction)==17 and all(r['matches'] is True and r['responseFramePresent'] is True for r in reconstruction)
 assert initial['assets'] is None and not any(n.startswith('rsi_') for n in initial['toolSchemas'])
 assert policy['sourceSessionsRestored'] is False and policy['baselineRawHistoryRestored'] is False and policy['learningCallBudget']==policy['learningDispatchLimit']==0
 assert policy['dispatchLimit']==policy['requestLimit']==40 and policy['wallSecondsPerPhase']==1200 and policy['settleSecondsPerPhase']==0
 assert not (out/'source-snapshot.json').exists() and read(out/'state.json')['container']['ExitCode']==0
 assert rec['phaseStops']==[{'kind':'completed'}] and not rec['timedOut']
 assert grade['status']=='GRADED' and type(grade['resolved']) is bool and rec['resolved']==grade['resolved'] and grade['instanceId']==ID and grade['swebenchVersion']=='3.0.0' and grade['verifiedSourceFiles']==50 and grade['modelRequests']==0
 assert grade['patchSha256']==sha(pilot/'prediction.patch')==rec['patchSha256']
 assert grade['officialReport'][ID]['resolved']==grade['resolved']
 paths=[original,SOURCE/'protocol.json',out/'gateway.log',out/'gateway-evidence-export.json',out/'policy.json',out/'state.json',out/'grading.json',out/'scorer.log',out/'run.log',SOURCE/(ID+'-on-0.runner.log')]+list(pilot.glob('*.json'))+[pilot/'prediction.patch']
 evidence={'status':'AUDITED_COMPLETED_CASE_WITH_RAW_WIRE_GAP','sourceRecord':str(original.relative_to(P)),'files':{str(p.relative_to(P)):sha(p) for p in paths},'instanceId':ID,'thinking':'on','calls':17,'resolved':grade['resolved'],'realTaskReplay':False,'rescore':False,'sourceRevision':read(SOURCE/'protocol.json')['revision'],'reasoningChars':sum(r['reasoningChars'] for r in responses),'knownTokens':rec['totalTokens'],'rawWireBytesAvailable':False,'limitation':'Original request/response bytes were lost by Docker tmpfs archive export. Logged actual flag, complete service/native reasoning, usage, native reconstruction and official patch grade are verified; original byte hashes cannot be rechecked. Preserve this failed-export attempt and its score without replay.'}
 return evidence,rec

def carry(audit):
 evidence,rec=verify();assert read(audit)==evidence,'Completed-case audit changed'
 source=read(SOURCE/'protocol.json')
 evidence['auditFile']=str(audit.relative_to(P));evidence['auditSha256']=sha(audit)
 rec=dict(rec,status='CLOSED_GRADED',auditRepair=evidence,serviceThinkingEvidence={'status':'PASS_LOGGED_SERVICE_NATIVE_THINKING_WITH_RAW_WIRE_GAP','thinking':'on','requests':17,'reasoningChars':evidence['reasoningChars'],'nativeReasoningChars':evidence['reasoningChars'],'rawWireBytesAvailable':False})
 return rec,source,evidence

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args();e,_=verify()
 if a.output:a.output.write_text(json.dumps(e,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in e.items() if k!='files'},ensure_ascii=False))
if __name__=='__main__':main()
