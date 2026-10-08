# SWE-bench 扩样协议（2026-10-08）

当前为环境准备方案，尚未冻结正式研究、尚未启动模型任务。固定公开题单见 `docs/evidence/swe-expansion-spec-20261008.json`；环境准备完成仅表示 READY。正式执行前审阅评分环境、104 个公开源码环境、运行控制器、版本与输入冻结回执。

## 问题与范围

比较当前版本完整 RSI 与原始 dsh，在固定四题前序形成的资产和历史条件下，对100道新 Django 任务的配对修复效果。共4个前序和100个评估任务、两组208次执行；所选版本为3.0–4.0。排除已曝光的34个任务，仅按公开元数据排序取题，无成绩筛选。数据路径、SHA256、排除清单及选择规则均固定在 spec；可通过 `scripts/prepare-swe-expansion.py` 重建。

两组分别顺序执行相同四题前序，各保留自身前序原始日志；RSI组另保留自然生成的原生资产。每个后序任务独立复制本组固定的前序快照，后序学习不传递到其他后序任务。这100题不是连续学习序列；收益属于完整插件的整体对照，不能拆称 Memory 或 Skill 单组件的因果贡献，也不能外推到所有 SWE-bench 仓库。

## 预算与停止

仅使用既有 `qwen3.8-27b`，thinking off。前台每题每组最多40次调用、1200秒；RSI前序后台共享100次调用，后序每题后台最多10次。前序等待180秒，最后一题360秒，后序180秒。计划受限两路并行；各组前序保持顺序。固定执行100个评估配对，不因显著性或成功率提前结束。无自动重试、无自动换题；基础设施、未知 usage 或冻结输入错误时停止新派发，保留已运行及在途证据并审阅。

120M–160M聊天token仅按旧运行估计，既不是保证也不是费用报价或token硬上限；统计前台、后台、失败尝试、已知输入/输出token和未知usage。嵌入token不可得时明确标记。判分只消费保存的预测补丁，在独立官方评分容器执行，不向任务或学习回流评分与隐藏数据。

## 分析

主指标为官方 resolved、100题配对净差及按任务配对 bootstrap 的95%区间。区间条件于这四道前序、冻结代码、模型与单次随机运行，不包含前序选择和重复模型运行的不确定性。近零净差时，假定配对不一致率为20%/40%，粗略95%半宽约8.8/12.4个百分点；这只是精度示例，不能称为检出小收益的功效保证。

次指标包括全链路成本、每解决一题token、停止原因、实际 Memory/Skill 正文消费的来源与版本证据；预先固定诊断样本中的相关性、长度、首次有判分支持的保存修改和重复检查。资产不必每题加载，不强制消费无关资产。旧24题、连续8题及开发结果只作为背景，不混入新100题分数。

## 独立环境准备

干净评分环境 `.artifacts/swe-scorer-venv/bin/python` 使用 `swebench==3.0.0`，50个官方源码发行哈希一致。新增正式题的空补丁负控制与既有公开任务的正/负控制健康检查正在后台进行，尚不宣称通过。后台脚本只逐题调用既有 `prepare-task-image.py`，先前序后后序，不启动真实模型；固定spec、dataset和准备脚本哈希，记录HEAD、逐例日志、环境与公开输入哈希。宿主可用空间不足15GiB时保守停止；不自动删除镜像。已有不完整环境目录要求人工审阅，不自动重试。STOP文件在当前准备任务结束后阻止下一题。

```sh
python3 scripts/prepare-swe-environments.py start \
  --spec docs/evidence/swe-expansion-spec-20261008.json \
  --dataset /Users/lsmax/Coder/EvoAgentBench/data/swebench/data/test-00000-of-00001.parquet \
  --python .artifacts/swe-scorer-venv/bin/python \
  --output .artifacts/swe-expansion-environments-20261008
python3 scripts/prepare-swe-environments.py status --output .artifacts/swe-expansion-environments-20261008
```

`start` 创建独立会话后台进程，无需Codex在线；`run --output ...` 用于STOP/磁盘停止后的人工恢复，必须保持输入不变、已完成回执一致且不存在未完成题目录。出现HALTED先审阅，不把准备错误算为模型任务失败。全部104环境完成后标记READY，正式研究冻结与模型执行仍是后续步骤。
