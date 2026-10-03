# 实验预算与评分汇总准备

2026-10-03；不启动正式配对实验。本轮检查不新增模型调用。

## 1. 跨容器预算

`learning-budget.py` 维护宿主侧实验预算 SQLite，仅记录额度、预留与结算，不读取或实现记忆/技能资产。任务容器不挂载预算库，产品学习仍调用原有模型桥与提炼组件。

- 正式前序可使用一个固定上限 100 的共享池；后序每题使用独立上限 10 的池。该配置仍是待确认方案，当前只初始化上限 1 的检查池。
- 启动容器前原子预留本次额度，最多授予池中剩余额度。运行器在官方 llm/stream 调用路径上限制**本次新增**后台调用，不使用资产快照内历史 usage 当作本题成本。
- 并发预留不能超额，重开库或跨日不会重置额度。预算上限不可被再次初始化改大。进程丢失时，预留仍占用额度，不自动退款。
- 容器停止、日志导出且请求账本与网关对齐后，按实际观测后台调用结算，释放未用额度。缺少日志、导出失败、计数不一致时保留全额预留，停止后核查；未知 token 不等于没有消耗调用额度。
- 网关总调用上限不高于前台上限 + 实际授予后台额度。任务尝试绕过官方路径导致网关/账本不一致时，不能继续作为有效实验结果。

两个断网容器沿用真实官方 Agent、原生默认捕获与学习，仅模型为固定响应。第一个获额度 1，实际后台 1 次；第二个获额度 0，前台仍正常执行 2 次，后台 0 次。第一个原生任务显示暂停；第二个记忆提炼包装丢失预算错误码后显示失败，`blocked-dispatches.json` 明确保留“实验额度耗尽”原因，不能将它报告成模型质量失败。见 [共享池证据](evidence/shared-learning-pool-20261003.json)。

额外离线控制验证并发预留、孤儿预留保留、核验退款、上限不可重置与不可超额结算。见 [统计控制](evidence/measurement-controls-20261003.json)。固定响应 usage 是模拟数据，不计真实 token。

## 2. 官方评分入口

`score-prediction.py` 对一个已保存补丁调用固定官方 SWE-bench 3.0.0。发行源码哈希验证、容器资源/断网配置复用 `probe-scorer.py`；未修改测试生成、日志解析或评分算法。只接受已缓存评分镜像，缺少镜像时退出，不自动下载正式题目镜像。

评分输出包含补丁 SHA256、官方原始报告、resolved 与测试日志哈希。空预测和明确的补丁应用失败沿用官方报告函数；其他无报告情况保留为未分类，不能一律算 INFRA 或任务失败。评分目录含评测专用材料，始终留在评分侧，不复制到 Agent 任务镜像。

对已有真实补丁 `django__django-11292` 通过新入口复验，官方判分仍为 `resolved=true`，FAIL_TO_PASS 与 PASS_TO_PASS 均通过。本次仅新增 1 次已缓存镜像的评分执行，真实模型调用为 0，不是新增正式样本。见 [评分入口证据](evidence/score-entry-20261003.json)。

## 3. 离线汇总

`summarize-paired.py` 只读取固定题单、运行清单、逐请求 usage 与保存的官方报告，不启动容器、评分器或模型。

- 验证题目 ID、评分报告及补丁哈希一致；预算终止不会覆盖官方 resolved。
- 同题两组报告新增解决、新增失败、配对表与差异区间。区间采用固定 seed 的成对任务 bootstrap，只表示任务重采样差异，不代表同题重复模型运行的不确定性。
- 前序/后序、前台/后台分别统计，全链路包含全部重试。只有确认且尚未判分的 INFRA 才可重试 1 次，失败任务不能借重试筛掉。
- 缺失判分保留固定分母并给成功率上下界，不自动算失败、换题或删除样本。配对不完整时不给完整净差。
- 未返回 usage 或整个日志缺失时，精确总 token 为 null，另列已知部分和缺失覆盖。缓存/推理细分不重复计入 total。均值、中位数与每个成功结果成本也不静默丢掉未知值。
- 保留每题前台 token 差、固定 N 的学习摊销、全链路 token 增量；完整性不足时不推算节省比例。

已有真实成功案例的旧失败回执没有最终 receipt，请求保存在 failure.json；新工具能正确读取，并保留官方成功与预算终止：前台 508737、后台 59745 token，未追加模型请求或改写原始材料。见 [真实保存结果审计](evidence/saved-score-audit-20261003.json)。该单例不是正式配对效果结果。

## 4. 使用入口

以下是工具用法；当前不运行正式任务：

```bash
python3 -B scripts/learning-budget.py /tmp/rsi-prefix-budget.sqlite --init 100
# 单次隔离运行另传 --learning-pool、--learning-dispatch-limit 和已经核验的 --baseline-date。
# 正式后序每题应使用独立上限 10 的池，不能共享前序池或后序资产副本。

python scripts/score-prediction.py --dataset DATASET_PARQUET --instance INSTANCE_ID --prediction PREDICTION_PATCH --work-dir GRADER_ONLY_DIR --output GRADE_JSON
python3 -B scripts/summarize-paired.py --manifest MANIFEST_JSON --runs RUNS_JSON --output NEW_SUMMARY_JSON
```

评分命令必须在已校验的 SWE-bench 3.0.0 Python 环境运行。运行清单使用绝对路径，记录 instanceId、stage（prefix/heldOut）、arm（baseline/rsi）、attempt（0/1）、runDir、grading 和 classification。尚未判分或确认基础设施故障时 grading 为 null；不得把未经判定的无报告错误写成 INFRA 来自动重试。

## 5. 正式启动边界

预算控制、单补丁评分入口与离线汇总已准备；正式题单、规模、预算和重试方案仍待确认。确认后才准备每题评分/任务镜像并冻结版本与资产来源快照；当前没有运行任何正式配对样本。
