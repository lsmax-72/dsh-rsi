#!/usr/bin/env python3
"""Select untouched official users using public metadata; keep answers outside public input."""
import argparse,collections,csv,hashlib,json,random
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ['source','old-freeze','proposal','output']:p.add_argument('--'+name,type=Path,required=True)
 args=p.parse_args();root=args.output.resolve();assert not root.exists(),'Preserve every preparation';root.mkdir(parents=True);raw=args.source.resolve();provenance=json.loads((raw/'provenance.json').read_text())
 for name,info in provenance['files'].items():assert sha(raw/name)==info['sha256']
 old=json.loads(args.old_freeze.read_text());excluded={'0'}|{c['personaId'] for c in old['cases']};rows=list(csv.DictReader((raw/'questions_32k.csv').open()));contexts={}
 for line in (raw/'shared_contexts_32k.jsonl').read_text().splitlines():contexts.update(json.loads(line))
 groups=collections.defaultdict(list)
 for row in rows:groups[(row['persona_id'],row['shared_context_id'],int(row['end_index_in_shared_context']))].append(row)
 eligible=collections.defaultdict(list)
 for key,questions in groups.items():
  uid,cid,cutoff=key;history=contexts[cid][:cutoff]
  if uid not in excluded and len({q['question_id'] for q in questions})>=4 and sum(m['role']=='system' for m in history)>=4:eligible[uid].append(key)
 rng=random.Random(old['selectionSeed']);uids=sorted(eligible,key=int);rng.shuffle(uids);selected=uids[:8];assert len(selected)==8
 (root/'public').mkdir();(root/'scorer').mkdir();cases=[];answers={};protocol='Find the most appropriate model response and give your final answer (a), (b), (c), or (d) after the special token <final_answer>.'
 for uid in selected:
  key=rng.choice(sorted(eligible[uid]));_,cid,cutoff=key;questions=rng.sample(groups[key],4);history=contexts[cid][:cutoff];assert len(history)==cutoff
  body={'personaId':uid,'contextId':cid,'historyCutoffExclusive':cutoff,'history':history,'questions':[{'id':q['question_id'],'questionType':q['question_type'],'question':q['user_question_or_message'],'options':q['all_options'],'protocol':protocol} for q in questions]};public=root/'public'/('persona-'+uid+'.json');public.write_text(json.dumps(body,ensure_ascii=False)+'\n')
  cases.append({'personaId':uid,'contextId':cid,'cutoffExclusive':cutoff,'questionIds':[q['id'] for q in body['questions']],'historyMessages':len(history),'historyChars':sum(len(m['content']) for m in history),'historySegments':sum(m['role']=='system' for m in history),'questionTypes':[q['questionType'] for q in body['questions']],'publicInputSha256':sha(public)})
  answers.update({q['question_id']:q['correct_answer'] for q in questions})
 assert len(answers)==32;assert not set(answers).intersection(q for c in old['cases'] for q in c['questionIds']);(root/'scorer/answers.json').write_text(json.dumps(answers,indent=2)+'\n')
 proposal=json.loads(args.proposal.read_text());proposal.update(status='PREPARED_FRESH_USERS_NOT_FROZEN_NOT_RUN',purpose='Fresh users after an output-window repair. Original failed attempt and all costs remain separate.',datasetProvenance=provenance,supersedesForNewDispatchOnly={'oldFreezeSha256':sha(args.old_freeze),'excludedAllPriorFrozenUsers':sorted(excluded,key=int),'selectionUsesNoAnswersOrOutcomes':True},stagingOutput=str(root),realModelRequests=0,formalEvaluationStarted=False);proposal['persona'].update(excludedDevelopmentUsers=sorted(excluded,key=int),eligibleUsers=sorted(eligible,key=int),selectedUsers=selected,cases=cases)
 (root/'proposal.json').write_text(json.dumps(proposal,ensure_ascii=False,indent=2)+'\n');(root/'preparation.json').write_text(json.dumps({'status':'PREPARED_NOT_DISPATCHED','datasetProvenance':provenance,'publicCases':cases,'excludedUsers':sorted(excluded,key=int),'officialAnswersUsedForSelection':False,'realModelRequests':0},ensure_ascii=False,indent=2)+'\n');print(json.dumps({'status':'PREPARED_NOT_DISPATCHED','users':selected,'excludedUsers':sorted(excluded,key=int),'historyMessages':[c['historyMessages'] for c in cases],'questionCount':32,'budgets':proposal['persona']['budgetProposal'],'realModelRequests':0}))
if __name__=='__main__':main()
