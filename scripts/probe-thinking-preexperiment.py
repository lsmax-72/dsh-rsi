#!/usr/bin/env python3
"""Exercise actual preexperiment case/controller code with local artifact fixtures only."""
import argparse,hashlib,importlib.util,json,tempfile
from pathlib import Path
P=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('thinking',P/'scripts/run-thinking-preexperiment.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args();checks=[];m.validate=lambda s:None;commands=[];fault={'kind':None}
 e={'instanceId':m.IDS[0],'taskTag':'fixture','baselineDate':'@0 +0000','expectedTree':'fixturetree','expectedVersion':'3.0'};s={'environments':[e]}
 def execute(argv,log):
  cmd=[str(x) for x in argv];commands.append(cmd);get=lambda k:Path(cmd[cmd.index(k)+1])
  if cmd[2].endswith('probe-runner.py'):
   out=get('--output');id=cmd[cmd.index('--instance')+1];mode=cmd[cmd.index('--thinking')+1];pilot=out/'state/pilot'/id;pilot.mkdir(parents=True);usage={'inputTokens':11,'outputTokens':7,'totalTokens':18}
   if fault['kind']=='null-usage':usage={'inputTokens':None,'outputTokens':None,'totalTokens':None}
   m.write(pilot/'model-requests.json',[{'sessionId':'task','phase':'task','status':'RETURNED','usage':usage,'finish':{'kind':'stop'}}]);m.write(pilot/'tool-results.json',[]);m.write(pilot/'phases.json',[{'wallMs':1000,'stopReason':{'kind':'completed'}}]);m.write(pilot/'initial.json',{'assets':None,'toolSchemas':['bash']});m.write(pilot/'receipt.json',{'arm':'baseline','backgroundDispatches':0,'formalBenchmark':True,'fixture':False,'instanceId':id});m.write(pilot/'reconstruction.json',[{'sessionId':'task','request':1,'matches':fault['kind']!='bad-reconstruction','responseFramePresent':True}]);(pilot/'prediction.patch').write_text('fixture patch')
   if fault['kind']=='missing-native-ledger':(pilot/'model-requests.json').unlink()
   first={'request':1,'model':'qwen3.8-27b','enableThinking':mode=='on','messagesSha256':'a'*64,'toolsSha256':'b'*64,'maxOutputTokens':8192,'temperature':None}
   if fault['kind']=='missing-first':first.pop('messagesSha256');first.pop('toolsSha256')
   response={'responseRequest':1,'usage':[{'prompt_tokens':11,'completion_tokens':7,'total_tokens':18,'completion_tokens_details':{'reasoning_tokens':4 if mode=='on' else 0}}]}
   if fault['kind']=='null-usage':response['usage']=[]
   if fault['kind']=='missing-thinking-usage':response['usage'][0]['completion_tokens_details']['reasoning_tokens']=None
   (out/'gateway.log').write_text(json.dumps(first)+'\n'+json.dumps(response)+'\n');m.write(out/'thinking-wire.json',{'status':'PASS_ACTUAL_THINKING_WIRE','thinking':mode,'requests':1,'reasoningChars':5 if mode=='on' else 0,'nativeReasoningChars':5 if mode=='on' else 0})
  else:m.write(get('--output'),{'instanceId':e['instanceId'],'resolved':False,'patchSha256':hashlib.sha256(b'fixture patch').hexdigest()})
  return 0
 m.execute=execute
 with tempfile.TemporaryDirectory() as td:
  base=Path(td)
  for mode in ['off','on']:
   root=base/mode;root.mkdir();rec=m.run_case(root,s,e,mode);assert rec['status']=='CLOSED_GRADED',rec;assert rec['thinkingTokens']==(4 if mode=='on' else 0),rec
   cmd=commands[-2];assert cmd[cmd.index('--arm')+1]=='baseline' and '--verify-thinking-wire' in cmd;assert cmd[cmd.index('--dispatch-limit')+1]=='40' and cmd[cmd.index('--wall-seconds')+1]=='1200' and cmd[cmd.index('--learning-dispatch-limit')+1]=='0';assert not any(x in cmd for x in ['--seed-assets','--seed-sessions','--baseline-history','--learning-pool'])
   before=len(commands)
   try:m.run_case(root,s,e,mode)
   except RuntimeError:pass
   else:raise AssertionError('Existing arm automatically repeated')
   assert len(commands)==before
  fault['kind']='missing-thinking-usage';root=base/'unknown-thinking-tokens';root.mkdir();rec=m.run_case(root,s,e,'on');assert rec['status']=='CLOSED_GRADED' and rec['thinkingTokens'] is None,rec;fault['kind']=None
  checks.append('missing reasoning-token detail remains unknown without inferring tokens from Unicode chars')
  checks+=['actual run_case consumes real reconstruction array and raw SSE usage-list shape','on/off command shares 40 calls 1200 seconds and zero RSI/history','saved attempts cannot dispatch again']
  for failure in ['bad-reconstruction','null-usage','missing-first']:
   fault['kind']=failure;root=base/failure;root.mkdir();rec=m.run_case(root,s,e,'on')
   if failure=='null-usage':assert rec['status']=='CLOSED_GRADED' and not rec['costComplete'] and rec['unknownUsageRequests']==1,rec
   else:assert rec['status']=='CLOSED_INFRA',rec
   if failure!='missing-first':assert rec['resolved'] is False,'Saved patch grading should survive case audit failure'
  fault['kind']='missing-native-ledger';root=base/'missing-native-ledger';root.mkdir();rec=m.run_case(root,s,e,'on');assert rec['status']=='CLOSED_INFRA' and rec['calls']==1 and rec['totalTokens']==18 and rec['usageRecoveredFromService']==[1],rec
  checks.append('missing native export retains actually reported service cost and flags the task as infrastructure')
  checks.append('unknown usage keeps valid grade and lower-bound cost; case audit errors remain diagnostic infrastructure')
  fault['kind']='bad-reconstruction';root=base/'controller';root.mkdir();m.run(root,s,False)
  rows=[m.read(f) for f in root.glob('*.record.json')];assert len(rows)==2 and all(r['status']=='CLOSED_INFRA' for r in rows),'Both modes must run despite case audit errors'
  before=len(commands);m.run(root,s,True);assert len(commands)==before,'Resume must never replay terminal failures';checks.append('serial controller visits both modes despite case audit errors; saved failures are never retried')
 result={'status':'PASS_OFFLINE_THINKING_CONTROLLER','realProviderRequests':0,'dockerOperations':0,'checks':checks,'execution':'actual run_case/run with local monkeyexecute artifact fixtures; no task or official scorer dispatched'}
 if a.output:m.write(a.output,result)
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
