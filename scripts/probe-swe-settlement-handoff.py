#!/usr/bin/env python3
"""Native container learning/hand-off regression with fixed replies; no asset consumption acceptance or Qwen."""
import argparse, importlib.util, json, sys
from pathlib import Path
P=Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location('continuous',P/'scripts/run-swe-continuous.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=a.output.resolve();m.require(not root.exists(),'Preserve regression attempts');root.mkdir(parents=True)
 cases=m.read(P/'docs/evidence/thinking-environments-20261008.json')['environments'][2:4]
 seeds={'rsi':P/'.artifacts/swe-continuous-development-20261009/002-rsi/state','baseline':P/'.artifacts/continuous-native-fork-fixture-20261009/001-baseline/state'}
 histories={'rsi':['django__django-11848','django__django-11551'],'baseline':['django__django-11848']};inventory=m.asset_inventory(seeds['rsi']);checks=[]
 for pos,c in enumerate(cases,1):
  for arm in m.ARMS:
   old=seeds[arm];out=root/m.key(pos,arm);order=root/(m.key(pos,arm)+'.order.json');m.write(order,histories[arm]);cmd=[sys.executable,'-B',P/'scripts/probe-runner.py','--fixture','--arm',arm,'--image',c['taskTag'],'--instance',c['instanceId'],'--output',out,'--history-order',order,'--dispatch-limit','4','--request-limit','24' if arm=='rsi' else '4','--learning-call-budget','40' if arm=='rsi' else '0','--learning-dispatch-limit','20' if arm=='rsi' else '0','--wall-seconds','120','--settle-seconds','120' if arm=='rsi' else '0','--baseline-date',c['baselineDate'],'--expected-tree',c['expectedTree'],'--expected-version',c['expectedVersion']]
   if arm=='rsi':cmd+=['--fixture-learning','--seed-assets',old/'assets','--seed-sessions',old/'home/sessions']
   else:cmd+=['--baseline-history',old/'home/sessions']
   rc=m.thinking.execute(cmd,root/(m.key(pos,arm)+'.log'),timeout=500);m.require(rc==0,'Native regression failed, retained log: '+str(out))
   pilot=out/'state/pilot'/c['instanceId'];r=m.read(pilot/'receipt.json');initial=m.read(pilot/'initial.json');recon=m.read(pilot/'reconstruction.json');ledger=m.read(pilot/'model-requests.json');inherited=m.read(pilot/'history-inheritance.json')
   m.require(r['fixture'] and not r['formalBenchmark'] and r['nativeFiberDisposed'] and not (out/'gateway.log').exists(),'Fixture/closure/isolation violation')
   m.require(all(x['matches'] for x in recon) and len(recon)==len(ledger),'Native actual input reconstruction failed')
   m.require(initial['baselineTree']==c['expectedTree'] and initial['djangoVersion']==c['expectedVersion'],'Source reset failed')
   hashes=m.files(old/'home/sessions');m.require(m.read(out/'source-snapshot.json')['inputSha256']['sessions']==hashes and all(m.sha(out/'state/home/sessions'/f)==h for f,h in hashes.items()),'Raw history changed')
   parent=[json.loads(line) for line in (old/'home/sessions/--workspace--'/inherited['parentSessionId']/'session.v4.jsonl').read_text().splitlines()][1:];child=[json.loads(line) for line in (out/'state/home/sessions/--workspace--'/('pilot-'+c['instanceId']+'-task')/'session.v4.jsonl').read_text().splitlines()];m.require(child[1:1+len(parent)]==parent,'Native inherited prefix changed')
   if arm=='rsi':
    wait=r['learningSettlements'][0];m.require(wait['status']=='COMPLETED' and wait['waitMs']<120000,'Native work did not settle before deadline')
    oldjobs={j['id'] for j in m.read(old/'pilot'/('django__django-11551' if pos==1 else cases[0]['instanceId'])/'receipt.json')['after']['jobs']};newjobs=r['after']['jobs'];current=[j for j in newjobs if j['id'] not in oldjobs]
    m.require(len(current)==1 and current[0]['session']=='pilot-'+c['instanceId']+'-task' and current[0]['status']=='completed','Missed or duplicate task learning')
    m.require(m.asset_inventory(out/'state')==inventory,'Original natural assets lost or rewritten by the fixture')
   checks.append({'position':pos,'arm':arm,'actualNativeCalls':len(ledger),'learningCalls':r['backgroundDispatches'],'wait':r['learningSettlements'][0],'oldLogsByteExact':True,'nativePrefixExact':True,'naturalAssetsUnchanged':arm=='rsi','newLearningJobs':1 if arm=='rsi' else 0})
   seeds[arm]=out/'state';histories[arm].append(c['instanceId']);m.write(root/'progress.json',{'completed':len(checks),'planned':4})
 result={'status':'PASS_SETTLEMENT_NATIVE_HANDOFF','fixtureModel':True,'realQwenRequests':0,'scorerInvocations':0,'newAssetConsumptionSpecialty':False,'checks':checks,'mechanismSha256':m.mechanism_hashes()};m.write(root/'audit.json',result);print(json.dumps(result))
if __name__=='__main__':main()
