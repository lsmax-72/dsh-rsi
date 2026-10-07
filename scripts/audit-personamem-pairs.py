#!/usr/bin/env python3
import json,re,pathlib,sys,hashlib,collections,argparse
parser=argparse.ArgumentParser(description='Offline paired answer audit; never rescoring.')
parser.add_argument('--project',type=pathlib.Path,required=True)
parser.add_argument('--study-root',type=pathlib.Path)
parser.add_argument('--output',type=pathlib.Path,required=True)
args=parser.parse_args()
ROOT=args.project.resolve();STUDY=(args.study_root or ROOT/'.artifacts/personamem-native-v2-replication-20261006').resolve();OUT=args.output.resolve()
OUT.mkdir(parents=True,exist_ok=True)
for name in ['paired-audit.json','paired-audit.md']:
 if (OUT/name).exists(): parser.error(f'Refusing to overwrite {OUT/name}')
sys.path.insert(0,str(ROOT/'scripts'))
from personamem_answer_diagnostics import diagnose_answer_format
report=json.loads((ROOT/'docs/evidence/personamem-native-v2-outcome-20261007.json').read_text())
notes={
('9',3):('无推理的选择变更；资产适用性疑点','基线以收藏杂乱、卖海报及极简倾向选a；RSI只选c。已保存注释证明重复读画像、加载电影推荐Skill；是否适用于本题仍需核对；缺少规则到选项推理，不能归因错误。'),
('12',1):('选项比较标准偏移','基线引用ADR枯燥/渴望真实案例选d；RSI认为a更详细、d太短，未解释该历史约束。固定召回含过去枯燥与后来课程改善；这不证明资产导致偏移。'),
('12',4):('泛化聊天与个性化桥接差异','基线最终用法律/策略兴趣桥接历史拼图选d；RSI先自由回应、选a。闲聊Skill确实交付，但无显式规则引用，不能把错误归于简短/共情规则，也不能认定该聊天任务不适用。'),
('14',4):('两组均错；身份与行为历史权重差异','基线显式讨论身份画像与音乐史冲突，偏重文化身份/尤克里里选d；RSI只选b。代码Skill跨域加载发生在Q1且Q1两组均对，不可移植为Q4错因。'),
('3',2):('两组均错；约束权重差异','基线偏重新颖及文化身份选d；RSI明确引用Memory/Scene与历史，偏重放松、旅行疲惫与陶艺疗愈选b。旅行条目遗漏后续疲惫可观察，但RSI推理实际考虑疲惫；不是漏记导致该错误的证据。'),
('3',3):('两组均错；时间/事件解析待诊断','基线显式区分首次卡拉OK焦虑与较晚正向经历，最终选d；RSI只选b。两次体验不能合并成单一永久偏好；没有RSI决策链，因果未知。'),
('17',1):('两组均错；推荐权重差异','基线偏重自由与小团体选b；RSI自然搜索后区分阅读马拉松正向与后来压力，以深度交流选c。历史阶段已在RSI推理体现；Cosplay态度省略属资产问题，尚不能归因本题。'),
('17',3):('官方改善；跨领域偏好类比','基线仅选a；RSI以近期自由/低压力倾向以及阅读/电影历史类比绘画自主活动选b。两组都有完整历史，未证明增量Memory贡献，且无Skill自然加载。'),
('19',1):('两组均错；无RSI决策证据','基线权衡私密日记、艺术挫折与旅行vlog，选a；RSI加载多话题聊天Skill后只选c。一般策略类比与正文交付可观察，不足以证明规则导致错误。'),
('19',4):('两组均错；无RSI决策证据','基线用远离网红/偏好本地真实体验选a；RSI加载旅行聊天Skill后只选b。Skill投资挑战例证归属错误在另一话题，不能据此认定它导致本题文化体验错答。'),
('15',3):('两组均错；风格权重与泛化回应差异','基线较长推理先质疑c跳跃，最终因历史助手长回应风格选c；RSI加载理财Skill后只选b。投资社区阶段在Skill遗漏属已观察质量问题，尚无本题纪录片选择因果证据。'),
('9',2):('同选项而官方不同；解析干扰','两组明确首选c；基线尾部解释含a/b/d，官方false；RSI单一尾部c官方true。严格诊断非单选不等于公开协议违约；主结果不重算。'),
('9',4):('同选项均对；严格格式异常','RSI尾部为c及回应正文，官方true；严格单选诊断false。此事实不能推广成所有尾部正文都会误判。'),
('14',3):('同选项均对；严格格式异常','RSI尾部为d及回应正文，官方true；严格单选诊断false。'),
('12',2):('同选项均对；题目重复选项','两组b且官方true；既有证据记录b/d文字重复，不能将其视为明确可区分的唯一语义正确题。'),
('17',2):('同选项均对；题干/选项错配','两组d且官方true；题干绘画而四选项阅读，RSI和基线均发现错配。官方正确不等于题目语义健康。'),
('14',1):('同选项均对；明确跨领域Skill加载','音乐表达题加载仅针对代码重构Skill，适用性不符明确；最终两组a且正确，未证明造成答错。'),
('15',2):('同选项均对；阶段泛化风险','RSI逐字引用Memory中过去回避论坛/后来加入新社区，并以过去偏好选b。Skill缺少较晚正向阶段；本题无自然Skill加载，不可把Skill缺陷直接归因到本题。'),
}
rows=[];sources={}
for path in [ROOT/'docs/evidence/personamem-native-v2-outcome-20261007.json',ROOT/'scripts/personamem_answer_diagnostics.py',*STUDY.glob('public/*.json'),*STUDY.glob('annotations/*.json'),*STUDY.glob('review-packs/*.json')]:
 sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
