#!/usr/bin/env python3
"""Statistical controls: correlated-question replication must not manufacture certainty."""
import importlib.util,json,argparse
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args();assert not args.output.exists()
root=Path(__file__).resolve().parent;loader=importlib.util.spec_from_file_location('cluster',root/'user-cluster-stats.py');module=importlib.util.module_from_spec(loader);loader.loader.exec_module(module)
def dataset(repeats):
 users=[]
 for person,b,r in [('u1',False,True),('u2',True,False)]:
  ids=[str(i) for i in range(repeats)];users.append({'personaId':person,'expectedQuestionIds':ids,'baseline':[{'questionId':q,'correct':b} for q in ids],'rsi':[{'questionId':q,'correct':r} for q in ids]})
 return {'plannedUserIds':['u1','u2'],'users':users}
a=module.paired_user_summary(dataset(1));b=module.paired_user_summary(dataset(100));assert a['macroAccuracyDifference']==b['macroAccuracyDifference']==0;assert a['confidenceInterval95']==b['confidenceInterval95']==[-1,1]
single=dataset(1);single['plannedUserIds']=['u1'];single['users']=single['users'][:1];assert module.paired_user_summary(single)['confidenceInterval95'] is None
missing=dataset(1);missing['users'][1]['rsi']=[];m=module.paired_user_summary(missing);assert m['macroAccuracyDifference'] is None and m['confidenceInterval95'] is None and m['incomplete']
result={'status':'PASS','fixtureOnly':True,'realModelRequests':0,'controls':['Replicating perfectly correlated questions 100 times within each user does not narrow the interval','Single user has no user-cluster interval','Missing planned user answers do not silently disappear from the comparison'],'twoUserDifference':a['macroAccuracyDifference'],'twoUserInterval':a['confidenceInterval95']};args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
