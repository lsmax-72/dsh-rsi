# 通用与工作区资产：范围生命周期诊断

2026-10-07。继[逐题与成本复盘](personamem-offline-audit-20261007.md)后发现一项具体宿主适配缺口：提炼结果被分类为persona并迁往通用范围后，原工作区的后续原生冲突检测看不到该旧条目。原生算法仍被调用，但跨范围的候选与更新链并不完整。此项重新列为待处理，不能把此前七项装配局部验收扩大解释为完整生命周期已验收。

## 源码与运行证据

- `src/runtime.ts:221`：workspace提炼后将persona条目经global.storeMemory写入通用范围，并删除workspace的L1头。
- `src/local-core.ts:33`、`:143`：每个物理目录持有独立VectorStore；原生extractL1Memories只收到当前memory。
- `vendor/core/src/core/record/l1-dedup.ts:107`：向量/FTS冲突候选只从传入vectorStore查询，没有自动跨范围查询。
- `src/local-core.ts:157`：storeMemory使用原生writeMemory的store决策，未另做跨范围冲突检测。通用场景提取也只读取自己的记忆集合。

因此后续workspace episodic事件不会自动成为global冲突候选或global场景输入。这说明旧偏好可能缺少后续修订依据，但不是说所有跨范围记忆都语义冲突。

[原运行断言与哈希](evidence/personamem-offline-audit-20261007/saved-scope-separation.json)：用户9的global条目保留“开始收藏老电影海报”，workspace条目记录后期“出售海报缓解杂乱”。保存的第26条请求（0基索引25）是卖出新条目的冲突请求，包含新条目ID却没有该global旧ID。最终通用画像仍包含“怀旧收藏者”。卖出部分海报不等于完全不喜欢收藏；事实阶段的缺失与错误答案的因果关系仍未验证。

[零模型夹具回执](evidence/personamem-offline-audit-20261007/scope-visibility.json)使用真实openLocalCore、原生提炼/存储/删除/冲突调用及确定性embedding：先生成合成persona，按宿主相同API迁往global，再提炼后续episodic。迁移后的旧ID对workspace冲突不可见；把旧条目保留在同workspace的阳性对照中则可见。未知runner任务直接拒绝，没有qwen调用。

这个夹具证明范围可见性差异，不证明真实模型会合并、会正确更新偏好，也没有执行完整宿主scheduler；其status为PASS是“诊断复现成功”，不是“产品问题修复成功”。原资产、冻结代码和分数均未改动。

## 推进顺序与修复验收

先验证并补齐范围生命周期，再决定是否运行人工修复画像的诊断。此前建议优先修画像正文，是根据可见内容异常；此次增加了源码、原请求与阳性对照证据，优先级据此调整，不以追求正分数换题。

最小适配必须仍把候选判断、冲突决策、写入和版本管理交给原生能力。不能只给prompt追加旧偏好，也不能把另一范围ID交给当前物理库的writer后假设删除/更新已经跨库生效。验收需要覆盖：

1. 当前工作区的新信息能与相关通用旧偏好参与原生冲突检查；其他工作区专属条目保持隔离。
2. 原生决策所指的实际头、向量、历史版本与来源在正确范围更新，类型/范围变化有一致处理；不可留下仍可召回的旧通用副本。
3. 变更后的场景/画像失效与原生重建一致，召回和profile_read不能继续提供未标记的旧概括；明确更新传播的额度与失败状态。
4. 相同内容重放、无语义冲突、失败重试、恢复均保留原生语义；新增调用和token必须计入成本。先固定响应夹具，再真实小样本，不能把夹具当效果成绩。

仅保留workspace副本而不同步global，或者把全部workspace记录复制到global，都不能直接视为修复完成。实现选择仍需针对原生读写接口完成最小设计；本次没有修改生产后端。

## 后续冻结资产诊断的现有缺口

`scripts/probe-runner.py:133`拒绝PersonaMem与seed-assets组合，`personamem-pilot-task.mjs`的正常路径会重新导入并学习。已有coding/recovery隔离复制和资产/源会话哈希检查可复用，不能直接删除校验后把它当已支持的冻结消费模式。

`editMemory`会标记profile-invalid，使自动召回排除画像。因此原资产与修复资产的直接比较会混入画像失效、版本/索引和排序变化；需要原资产、同文原生编辑、按来源修复的独立副本对照，记录每次实际消费。画像当前没有公开管理编辑RPC，手工改文件仅是诊断干预，不能称为正常用户编辑或自动学习结果。没有通过来源、写入、消费与无意变化检查前，不扩大真实答题。

## 复现

```sh
node scripts/probe-native-scope-visibility.mjs --project "$PWD" --output /tmp/rsi-scope-visibility-new.json
```

输出文件必须不存在。夹具保留其创建的临时数据库和完整冲突prompt供复核。只新增离线诊断证据，尚未建立答题因果或质量改进结论。