for user in report['officialReport']['users']:
 pid=user['personaId'];public=json.loads((STUDY/f'public/persona-{pid}.json').read_text());pack=json.loads((STUDY/f'review-packs/persona-{pid}.json').read_text());ann=json.loads((STUDY/f'annotations/persona-{pid}.json').read_text());arms={a['arm']:a for a in user['arms']};answers={a:json.loads((STUDY/f'persona-{pid}-{a}/state/pilot/persona-{pid}/answers.json').read_text()) for a in arms}
 for i,q in enumerate(public['questions']):
  qid=q['id'];entry={'personaId':pid,'questionOrdinal':i+1,'questionId':qid,'question':q['question'],'arms':{},'assetCausalAttribution':'UNKNOWN','learningInput':False}
  for arm in ['baseline','rsi']:
   a=answers[arm][i];score=arms[arm]['scores'][i];assert a['questionId']==qid==score['questionId'];text=a['response'];sha=hashlib.sha256(text.encode()).hexdigest();assert sha==score['responseSha256'];fmt=diagnose_answer_format(text);assert fmt==score['formatDiagnostic'];tail=text.rsplit('<final_answer>',1)[-1].strip();m=re.match(r'\(([a-d])\)|([a-d])\b',tail,re.I);assert m;choice=(m.group(1) or m.group(2)).lower();path=STUDY/f'persona-{pid}-{arm}/state/pilot/persona-{pid}/answers.json';entry['arms'][arm]={'officialCorrect':score['correct'],'outputChoiceDiagnostic':choice,'strictFormatDiagnostic':fmt,'responseSha256':sha,'evidence':str(path)+f'#/index/{i}/response'};sources[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
  b,r=entry['arms']['baseline'],entry['arms']['rsi'];entry['choicesDifferent']=b['outputChoiceDiagnostic']!=r['outputChoiceDiagnostic'];entry['officialPairClass']=('both_correct' if b['officialCorrect'] and r['officialCorrect'] else 'both_wrong' if not b['officialCorrect'] and not r['officialCorrect'] else 'baseline_only_correct' if b['officialCorrect'] else 'rsi_only_correct')
  category,evidence=notes.get((pid,i+1),('同选项；无可识别增量贡献','相同输出选项；官方正确性见逐题记录。完整历史共同存在，不能由同选项或正确性推断资产因果贡献。'));entry.update({'manualReview':{'reviewedBy':'gpt-6.1-sol assistant','category':category,'evidence':evidence,'causalAttribution':'UNKNOWN'},'diagnosticCategory':category,'reviewEvidence':evidence,'actualSkillBodyDeliveries':[x for x in pack['actualSkillBodyDeliveries'] if x['questionId']==qid],'savedObservedDecisions':[x for x in ann['observedDecisions'] if x['questionId']==qid],'reviewPackEvidence':str(STUDY/f'review-packs/persona-{pid}.json'),'annotationEvidence':str(STUDY/f'annotations/persona-{pid}.json')});rows.append(entry)
counts={'pairs':len(rows),'responses':len(rows)*2,'officialBaselineCorrect':sum(x['arms']['baseline']['officialCorrect'] for x in rows),'officialRsiCorrect':sum(x['arms']['rsi']['officialCorrect'] for x in rows),'differentChoices':sum(x['choicesDifferent'] for x in rows),'sameChoices':sum(not x['choicesDifferent'] for x in rows),'officialPairClasses':dict(collections.Counter(x['officialPairClass'] for x in rows)),'differentChoiceOfficialPairClasses':dict(collections.Counter(x['officialPairClass'] for x in rows if x['choicesDifferent'])),'strictFormatAnomalies':sum(not a['strictFormatDiagnostic']['valid'] for x in rows for a in x['arms'].values())}
assert counts['pairs']==32 and counts['differentChoices']==11 and counts['strictFormatAnomalies']==3
result={'scope':'OFFLINE_PREEXPOSED_DEVELOPMENT_AUDIT','realModelRequests':0,'officialScoresChanged':False,'answerKeyLearningInputsCreated':False,'counts':counts,'rows':rows,'inputFileSha256':sources,'manualReviewSummary':{'causalAttributionEstablished':0,'interpretationNotFactCount':True},'method':'Reuse personamem_answer_diagnostics; official report and hashes retained. Leading marked choice is descriptive offline diagnostic only, not rescoring.'}
with (OUT/'paired-audit.json').open('x') as f: f.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
md=['# dsh-rsi 32对回答离线审计','仅开发，不是blind。无模型/网络调用；未改原数据、评分或学习输入。事实计数来自保存官方结果；assistant审阅分类是解释，错误因果全部未知。',
'事实计数：32对/64回答；官方21/32与20/32。选项不同11对：基线独对3、RSI独对1、均错7；同选项21对。全体均对18、均错9、基线独对3、RSI独对2。严格格式异常3条。',
'输出选项规则：最后 `<final_answer>` 后首个括号或独立a-d，大小写忽略；仅离线描述，不重算成绩。公开协议未禁止解释，因此严格尾部单选失败不等于协议违约。',
f'源目录：[study]({STUDY})；以下B/R引用均为该目录相对路径，JSON数组索引0基。完整哈希、qid与原回答定位见 [paired-audit.json]({OUT/"paired-audit.json"})。',
'|用户/题|qid|官方B/R|选项B/R|严格B/R|不同|assistant审阅分类|', '|---|---|---|---|---|---|---|']
for x in rows:
 b,r=x['arms']['baseline'],x['arms']['rsi'];mark=lambda a:'合格' if a['strictFormatDiagnostic']['valid'] else '尾部多文本'
 md.append(f"|{x['personaId']}/{x['questionOrdinal']}|{x['questionId']}|{int(b['officialCorrect'])}/{int(r['officialCorrect'])}|{b['outputChoiceDiagnostic']}/{r['outputChoiceDiagnostic']}|{mark(b)}/{mark(r)}|{int(x['choicesDifferent'])}|{x['diagnosticCategory']}|")
md+=['','## 11对不同选项：assistant审阅解释（非因果结论）']
for x in rows:
 if x['choicesDifferent']:
  md +=[f"- 用户{x['personaId']} Q{x['questionOrdinal']}：{x['reviewEvidence']} Skill交付{len(x['actualSkillBodyDeliveries'])}次；源：persona-{x['personaId']}-{{baseline,rsi}}/state/pilot/persona-{x['personaId']}/answers.json，数组索引{x['questionOrdinal']-1}；annotations/persona-{x['personaId']}.json。"]
md+=['','## 三损失与最小开发诊断',f'深读实际交付/原历史0基索引见 [three-loss-focus.json](three-loss-focus.json)。用户9 Q3同时交付减杂乱事件与仍偏重收藏的global画像；先固定其余输入，仅修画像阶段或撤去该画像。错误因果仍未知，不能保证救回答案。用户12 Q1原资产保留ADR前后阶段，但真实案例诉求被概括，实际理由为a更详细/d更短，需单独诊断决策标准；Q4相关检出片段含负向桌游，不能据此认定所有交付遗漏正向场次。',
'其他最小控制：用户9 Q2解析异常；用户14 Q1代码Skill跨域加载但答对；用户15投资社区Skill阶段遗漏与Memory阶段保留。都仅开发，不宣称blind。',
'评分器最小建议：标记存在时仅解析明确选项，禁止任意正文单字母fallback；明确最后标记、leading choice、额外正文与歧义规则。虚拟标签控制及原异常响应回归，版本记录，新旧结果分开；本次不改实现。',
'标准答案隔离：本审计未读取评分标准答案，未生成含标准答案的学习输入；官方结果仅用于离线分类。审阅解释由gpt-6.1-sol assistant给出，并非人类人工标注。',
'特别边界：用户9 Q2同c却官方不同；用户9 Q4和14 Q3严格异常但官方对。用户12 Q2重复选项，用户17 Q2绘画题/阅读选项错配。事实正确、阶段忠实、适用性、消费与因果贡献分别判断。']
with (OUT/'paired-audit.md').open('x') as f: f.write('\n'.join(md)+'\n')
print(json.dumps(counts,ensure_ascii=False))
