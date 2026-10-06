# PersonaMem 后台失败与前台答题的预先规则

## 本次解决的问题
当前关闭轮最后一位用户在 Skill 更新超时后没有进入答题，原协议因此不能报告完整八用户准确率。修改方向是让下一轮测量有限预算内实际可用的完整插件：后台学习失败是一个单独结果；已有历史和资产仍能被前台使用时，前台答题质量可以测量。它不会使学习失败变成学习成功。

只修改评测运行器、冻结与离线报告，不修改原生提炼、检索、Skill 工具、版本或生产算法。旧轮继续缺失，不恢复旧轮、不回填答案，也不删旧费用。

## 两种冻结策略
- `require-complete`：默认及全部旧冻结使用。原生学习不结束就停止，不给缺失答案记零分。
- `evaluate-closed-bounded-failure`：只允许新方案在首次派发前明确选择。原生 L0 捕获完整、没有活跃调用或待处理队列、实际学习账本全部闭合后，作业为 `failed`/`paused` 且失败码仅为 `ABORTED` 或带实际拦截记录的 `BUDGET_EXHAUSTED` 时，可冻结已有资产进入答题。

`ABORTED` 表示已闭合的操作中断；此规则本身不能证明中断根因或保证都是时限耗尽。未知错误、明确的基础设施错误、还在运行、未完整捕获或关闭产生的 `interrupted` 均停止。仅有待触发画像、没有已记录失败作业的状态也不会被此规则放行。不得通过扩充次数/时间、救援提炼、人工编辑资产或给模型答案来恢复失败。

答题前关闭学习；原题历史、共同时间来源说明及截止点在两组保持。答题后除作业来源和 L0-L3 数量，还对比 Memory 正文及历史版本、Skill 正文/版本/资源、画像文件完整导出内容。答案不得变成学习输入。

## 报告怎么计算
已测到的每题输出仍按原官方提取方法评分，包括正常协议保存的中断输出；完全缺失的答案不补零。完整八用户配对都结束才能出全组估计，按用户做成对 bootstrap。单列 `completedLearners` 和 `closedBoundedFailedLearners`，保留实际前台/后台 token 与未知 usage，失败学习费用计入总成本。

新 receipt 声明实际策略、失败作业及 `learning.json` SHA256；离线报告检查冻结策略、失败来源、实际闭合账本和内容哈希。默认策略不得接受事后改成宽松规则的 receipt。

已接触用户的复验使用 `preexposed-development-replication`、`FROZEN_PERSONAMEM_REPLICATION`、`independenceClaim:false` 和 `COMPLETE_PREEXPOSED_SAVED_RESULTS`。复验用于开发比较，不充当独立盲测或全数据集结论。

## 验证证据
1. [14 项决定门控制](evidence/personamem-learning-failure-gate-controls-20261006.json)：读取原最后用户失败快照，默认仍拒绝；新策略接受已闭合中断，拒绝运行中、缺 L0、队列待处理、基础设施错误、关闭中断、未闭合账本及无拦截记录的预算失败。
2. [13 项实际离线报告控制](evidence/personamem-learning-failure-report-controls-20261006.json)：旧七项保持；新预登记策略同时记录可评分答案和失败学习，策略错配/内容变动/错误独立标签均拒绝。
3. [11 项观察器控制](evidence/personamem-learning-failure-observer-controls-20261006.json)：保留中断正文、异常 finish、无效/未知 usage，不把零 usage 算免费。
4. [Docker 原生路径控制](evidence/personamem-learning-failure-runtime-control-20261006.json)：显式模型夹具通过安装版默认捕获、原生 Memory/Skill 写入、模型桥与失败落盘。保存 1 条 Memory 和 1 个 Skill 后模拟 `ABORTED`，学习仍为失败，两个前台问题完成；资产内容、版本及资源在答题前后不变，5 次夹具输入均能从持久日志重建。
5. 同一回执包含旧轮只读镜像报告：77 份原文件哈希保持，原 5,288,793 已知聊天 token/1 未知、18/28 与 16/28 不变；完整八用户估计仍为空。

新增真实模型调用 **0**；夹具的 80 已知 usage token/1 未知是模拟值，不能加入真实成本。没有运行官方判分或证明真实内容质量/效果提升。

## 保留的夹具失败
首次 `/private/tmp/dsh-rsi-persona-closed-failure-runtime-20261006` 直接抛错被宿主变成 `UNKNOWN`，规则正确拒绝，前台 0 次；保存原失败目录。随后在独立 `...runtime-b-20261006` 用明确 finish failure 事件模拟 `ABORTED` 后通过。不是把真实未知错误重分类，也不是重跑旧正式轮。

## 下一步
固定下一轮方案、用户和成本上限，再冻结清洁提交。原八用户题单已用于开发诊断，不能再称盲测；32k 版本只剩三位未试跑身份，完整八用户比较必须披露复验性质。真实日期单批检查与资源更新已有局部成功，但场景主语、偏好依据、自然 Skill 相关性和总成本仍是已知限制，不能靠完整交付率替代质量结论。
