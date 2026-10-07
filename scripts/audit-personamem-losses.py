#!/usr/bin/env python3
import json,pathlib,argparse,hashlib
parser=argparse.ArgumentParser(description='Offline three-loss deep audit.')
parser.add_argument('--project',type=pathlib.Path,required=True)
parser.add_argument('--study-root',type=pathlib.Path)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args();R=args.project.resolve();S=(args.study_root or R/'.artifacts/personamem-native-v2-replication-20261006').resolve();O=args.output.resolve();O.mkdir(parents=True,exist_ok=True)
if (O/'three-loss-focus.json').exists():parser.error('Refusing to overwrite three-loss-focus.json')
configs=[('9',3,[25,48,69,125,131,135],['收藏','杂乱','极简','clutter','minimal','海报']),('12',1,[21,29,52,53],['ADR','枯燥','争端','案例','辩论']),('12',4,[27,62,83],['桌游','法律概念','策略','从做中学'])]
focus=[]
for pid,n,indices,words in configs:
 public=json.loads((S/f'public/persona-{pid}.json').read_text());qid=public['questions'][n-1]['id'];rp=S/f'persona-{pid}-rsi/state/pilot/persona-{pid}/model-requests.json';requests=json.loads(rp.read_text());selected=[]
 for i,req in enumerate(requests):
  if qid not in req.get('sessionId',''):continue
  for j,m in enumerate(req['messages']):
   c=m['content'];t=c if isinstance(c,str) else '\n'.join(x.get('text','') for x in c if isinstance(x,dict))
   if 'memory-scope' not in t:continue
   lines=[line for line in t.splitlines() if any(w.lower() in line.lower() for w in words)]
   selected.append({'requestArrayIndex':i,'messageArrayIndex':j,'reference':str(rp)+f'#/index/{i}/messages/{j}','relevantDeliveredAssetLines':lines})
 focus.append({'personaId':pid,'questionOrdinal':n,'questionId':qid,'actualDeliveryEvidence':selected,'sourceHistory': [{'publicHistoryArrayIndex':i,'role':public['history'][i]['role'],'content':public['history'][i]['content'],'reference':str(S/f'public/persona-{pid}.json')+f'#/history/{i}'} for i in indices]})
focus[0]['assessment']='当前请求同时交付卖海报缓解杂乱事件与global画像的怀旧收藏者/收藏纵深延伸叙述，画像未体现后续卖出与极简阶段；阶段偏重可观察。实际读画像两次及电影Skill后仅选c，无显式事实到选择推理，错误因果未知。'
focus[1]['assessment']='ADR合并条保留早期枯燥与后期课程正向，未发现该条与原史冲突；但早期29里明确真实应用/生动案例的细节被概括。RSI无显式引用，理由实际是a更详细、d更短；优先诊断决策标准，不先改提炼算法。'
focus[2]['assessment']='首请求检出法律桌游负向27条，但未在相关交付片段见较晚62的另一场正向桌游事实；这只证明相关检出片段缺失，尚未完整审计全部画像/其他记忆，不能声称所有交付均遗漏。Skill自然交付且最终a；无显式规则或资产引用，因果未知。'
sources={}
for path in [R/'docs/evidence/personamem-native-v2-outcome-20261007.json',*S.glob('public/*.json'),*S.glob('annotations/*.json'),*S.glob('review-packs/*.json')]: sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
for pid in ['9','12']:
 for path in [S/f'persona-{pid}-rsi/state/pilot/persona-{pid}/model-requests.json',*[S/f'persona-{pid}-{arm}/state/pilot/persona-{pid}/answers.json' for arm in ['baseline','rsi']]]: sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
for item in focus: item['assessmentType']='ASSISTANT_REVIEW_NOT_CAUSAL_ESTIMATE'; item['reviewedBy']='gpt-6.1-sol assistant'
with (O/'three-loss-focus.json').open('x') as f: f.write(json.dumps({'manualFocus':focus,'inputFileSha256':sources,'modelCalls':0,'learningInput':False},ensure_ascii=False,indent=2)+'\n')
print('Wrote three-loss-focus.json')
