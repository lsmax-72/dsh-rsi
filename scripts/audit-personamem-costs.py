#!/usr/bin/env python3
import json,pathlib,collections,hashlib,argparse
parser=argparse.ArgumentParser();parser.add_argument("--study-root",type=pathlib.Path,default=pathlib.Path(__file__).resolve().parent.parent/".artifacts/personamem-native-v2-replication-20261006");parser.add_argument("--output",type=pathlib.Path,required=True);args=parser.parse_args()
ROOT=args.study_root.resolve(); OUT=args.output.resolve(); OUT.mkdir(parents=True,exist_ok=True)
for name in ["audit.json","README.md"]:
 if (OUT/name).exists(): parser.error(f"Refusing to overwrite {OUT/name}")
input_hashes={}
def read(p):
 input_hashes[str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest();return json.loads(p.read_text())
def text(m):
 c=m.get('content','');return c if isinstance(c,str) else ''.join(b.get('text','') for b in c if isinstance(b,dict))
def stats(rows):
 for row in rows:
  u=row.get("usage") or {};assert all(isinstance(u.get(k),(int,float)) for k in ["inputTokens","outputTokens","totalTokens"]), "unknown usage: "+row.get("sessionId", "?");assert u["inputTokens"]+u["outputTokens"]==u["totalTokens"]
 return dict(calls=len(rows),input=sum(r['usage']['inputTokens'] for r in rows),output=sum(r['usage']['outputTokens'] for r in rows),total=sum(r['usage']['totalTokens'] for r in rows),unknown=sum(not r.get('usage',{}).get('totalTokens') for r in rows))
first_rows=[];followup_rows=[]
allrows=collections.defaultdict(list); tasks=collections.defaultdict(list);details=[];duplicate=[];normalized_duplicates=[];skill_system=[]
for run in sorted(ROOT.glob('persona-*-baseline'))+sorted(ROOT.glob('persona-*-rsi')):
 arm=run.name.rsplit('-',1)[1]; pid=run.name.split('-')[1]; p=run/'state/pilot'/f'persona-{pid}';rows=read(p/'model-requests.json');fg=[r for r in rows if r['phase']!='learning'];bg=[r for r in rows if r['phase']=='learning'];allrows[arm+'-foreground']+=fg;allrows[arm+'-background']+=bg
 if arm=='rsi':
  seen=set()
  for row in fg:
   if row['phase'] in seen:followup_rows.append(row)
   else:first_rows.append(row);seen.add(row['phase'])
 if bg:
  records={x['record']['sessionId']:x['record'] for x in read(p/'native-learning-runs.json')}
  for r in bg:
   task=records[r['sessionId']]['taskId']; task='skill-extract' if task.startswith('skill-extract-') else 'scene-extract' if task.startswith('scene-extract-') else task;tasks[task].append(r)
   if task=='skill-extract':skill_system.append(text(r['messages'][0]))
  by=collections.defaultdict(list)
  for r in bg:by[hashlib.sha256(json.dumps(r['messages'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()].append(r)
  norm=collections.defaultdict(list)
  for r in bg:norm[hashlib.sha256(json.dumps([(m.get("role"),m.get("content")) for m in r["messages"]],sort_keys=True,ensure_ascii=False).encode()).hexdigest()].append(r)
  normalized_duplicates += [dict(persona=pid,calls=len(v),sessions=len(set(r["sessionId"] for r in v)),tokens=sum(r["usage"]["totalTokens"] for r in v)) for v in norm.values() if len(v)>1]
  duplicate += [dict(persona=pid,calls=len(v),sessions=len(set(r['sessionId'] for r in v)),tokens=sum(r['usage']['totalTokens'] for r in v)) for v in by.values() if len(v)>1]
 # baseline first request establishes identical role/content historical prefix before time-note/question
 baseline=read(ROOT/f'persona-{pid}-baseline/state/pilot'/f'persona-{pid}'/'model-requests.json')[0]
 msgs=baseline['messages']; history=[]
 for m in msgs[1:]:
  if text(m).startswith('Original source message times'):break
  history.append((m['role'],text(m)))
 public=read(ROOT/"public"/f"persona-{pid}.json")["history"]
 public_checks=[]
 checks=[]
 for r in fg:
  actual=[(m['role'],text(m)) for m in r['messages']];joined='\n'.join(t for _,t in actual);missing=[i for i,m in enumerate(public) if m['content'] not in joined];public_checks.append(dict(sessionId=r['sessionId'],phase=r['phase'],prefixEndSeq=r.get('prefixEndSeq'),missingPublicHistoryIndices=missing)); checks.append(actual[1:1+len(history)]==history)
 details.append(dict(persona=pid,arm=arm,foreground=stats(fg),background=stats(bg),historyMessages=len(history),historyChars=sum(len(t) for _,t in history),allForegroundCarryIdenticalHistory=all(checks),checks=checks,publicHistoryChars=sum(len(m["content"]) for m in public),publicHistoryCount=len(public),allPublicHistoryContentPresent=all(not q["missingPublicHistoryIndices"] for q in public_checks),publicHistoryChecks=public_checks))
assert len(first_rows)==32 and len(details)==16, 'This audit requires the complete fixed eight-user cohort'
assert all(d['allPublicHistoryContentPresent'] for d in details), 'Historical source text missing'
s={k:stats(v) for k,v in allrows.items()}; n=32;b=s['baseline-foreground']['total']/n;f=s['rsi-foreground']['total']/n;B=s['rsi-background']['total'];addition='Write asset prose in ';host=[]
for st in skill_system:
 host.append(st[st.index(addition):] if addition in st else '')
r=dict(groups=s,nQuestionsPerArm=n,perQuestion=dict(baseline=b,rsiForeground=f,foregroundIncrement=f-b,backgroundAmortized=B/n,fullRsi=f+B/n),amortization=dict(totalBackground=B,formula=f'C_rsi(N)={B}+{f}*N; C_base(N)={b}*N; delta/N={f-b}+{B}/N',breakEvenPossibleAtCurrentMean=f<b),byNativeTask={k:stats(v) for k,v in tasks.items()},foregroundHistoryChecks=details,exactIdenticalBackgroundMessageDuplicates=duplicate,roleContentBackgroundMessageDuplicates=normalized_duplicates,skillSystemChars=dict(calls=len(skill_system),total=sum(map(len,skill_system)),hostSuffixTotal=sum(map(len,host)),hostSuffixMin=min(map(len,host)),hostSuffixMax=max(map(len,host))),limitations=['Only whole-request usage is exact; component character counts are not component token estimates.','Identical requests prove repeated payload, not unnecessary processing; different prompts may reuse source facts without being duplicate jobs.','Embedding usage is unreported and excluded; do not call it zero.','Token totals are not monetary costs; pricing and cached-token billing are not reconstructed.'])
r['rsiFirstRequestCost']=stats(first_rows)
r['rsiFollowupRequestCost']=stats(followup_rows)
r['inputSha256']=input_hashes
r['extraForegroundPublicHistoryChars']=sum((d['foreground']['calls']-4)*d['publicHistoryChars'] for d in details if d['arm']=='rsi')
r['extraForegroundHistoryChars']=sum((d['foreground']['calls']-4)*d['historyChars'] for d in details if d['arm']=='rsi')
(OUT/'audit.json').write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n');print(json.dumps({'groups':s,'rsiFirstRequestCost':r['rsiFirstRequestCost'],'rsiFollowupRequestCost':r['rsiFollowupRequestCost'],'inputFiles':len(input_hashes)},ensure_ascii=False))

report_lines=["# dsh-rsi 离线成本审计", "复现：python3 scripts/audit-personamem-costs.py --study-root <研究目录> --output <输出目录>", "", "|范围|调用|input|output|合计|", "|---|---:|---:|---:|---:|"]
for name,g in r["groups"].items():report_lines.append(f"|{name}|{g['calls']}|{g['input']}|{g['output']}|{g['total']}|")
report_lines += ["", f"每题前台增量 {f-b} token；{r['amortization']['formula']}。保持当前均值仅加题量不能持平。", f"54条dsh-rsi前台请求全部public历史content检查：{all(d['allPublicHistoryContentPresent'] for d in details if d['arm']=='rsi')}。含system背景content，但system背景在共享说明中投影，原role未保留。额外调用重复public历史 {r['extraForegroundPublicHistoryChars']} 字符。", f"后台原始messages重复组{len(duplicate)}；role/content规范化重复组{len(normalized_duplicates)}。这不等于作业重复或无效处理结论。", f"Skill宿主后缀重复{sum(map(len,host))}字符；不能拆成精确分项token。", "最值得验证是否能减少非必要前台工具往返；模型通常无状态，不能假设删除后续历史语义不变。压缩或替代上下文属于新实验条件；缓存账单折扣不减少本指标raw token。若只做后台最小改动，审查压缩宿主重复提示，保留来源、验证及长度约束。", "现成原生窗口headChars/tailChars默认8000/32000，src/local-core.ts:97-102已接入；缩窗会影响覆盖。原生pipeline有everyNConversations/idle/warmup及L2调度，未证明本轮发生可避免的重复触发。", f"每题首请求成本{r['rsiFirstRequestCost']}；后续22请求成本{r['rsiFollowupRequestCost']}。这些是实际加和，不代表删除调用可实现的节省。", "全部输入SHA256和逐请求缺失索引见audit.json。usage缺失或不一致会assert失败。", *r["limitations"]]
(OUT/"README.md").write_text("\n".join(report_lines),encoding="utf-8")
