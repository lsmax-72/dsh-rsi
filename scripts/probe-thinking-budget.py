#!/usr/bin/env python3
"""Saved real cancellation audit plus offline batch faults; never call the model."""
import argparse,copy,hashlib,importlib.util,json,subprocess,sys,tempfile,time
from pathlib import Path
P=Path(__file__).resolve().parent.parent
OLD=P/'.artifacts/thinking-preexperiment-v4-20261008'
def load(name):
 s=importlib.util.spec_from_file_location(name,P/'scripts'/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
runner=load('probe-runner');controller=load('run-thinking-preexperiment');reporter=load('report-thinking-preexperiment')
def read(p):return json.loads(p.read_text())
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);a=parser.parse_args();checks=[];actual=OLD/'django__django-11815-on-0'
 try:runner.verify_thinking_wire(actual,'on',write_result=False)
 except AssertionError:pass
 else:raise AssertionError('Strict gate accepted unfinished stream')
 evidence=runner.verify_thinking_wire(actual,'on',allow_budget_abort=True,write_result=False);assert evidence['budgetAbortedRequestIds']==[34] and evidence['reasoningChars']==evidence['nativeReasoningChars']
 checks.append('saved real wall-budget cancellation retains exact partial bytes and actual Thinking proof, no replay')
 with tempfile.TemporaryDirectory() as td:
  root=Path(td);started=time.monotonic();rc=controller.execute([sys.executable,'-B','-c','import time; time.sleep(10)'],root/'timeout.log',timeout=.1);assert rc==124 and time.monotonic()-started<5;assert 'OUTER_PROCESS_TIMEOUT' in (root/'timeout.log').read_text();checks.append('actual hanging child process terminates within configured outer timeout')
  batch=root/'batch';batch.mkdir();visited=[];saved_run=controller.run_case
  def case(out,s,e,mode):
   visited.append((e['instanceId'],mode));n=len(visited);r={'instanceId':e['instanceId'],'thinking':mode,'status':'CLOSED_INFRA' if n in [2,5,7] else 'CLOSED_GRADED','resolved':None if n in [2,5,7] else False,'startedAt':0,'finishedAt':1,'error':'synthetic model/scorer/audit exception' if n in [2,5,7] else None,'firstRequest':{'messagesSha256':'a'*64,'toolsSha256':'b'*64,'maxOutputTokens':8192}}
   write(out/(e['instanceId']+'-'+mode+'-0.record.json'),r);return r
  controller.run_case=case;spec={'environments':[{'instanceId':i} for i in controller.IDS]};controller.run(batch,spec,False);assert len(visited)==16 and len(set(visited))==16 and read(batch/'state.json')['status']=='COMPLETE';assert read(batch/'summary.json')['netSolvedOnMinusOff'] is None
  count=len(visited);controller.run(batch,spec,True);assert len(visited)==count;controller.run_case=saved_run;checks.append('all 16 planned cases visited despite model/scorer/audit case errors, and resume never replays failures')
  def refuse(s):raise RuntimeError('synthetic frozen model/source mismatch')
  controller.validate=refuse;guard=root/'guard';guard.mkdir();r=controller.run_case(guard,{}, {'instanceId':controller.IDS[0]},'on');assert r['status']=='HALTED' and 'runnerReturnCode' not in r;checks.append('frozen model/source guard still prevents dispatch rather than running invalid inputs')
  # Exercise full final-analysis logic using explicitly synthetic copies of
  # already saved traces. Scores are fixture values, never new experiment data.
  analysis=root/'analysis';analysis.mkdir();protocol=read(OLD/'protocol.json');write(analysis/'protocol.json',protocol);(analysis/'protocol.sha256').write_text(reporter.sha(analysis/'protocol.json'));write(analysis/'state.json',{'status':'COMPLETE'});write(analysis/'summary.json',{'status':'COMPLETE'})
  for index,id in enumerate(controller.IDS):
   template=id if index<4 else controller.IDS[1]
   for mode in ['off','on']:
    r=copy.deepcopy(read(OLD/(template+'-'+mode+'-0.record.json')));old_out=Path(r['output']);new_out=analysis/(id+'-'+mode);pilot=new_out/'state/pilot'/id;pilot.parent.mkdir(parents=True);pilot.symlink_to(old_out/'state/pilot'/template,target_is_directory=True)
    (new_out/'gateway.log').symlink_to(old_out/'gateway.log');(new_out/'gateway-evidence').symlink_to(old_out/'gateway-evidence',target_is_directory=True)
    grade=read(Path(r['grading']));grade['instanceId']=id;write(new_out/'grading.json',grade);r.update(instanceId=id,output=str(new_out),grading=str(new_out/'grading.json'))
    if template==controller.IDS[3] and mode=='on':r.update(status='CLOSED_GRADED',serviceThinkingEvidence=evidence,costComplete=False)
    write(analysis/(id+'-'+mode+'.record.json'),r)
  result=reporter.analyze(analysis);assert not result['errors'],result['errors'];assert result['recommendationThinking']=='on' and result['paired']['onOnly']==1 and result['onToOffTokenRatio'] is None and result['totals']['on']['unknownUsageRequests']==1 and not result['costComplete'];assert '≥1,046,024' in (analysis/'report.md').read_text();checks.append('full report includes canceled-task official win; missing usage is a lower bound, not an exact cost ratio')
  # With equal official outcomes the missing cost cannot decide a token tie.
  file=analysis/(controller.IDS[3]+'-on.record.json');r=read(file);r['resolved']=False;write(Path(r['grading']),{**read(Path(r['grading'])),'resolved':False});write(file,r);result=reporter.analyze(analysis);assert result['recommendationThinking'] is None and not result['errors'];checks.append('equal scores with missing total usage cannot select a mode by incomplete token totals')
 result={'status':'PASS_THINKING_BUDGET_AND_BATCH_CONTINUATION','realProviderRequests':0,'scorerInvocations':0,'dockerOperations':0,'checks':checks,'fixtureScoresAreExperimentResults':False}
 if a.output:write(a.output,result)
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
