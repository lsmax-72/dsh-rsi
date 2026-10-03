#!/usr/bin/env python3
"""Prepare a development pilot from verified official 32k files; answers remain scorer-only."""
from pathlib import Path
import ast,csv,json,hashlib,argparse
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args();root=args.output.resolve();raw=args.source.resolve();root.mkdir(parents=True,exist_ok=True);(root/'scorer').mkdir(exist_ok=True);provenance=json.loads((raw/'provenance.json').read_text())
for name,info in provenance['files'].items():assert hashlib.sha256((raw/name).read_bytes()).hexdigest()==info['sha256']
rows=list(csv.DictReader((raw/'questions_32k.csv').open()));contexts={}
for line in (raw/'shared_contexts_32k.jsonl').read_text().splitlines():contexts.update(json.loads(line))
# Development pilot only: first two questions with exactly the same user and history cutoff.
first=rows[0];keys=('persona_id','shared_context_id','end_index_in_shared_context');selected=[r for r in rows if all(r[k]==first[k] for k in keys)][:2]
cutoff=int(first['end_index_in_shared_context']);history=contexts[first['shared_context_id']][:cutoff]
assert len(history)==cutoff and all(m['role'] in ['system','user','assistant'] and isinstance(m['content'],str) for m in history)
instructions='Find the most appropriate model response and give your final answer (a), (b), (c), or (d) after the special token <final_answer>.'
public=root/'public';public.mkdir(exist_ok=True)
body={'personaId':first['persona_id'],'contextId':first['shared_context_id'],'historyCutoffExclusive':cutoff,'history':history,'questions':[{'id':r['question_id'],'questionType':r['question_type'],'prompt':r['user_question_or_message']+'\n\n'+instructions+'\n\n'+r['all_options']} for r in selected]}
(public/'pilot.json').write_text(json.dumps(body,ensure_ascii=False)+'\n')
(root/'scorer/answers.json').write_text(json.dumps({r['question_id']:r['correct_answer'] for r in selected},indent=2)+'\n')
# Extract the official grading method unchanged; never execute upstream imports or inference code.
tree=ast.parse((raw/'inference_standalone_openai.py').read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Evaluation');method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='extract_answer')
source=ast.get_source_segment((raw/'inference_standalone_openai.py').read_text(),method)
(root/'scorer/official_grader.py').write_text('import re\nclass Evaluation:\n'+''.join('    '+line+'\n' for line in source.splitlines()))
# Golden/wrong/ambiguous controls run with the exact extracted official function.
namespace={};exec((root/'scorer/official_grader.py').read_text(),namespace);grader=namespace['Evaluation']()
controls=[('<final_answer>(b)</final_answer>','(b)',True),('<final_answer>(a)</final_answer>','(b)',False),('<final_answer>(a) (b)</final_answer>','(b)',False)]
for text,answer,expected in controls:assert grader.extract_answer(text,answer)[0] is expected
receipt={'status':'PREPARED_NOT_RUN','datasetRevision':provenance['datasetRevision'],'githubRevision':provenance['githubRevision'],'datasetRows':len(rows),'datasetUsers':len(set(r['persona_id'] for r in rows)),'personaId':body['personaId'],'questionIds':[q['id'] for q in body['questions']],'historyCutoffExclusive':cutoff,'historyMessages':len(history),'historyChars':sum(len(m['content']) for m in history),'publicInputSha256':hashlib.sha256((public/'pilot.json').read_bytes()).hexdigest(),'scorerFunctionSha256':hashlib.sha256(source.encode()).hexdigest(),'scorerControlsPassed':3,'roleCounts':{r:sum(m['role']==r for m in history) for r in ['system','user','assistant']},'answerFileOutsidePublicInput':True,'realModelRequests':0,'formalEvaluationStarted':False}
(root/'preparation.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
