#!/usr/bin/env python3
"""Four real isolated container runs with fixture LLM; no Qwen calls or grading."""
import argparse, importlib.util, json, subprocess, sys
from pathlib import Path
P=Path(__file__).resolve().parent.parent
sp=importlib.util.spec_from_file_location('continuous',P/'scripts/run-swe-continuous.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--compact',action='store_true',help='Exercise native idle compaction before the child task');parser.add_argument('--carry-first-from',type=Path,help='Reuse verified first fixture states, run only the new child-entry audit');a=parser.parse_args();root=a.output.resolve();m.require(not root.exists(),'Preserve previous checks');root.mkdir(parents=True)
    if a.carry_first_from:
        proof=m.read(a.carry_first_from/'audit.json');m.require(proof['fixtureModel'] is True and proof['realModelRequests']==0,'Only fixture evidence may be reused')
    env=m.read(P/'docs/evidence/thinking-environments-20261008.json')['environments'][:2];seeds={arm:None for arm in m.ARMS};checks=[]
    for position,c in enumerate(env,1):
        for arm in m.ARMS:
            out=root/m.key(position,arm);orderfile=root/(m.key(position,arm)+'.order.json');m.write(orderfile,[e['instanceId'] for e in env[:position-1]])
            cmd=[sys.executable,'-B',P/'scripts/probe-runner.py','--fixture','--image',c['taskTag'],'--arm',arm,'--instance',c['instanceId'],'--output',out,'--history-order',orderfile,'--dispatch-limit','4','--request-limit','4','--learning-call-budget','0','--learning-dispatch-limit','0','--wall-seconds','120','--settle-seconds','0','--baseline-date',c['baselineDate'],'--expected-tree',c['expectedTree'],'--expected-version',c['expectedVersion']]
            if a.compact:cmd+=['--fixture-compact']
            old=seeds[arm]
            if old:
                if arm=='rsi':cmd+=['--seed-assets',old/'assets','--seed-sessions',old/'home/sessions']
                else:cmd+=['--baseline-history',old/'home/sessions']
            if arm=='rsi':cmd+=['--embedding-model',P/'.artifacts/models/embeddinggemma-300m-qat-Q8_0.gguf']
            if position==1 and a.carry_first_from:
                m.shutil.copytree(a.carry_first_from/m.key(position,arm),out);rc=0
            else:rc=m.thinking.execute(cmd,root/(m.key(position,arm)+'.runner.log'),timeout=360)
            m.require(rc==0,'Native fixture container failed: '+str(out));pilot=out/'state/pilot'/c['instanceId'];receipt=m.read(pilot/'receipt.json');initial=m.read(pilot/'initial.json');requests=m.read(pilot/'model-requests.json');recon=m.read(pilot/'reconstruction.json');policy=m.read(out/'policy.json')
            m.require(receipt['fixture'] is True and receipt['formalBenchmark'] is False and receipt['nativeFiberDisposed'] is True and receipt['backgroundDispatches']==0,'Fixture invoked real/formal/learning execution')
            m.require(len(requests)==len(recon) and all(r['matches'] for r in recon) and all(r['status']=='RETURNED' for r in requests),'Real native persistence/model reconstruction failed')
            m.require(policy['hostBinds']==[] and policy['networkInternal'] is True and policy['rootfsReadOnly'] is True and not (out/'gateway.log').exists(),'Fixture isolation or zero-provider proof failed')
            m.require(initial['baselineTree']==c['expectedTree'] and initial['djangoVersion']==c['expectedVersion'],'Fresh source reset failed')
            if old:
                snap=m.read(out/'source-snapshot.json');m.require(snap['inputSha256']['sessions']==m.files(old/'home/sessions'),'Wrong own history restored')
                m.require(all(m.sha(out/'state/home/sessions'/n)==h for n,h in m.files(old/'home/sessions').items()),'Prior raw history changed')
                oldid='pilot-'+env[0]['instanceId']+'-task';m.require([r['sessionId'] for r in initial['priorTaskLogs']]==[oldid],'Frozen chronology differs')
                text='\n'.join(b.get('text','') for r in requests for msg in r['messages'] if (msg.get('toolCallId') or '').startswith('fixture-history-read-') for b in msg.get('content',[]))
                m.require(oldid in text and 'isolated change' in text,'Actual later model request did not receive the original prior tool result')
                inherited=m.read(pilot/'history-inheritance.json');m.require(inherited['parentSessionId']==oldid and inherited['inheritedEventCount']>0,'Missing native inherited prefix')
                parent=[json.loads(line) for line in (old/'home/sessions'/initial['priorTaskLogs'][0]['relativePath']).read_text().splitlines()][1:]
                m.require(m.sha(old/'home/sessions'/initial['priorTaskLogs'][0]['relativePath'])==m.sha(out/'state/home/sessions'/initial['priorTaskLogs'][0]['relativePath']),'Parent bytes changed')
                if a.compact:
                    m.require((pilot/'fixture-compaction.json').is_file(),'Native compaction did not commit')
                    compact=[r for r in requests if r['purpose']=='compaction'];normal=[r for r in requests if r['purpose']!='compaction']
                    m.require(len(compact)==1 and len(requests)==receipt['taskDispatches']==4,'Compaction did not consume a foreground call')
                    m.require(any('已完成前序隔离任务' in json.dumps(r['messages'],ensure_ascii=False) for r in normal),'Native summary absent from subsequent model context')
                else:
                    first={msg['id']:msg for msg in requests[0]['messages']}
                    for previous in inherited['parentMessages']:
                        if previous['role']=='system':continue
                        m.require(previous['id'] in first and m.hashlib.sha256(json.dumps(first[previous['id']]['content'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()==previous['contentSha256'],'Prior raw conversational content not in first actual child request')
                # Native fixture learning is off, but capture still records jobs:
                # only the two child-owned task turns may be queued.
                if arm=='rsi':
                    db=m.sqlite3.connect(out/'state/assets/rsi-state.sqlite')
                    count=db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0];db.close()
                    m.require(count==2,'Fork inherited old turns were enqueued again')

                if arm=='rsi':m.require(snap['inputSha256']['assets']==m.files(old/'assets'),'RSI prior native assets not copied exactly')
            else:m.require(initial['priorTaskLogs']==[] and not (out/'source-snapshot.json').exists(),'First task has prior history')
            checks.append({'position':position,'arm':arm,'carriedFirstFixture':bool(position==1 and a.carry_first_from),'nativeCompaction':bool(a.compact and old),'nativeCalls':len(requests),'sourceTreeVerified':True,'directNativeHistoryInFirstRequest':bool(old) and not a.compact,'historyByteExact':bool(old),'priorHistoryDeliveredToFixtureRequest':bool(old),'naturalAssetRestoreVerified':arm=='rsi' and bool(old),'realModelRequests':0})
            seeds[arm]=out/'state';m.write(root/'progress.json',{'completed':len(checks),'checks':checks})
    result={'status':'PASS_NATIVE_CONTAINER_CONTINUOUS_STATE','realModelRequests':0,'officialScorerInvocations':0,'fixtureModel':True,'checks':checks,'limitation':'Actual native fork inheritance, agents/tools/persistence/container restore and no duplicate inherited-turn capture verified with fixed model replies; no natural asset generation, Qwen quality or formal effect proof.'};m.write(root/'audit.json',result);print(json.dumps(result))
if __name__=='__main__':main()
