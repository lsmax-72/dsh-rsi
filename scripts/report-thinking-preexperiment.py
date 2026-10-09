#!/usr/bin/env python3
"""Detached final analysis of this frozen development batch. Never dispatch tasks."""
import argparse,hashlib,json,os,statistics,subprocess,sys,time
from pathlib import Path
IDS=['django__django-'+n for n in ['11848','11551','12262','11815','11880','11790','11999','11740']]
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n');os.replace(t,p)
def cost_choice(totals):
 # Missing usage gives [known total, infinity). Only disjoint intervals
 # establish a cheaper mode; overlapping lower bounds cannot decide a tie.
 a,b=totals['off'],totals['on']
 if a['costComplete'] and b['costComplete']:
  return min(['off','on'],key=lambda m:(totals[m]['totalTokens'],totals[m]['agentWallSeconds']))
 if a['costComplete'] and a['totalTokens']<b['totalTokens']:return 'off'
 if b['costComplete'] and b['totalTokens']<a['totalTokens']:return 'on'
 return None
def analyze(root):
 state=read(root/'state.json');summary=read(root/'summary.json') if (root/'summary.json').exists() else {};protocol=read(root/'protocol.json');rows=[read(p) for p in root.glob('*.record.json')];errors=[]
 def check(v,m):
  if not v:errors.append(m)
 check(sha(root/'protocol.json')==(root/'protocol.sha256').read_text().strip(),'Frozen protocol hash mismatch')
 check(state.get('status')=='COMPLETE' and summary.get('status')=='COMPLETE','Batch did not complete all eight pairs')
 check(len(rows)==16 and {(r['instanceId'],r['thinking']) for r in rows}=={(i,m) for i in IDS for m in ['on','off']},'Unexpected or missing task/mode records')
 pairs=[];by={(r['instanceId'],r['thinking']):r for r in rows};gaps=[]
 for r in rows:
  tag=r['instanceId']+'/'+r['thinking'];out=Path(r['output']);pilot=out/'state/pilot'/r['instanceId']
  check(r['status']=='CLOSED_GRADED' and type(r.get('resolved')) is bool,tag+': not a valid closed score')
  if r['status']!='CLOSED_GRADED':continue
  check(r.get('modelErrors')==0,tag+': model error')
  check(r.get('calls',41)<=40 and r.get('agentWallSeconds',0)<=1205,tag+': budget exceeded')
  evidence=r.get('serviceThinkingEvidence') or {};expected=r['thinking']=='on'
  check(evidence.get('requests')==r['calls'],tag+': wire/native call count differs')
  check((evidence.get('reasoningChars',0)>0)==expected and (evidence.get('nativeReasoningChars',0)>0)==expected,tag+': actual Thinking evidence mismatch')
  check(sum(u['total_tokens'] for u in r.get('rawServiceUsage',[]) if u)==r.get('totalTokens'),tag+': raw service and native total tokens differ')
  grade=read(Path(r['grading']));check(grade['resolved']==r['resolved'] and grade['patchSha256']==sha(pilot/'prediction.patch') and grade['verifiedSourceFiles']==50 and grade['modelRequests']==0,tag+': official score or prediction mismatch')
  receipt=read(pilot/'receipt.json');initial=read(pilot/'initial.json');recon=read(pilot/'reconstruction.json')
  check(receipt['arm']=='baseline' and receipt['backgroundDispatches']==0 and initial['assets'] is None and len(recon)==r['calls'] and all(q['matches'] is True for q in recon),tag+': isolation/reconstruction failed')
  wire=[json.loads(l) for l in (out/'gateway.log').read_text().splitlines() if l.strip()];sent=[w for w in wire if w.get('request') and w.get('model')];responses=[w for w in wire if 'responseRequest' in w]
  check(len(sent)==len(responses)==r['calls'] and all(w['enableThinking'] is expected for w in sent),tag+': actual toggle/count mismatch')
  abort_ids=set(evidence.get('budgetAbortedRequestIds',[]))
  check(all(w['parseErrors']==0 and ((w['responseComplete'] and w['sseDone'] and w['error'] is None) or (r['timedOut'] and w['responseRequest'] in abort_ids and w['responseRequest']==r['calls'] and w['error']=='CLIENT_DISCONNECTED')) for w in responses),tag+': response is neither complete nor verified wall-budget cancellation')
  if r.get('auditRepair'):
   check(r['instanceId']==IDS[0] and r['thinking']=='on' and r['auditRepair']['rawWireBytesAvailable'] is False,tag+': unexpected raw-byte exception')
   gaps.append(tag)
  else:
   for w in responses:
    for field,path in [('requestSha256','rawRequest'),('responseSha256','rawResponse')]:
     f=out/'gateway-evidence'/w[path];check(f.is_file() and sha(f)==w[field],tag+': original byte hash mismatch')
 for id in IDS:
  a,b=by.get((id,'off')),by.get((id,'on'));valid=bool(a and b and a['status']=='CLOSED_GRADED' and b['status']=='CLOSED_GRADED')
  if valid:check(a.get('firstRequest')==b.get('firstRequest') and bool(a.get('firstRequest')),id+': initial prompt/tools/cap differ')
  pairs.append({'instanceId':id,'off':a,'on':b,'valid':valid,'onMinusOff':int(b['resolved'])-int(a['resolved']) if valid else None})
 totals={}
 for mode in ['off','on']:
  group=[r for r in rows if r['thinking']==mode and r['status'] in ['CLOSED_GRADED','CLOSED_INFRA']];graded=[r for r in group if r['status']=='CLOSED_GRADED']
  totals[mode]={'attempted':len(group),'caseFailures':len(group)-len(graded),'graded':len(graded),'solved':sum(r['resolved'] for r in graded),'passRate':sum(r['resolved'] for r in graded)/8 if len(graded)==8 else None,'unknownUsageRequests':sum(r.get('unknownUsageRequests',0) for r in group),'costComplete':bool(group) and all(r.get('costComplete',r.get('unknownUsageRequests',0)==0 and r['status']=='CLOSED_GRADED') for r in group),'calls':sum(r.get('calls',0) for r in group),'inputTokens':sum(r.get('inputTokens',0) for r in group),'outputTokens':sum(r.get('outputTokens',0) for r in group),'totalTokens':sum(r.get('totalTokens',0) for r in group),'agentWallSeconds':sum(r.get('agentWallSeconds',0) for r in group),'endToEndSeconds':sum(r['finishedAt']-r['startedAt'] for r in group),'thinkingTokens':sum(r['thinkingTokens'] for r in group) if group and all(r.get('thinkingTokens') is not None for r in group) else None,'timeouts':sum(r.get('timedOut',False) for r in group),'toolErrors':sum(r.get('toolErrors',0) for r in group),'modelErrors':sum(r.get('modelErrors',0) for r in group),'outputTruncations':sum(r.get('outputTruncations',0) for r in group),'callCapReached':sum(r.get('calls')==40 for r in group),'medianAgentSeconds':statistics.median(r.get('agentWallSeconds',0) for r in group) if group else None}

 paired={'bothPassed':sum(p['valid'] and p['off']['resolved'] and p['on']['resolved'] for p in pairs),'bothFailed':sum(p['valid'] and not p['off']['resolved'] and not p['on']['resolved'] for p in pairs),'onOnly':sum(p['valid'] and p['onMinusOff']==1 for p in pairs),'offOnly':sum(p['valid'] and p['onMinusOff']==-1 for p in pairs)}
 recommendation=None;reason='证据或配对不完整，不能决定配置。';ratio=None;ratio_lower=None;net=None
 if not errors:
  a,b=totals['off'],totals['on'];net=b['solved']-a['solved'];ratio=b['totalTokens']/a['totalTokens'] if a['totalTokens'] and a['costComplete'] and b['costComplete'] else None
  ratio_lower=b['totalTokens']/a['totalTokens'] if a['totalTokens'] and a['costComplete'] else None
  if net>0:recommendation='on';reason='本轮开发题 Thinking On 官方通过题数更多；以任务通过率为主，成本和耗时另外披露。'
  elif net<0:recommendation='off';reason='本轮开发题 Thinking Off 官方通过题数更多；以任务通过率为主，成本和耗时另外披露。'
  else:
   recommendation=cost_choice(totals)
   if a['costComplete'] and b['costComplete']:reason='本轮官方通过题数相同，按预先声明规则优先较低实际总 Token，若相同再比较耗时。'
   elif recommendation:reason='本轮官方通过题数相同，'+recommendation.upper()+'的完整实际总Token严格低于另一组已知下界，成本排序确定；缺失用量仍保留，不报告精确成本倍率。'
   else:reason='官方通过题数相同，成本区间存在重叠，未知用量使Token排序无法确定。'
 result={'status':('COMPLETE_DEVELOPMENT_CONFIG_RECOMMENDATION' if recommendation else 'COMPLETE_NO_MODE_SELECTED') if not errors else ('COMPLETE_WITH_UNUSABLE_CASES' if state.get('status')=='COMPLETE' else 'INCOMPLETE_OR_AUDIT_FAILED'),'recommendationThinking':recommendation,'reason':reason,'totals':totals,'paired':paired,'netSolvedOnMinusOff':net,'onToOffTokenRatio':ratio,'onToOffTokenRatioLowerBound':ratio_lower,'rawWireEvidenceGaps':gaps,'errors':errors,'confidenceInterval':None,'formal100Started':False,'formalThinkingConfirmed':False,'formalBudgetConfirmed':False,'completedPlannedRuns':sum(r['status'] in ['CLOSED_GRADED','CLOSED_INFRA'] for r in rows),'costComplete':all(v['costComplete'] for v in totals.values()),'sourceRevision':protocol['revision'],'recordSha256':{p.name:sha(p) for p in root.glob('*.record.json')},'limitation':'8 previously exposed development tasks; single stochastic run per mode. No stable improvement, RSI effect, or statistical significance claim. First On run has disclosed original-wire-byte archive gap.'}
 write(root/'decision.json',result)
 md=['# Thinking 配置预实验结果','',f"状态：{result['status']}。已记录{result['completedPlannedRuns']}/16个计划项。",'',('建议：**Thinking '+str(recommendation).upper()+'**。'+reason if recommendation else reason),'','本轮仅比较 Baseline，无 RSI、学习或跨题历史。固定8道已曝光开发题，每题每模式40次调用/1200秒/输出8192，串行执行并交替On/Off先后。没有启动正式100题，也没有确认正式Thinking或预算。','','## 同题配对','','| 任务 | Off官方 | On官方 | Off调用 | On调用 | Off总Token | On总Token | Off耗时秒 | On耗时秒 |','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
 for p in pairs:
  def values(r):return ['未运行','—','—','—'] if not r else (['异常；诊断评分'+('通过' if r.get('resolved') is True else '失败' if r.get('resolved') is False else '缺失'),str(r.get('calls','未知')),'已知 '+str(r.get('totalTokens',0)),str(r.get('agentWallSeconds','未知'))] if r['status']!='CLOSED_GRADED' else ['通过' if r['resolved'] else '失败',str(r['calls']),('≥' if r.get('unknownUsageRequests',0) else '')+f"{r['totalTokens']:,}",f"{r['agentWallSeconds']:.1f}"])
  a,b=values(p['off']),values(p['on']);md.append('| '+p['instanceId']+' | '+' | '.join([a[0],b[0],a[1],b[1],a[2],b[2],a[3],b[3]])+' |')
 md+=['','## 汇总','','| 指标 | Off | On |','|---|---:|---:|']
 for label,key in [('已记录计划项','attempted'),('单题异常','caseFailures'),('官方通过题数','solved'),('已判分题数','graded'),('已知输入Token（缺失时为下界）','inputTokens'),('已知输出Token（缺失时为下界）','outputTokens'),('已知总Token（缺失时为下界）','totalTokens'),('用量缺失调用数','unknownUsageRequests'),('前台调用','calls'),('Agent总耗时秒','agentWallSeconds'),('准备与评分在内总耗时秒','endToEndSeconds'),('超时','timeouts'),('模型错误','modelErrors'),('工具错误','toolErrors'),('输出截断','outputTruncations'),('用满40次调用题数','callCapReached')]:md.append('| '+label+' | '+str(totals['off'][key])+' | '+str(totals['on'][key])+' |')
 md+=['',f"配对：On独胜{paired['onOnly']}题，Off独胜{paired['offOnly']}题，共同通过{paired['bothPassed']}题，共同失败{paired['bothFailed']}题。",f"完整配对净差（On−Off）：{net}；完整实际总Token倍率（On/Off）：{ratio}；已知倍率下界（仅Off成本完整时可计算）：{ratio_lower}。",'', '## 证据与边界','', '实际模型请求的enable_thinking和服务原生reasoning/DSH记录逐项核验；首条Prompt/工具/输出上限相同。官方评分独立执行，补丁与判分保留，答案、隐藏测试及分数不回流。', '', '正常预算到时保留官方评分、超时与已知成本。被取消的最后一次模型调用如无usage，标为未知，已知Token是下界；不补零、不估算完整成本，也不重跑整题。单题基础设施异常单列，不伪装为官方失败。', '', '服务未单列reasoning_tokens时Thinking Token标为未提供；不能用字符数估算Token，也不能把推理Token再次加到total。模型响应未提供权重hash或system_fingerprint，固定已配置部署身份，不能宣称独立验证了权重版本。', '', '首题11848 On的原始请求/响应字节因Docker tmpfs导出缺陷丢失；17个请求与完整服务响应的日志、原生推理/usage、日志重建和官方判分已审计。未重跑或删除该例，原HALTED证据保留，严格原字节hash审计未通过。其余例逐一核验原字节hash。', '', '这是8题开发配置预实验，每模式只运行一次；不做稳定收益、显著性或RSI效果结论。推荐依据为官方通过数，平局再按已声明的Token/耗时规则。正式100题仍需用户确认Thinking及预算，并实现验证连续Runner后另行冻结。', '', '完整逐题输入/输出Token、异常、补丁与官方判分路径在各record.json；summary.json与decision.json保存机器可读汇总。']
 if errors:md+=['','## 未解决问题','']+['- '+e for e in errors]
 (root/'report.md').write_text('\n'.join(md)+'\n');return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--wait',action='store_true');a=p.parse_args();root=a.output.resolve()
 if a.wait:
  while True:
   state=read(root/'state.json') if (root/'state.json').exists() else {}
   if state.get('status') in ['COMPLETE','HALTED','STOPPED']:break
   background=read(root/'background.json') if (root/'background.json').exists() else {}
   try:os.kill(background.get('pid',-1),0)
   except (ProcessLookupError,PermissionError):break
   time.sleep(30)
 result=analyze(root);print(json.dumps({k:result[k] for k in ['status','recommendationThinking','paired','netSolvedOnMinusOff','onToOffTokenRatio','errors']},ensure_ascii=False));return 0 if result['recommendationThinking'] else 1
if __name__=='__main__':sys.exit(main())
