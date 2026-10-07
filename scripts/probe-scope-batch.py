#!/usr/bin/env python3
"""Zero-model scheduler controls: concurrency, stopping, resume and detached lifetime."""
import importlib.util,json,os,subprocess,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('batch',Path(__file__).with_name('run-scope-study.py'));batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)

class Controls(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.p={'cases':[{'id':x} for x in ['a','b','c']],'batchWorkers':2,'budgets':{'backgroundCalls':20,'consumerCalls':4,'totalCalls':24}}
        batch.write(self.root/'protocol.json',self.p)
    def tearDown(self):self.tmp.cleanup()
    def good(self):return {'status':'CLOSED','exitCode':0,'elapsedSeconds':0,'knownTokens':10}
    def run_mock(self,worker,resume=False):
        with patch.object(batch,'validate'),patch.object(batch,'run_case',side_effect=worker),patch.object(batch,'summarize',return_value={'assetAudit':'PASS','knownChatTokens':30}):batch.run_batch(self.root,self.p,resume)
    def test_two_workers_and_no_duplicates(self):
        lock=threading.Lock();barrier=threading.Barrier(2);seen=[];active=0;peak=0
        def worker(root,p,cid):
            nonlocal active,peak
            with lock:seen.append(cid);active+=1;peak=max(peak,active)
            if cid in ['a','b']:barrier.wait(timeout=2)
            with lock:active-=1
            return self.good()
        self.run_mock(worker);self.assertEqual(peak,2);self.assertEqual(sorted(seen),['a','b','c'])
    def test_failure_closes_inflight_without_dispatching_third(self):
        barrier=threading.Barrier(2);seen=[];halt_saved=threading.Event();original=batch.write
        def writing(path,value):
            original(path,value)
            if path.name=='batch-state.json' and any(r['status']=='HALTED' for r in value['cases']):halt_saved.set()
        def worker(root,p,cid):
            seen.append(cid);barrier.wait(timeout=2)
            if cid=='a':return {'status':'HALTED','exitCode':1,'elapsedSeconds':0,'knownTokens':10}
            self.assertTrue(halt_saved.wait(2));return self.good()
        with patch.object(batch,'write',side_effect=writing):
            with self.assertRaisesRegex(ValueError,'Batch halted'):self.run_mock(worker)
        self.assertEqual(sorted(seen),['a','b']);self.assertEqual(batch.read(self.root/'batch-state.json')['status'],'HALTED')
    def test_resume_only_unstarted(self):
        batch.write(self.root/'batch-state.json',{'protocolSha256':batch.sha(self.root/'protocol.json'),'cases':[{'caseId':'a',**self.good()}]})
        seen=[]
        def worker(root,p,cid):seen.append(cid);return self.good()
        self.run_mock(worker,True);self.assertEqual(sorted(seen),['b','c'])
    def test_interrupted_case_is_not_retried(self):
        batch.write(self.root/'batch-state.json',{'protocolSha256':batch.sha(self.root/'protocol.json'),'cases':[{'caseId':'a','status':'RUNNING'}]})
        with self.assertRaisesRegex(ValueError,'Interrupted/unknown'):self.run_mock(lambda *a:self.fail('must not dispatch'),True)
    def test_stop_file_prevents_dispatch(self):
        (self.root/'STOP').touch();self.run_mock(lambda *a:self.fail('must not dispatch'))
        self.assertEqual(batch.read(self.root/'batch-state.json')['status'],'STOPPED')
    def test_budget_close_vs_missing_usage(self):
        a={'receipt':{'status':'ERROR','code':'BUDGET_EXHAUSTED','unknownActualUsage':0,'backgroundCalls':20,'consumerCalls':0,'actualRequests':20},'checks':{'durablePrefixReconstruction':True,'gatewayMatchesDispatches':True}}
        self.assertTrue(batch.may_continue(1,a,self.p['budgets']))
        a['receipt']['unknownActualUsage']=1;self.assertFalse(batch.may_continue(1,a,self.p['budgets']))
    def test_detached_child_outlives_launcher(self):
        child=self.root/'child.py';done=self.root/'finished'
        child.write_text('import os,time\nfrom pathlib import Path\nend=time.monotonic()+3\nwhile os.getppid()==int(os.environ["BATCH_TEST_PARENT"]) and time.monotonic()<end:time.sleep(.01)\nPath('+repr(str(done))+').write_text(str(os.getppid()!=int(os.environ["BATCH_TEST_PARENT"])))\n')
        module=str(Path(batch.__file__).resolve())
        launcher=f'import importlib.util,os\nfrom pathlib import Path\ns=importlib.util.spec_from_file_location("b",{module!r});b=importlib.util.module_from_spec(s);s.loader.exec_module(b)\nb.validate=lambda p:None\nb.__file__={str(child)!r}\nos.environ["BATCH_TEST_PARENT"]=str(os.getpid())\nb.start(Path({str(self.root)!r}),{{"batchWorkers":2}},False)\n'
        subprocess.run([sys.executable,'-B','-c',launcher],check=True,stdout=subprocess.DEVNULL)
        end=time.monotonic()+4
        while not done.exists() and time.monotonic()<end:time.sleep(.02)
        self.assertTrue(done.exists());self.assertEqual(done.read_text(),'True')

if __name__=='__main__':unittest.main()
