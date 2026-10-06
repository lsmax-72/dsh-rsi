#!/usr/bin/env python3
"""Official scorer controls for correctness vs termination; no model or task execution."""
import ast,argparse,hashlib,json,re
from pathlib import Path
from personamem_answer_diagnostics import diagnose_answer_format,official_parser_controls
p=argparse.ArgumentParser();p.add_argument('--scorer-source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();assert not args.output.exists()
project=Path(__file__).resolve().parent.parent
source=args.scorer_source.read_text();tree=ast.parse(source);klass=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Evaluation');method=next(n for n in klass.body if isinstance(n,ast.FunctionDef) and n.name=='extract_answer');assert hashlib.sha256(ast.get_source_segment(source,method).encode()).hexdigest()=='a619e9665cc3d12e82de4876843c979cbd3e6e6781a8fe1c184fd697583935ae'
# Execute only the pinned official method and actual production scoring wrapper, not upstream client imports.
wrapper=ast.parse((project/'scripts/score-personamem-pilot.py').read_text());func=next(n for n in wrapper.body if isinstance(n,ast.FunctionDef) and n.name=='grade_saved_answer');namespace={'re':re,'diagnose_answer_format':diagnose_answer_format};module=ast.Module(body=[ast.ClassDef(name='Evaluation',bases=[],keywords=[],body=[method],decorator_list=[]),func],type_ignores=[]);exec(compile(ast.fix_missing_locations(module),'verified-answer-boundary','exec'),namespace);grader=namespace['Evaluation']();cases=[]
for name,response,reason,correct,completed in [
 ('correct-but-truncated','<final_answer>(b)</final_answer>','max-tokens',True,False),
 ('wrong-but-completed','<final_answer>(a)</final_answer>','completed',False,True),
 ('ambiguous-but-completed','<final_answer>(a) (b)</final_answer>','completed',False,True),
 ('empty-after-error','','error',False,False),
 ('correct-but-interrupted','<final_answer>(b)</final_answer>','interrupted',True,False)]:
 row={'response':response,'stopReason':{'kind':reason}};actual=namespace['grade_saved_answer'](grader,row,'(b)');assert actual['correct']==correct and actual['completed']==completed,(name,actual);cases.append({'case':name,**actual})
result={'status':'PASS','cases':cases,'fixtureOnly':True,'realModelRequests':0,'actualScoresOverwritten':False,'officialMethodUnchanged':True,'parserHealth':official_parser_controls(grader)};args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
