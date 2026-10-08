# 切换模型后的执行计划

用户已切换并要求提供独立启动入口，自己启动。环境准备已STOPPED，已完成2/104；本轮真实模型调用0次。交付时保持STOP，由用户运行入口后显式恢复。原恢复步骤保留为背景，当前按一键入口文档执行。

## 已完成

- 清理确认过的128处 npm 下载缓存，释放49.77GiB，保留任务日志、资产和评分证据；新导出不再复制下载缓存。
- 4道前序 + 100道独立后序配对的公开题单、两路后台控制器和环境准备脚本已提交。运行控制器15项离线检查通过；环境控制器104题模拟及停止/恢复检查通过。
- 干净官方 swebench 3.0.0 评分环境：50个官方文件哈希完整；2题正负对照共4项实际通过。不得使用旧的改过parser的环境。
- 首次镜像准备被Python3.6默认ASCII编码阻断，旧目录保留；明确UTF-8修复后v2首题9296已成功，随后开始11141。
- 本地最新提交8759b7f（以及此前缓存/协议/控制器等提交）尚未推送。按lsmax身份继续。

## 恢复顺序

1. 查看git状态、v2准备状态和磁盘。读取协议与评分控制文档，确认当前任务是否完成，不能启动两个准备进程。旧失败目录不覆盖、不自动重试。
2. 用户说继续后，若准备已停止且无未完成题目录，移除v2的STOP，后台启动已有脚本 `run` 恢复；已完成项校验哈希并跳过。如当前仍在途，等待其结束再恢复。低于15GiB停止并汇报，不自行清理共享Docker缓存。
3. 把已验证提交推到origin/main。全部104个环境READY后，核对代码/依赖/公开源码/模型/预算/评分与输入隔离证据；构建lib并确保仓库干净，使用run-swe-expansion.py freeze生成不可变协议。环境准备完成不能称正式实验完成。
4. 启动正式后台批次：qwen3.8-27b、thinking off、并发2；按固定协议运行，不逐题依赖Codex调度。异常停止新派发，无自动重试；保留在途日志与未知usage，不把INFRA计为任务失败。
5. 208次执行完成后统一分析100个配对：官方成功率、净差和区间、全链路token、资产实际消费和诊断指标。负结果照实保留。此轮是固定4题前序的资产迁移，不是100题顺序持续学习，也不覆盖所有仓库。完成SWE-bench后再安排PersonaMem。

## 位置与命令

工作目录 `/Users/lsmax/Coder/dsh-rsi`。环境根目录 `.artifacts/swe-expansion-environments-v2-20261008`。

```sh
python3 scripts/prepare-swe-environments.py status --output .artifacts/swe-expansion-environments-v2-20261008
```

正常终端可查进程；Codex沙箱os.kill权限可能使workerAlive误报false，须用获准权限的ps核对。恢复前阅读 `docs/swe-expansion-protocol-20261008.md`；正式执行用 `python3 scripts/run-swe-expansion.py --help` 核对当前CLI，不能猜参数。

干净评分Python `.artifacts/swe-scorer-venv/bin/python`；健康回执 `.artifacts/swe-expansion-scorer-health-v2-20261008/receipt.json`。数据集 `/Users/lsmax/Coder/EvoAgentBench/data/swebench/data/test-00000-of-00001.parquet`；GGUF `.artifacts/models/embeddinggemma-300m-qat-Q8_0.gguf`。对比组保留各自4题原始历史，RSI另带自然资产；判分和答案不进入学习或任务上下文。
