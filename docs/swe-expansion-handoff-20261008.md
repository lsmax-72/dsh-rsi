# 当前交接边界（2026-10-08）

用户最新要求优先于旧4前序+100独立配对方案：正式应是100题连续序列、空历史/空资产启动、无4前序，固定100题集合以seed20261008一次随机排序，同组历史及RSI原生资产累积、每题源码重置。Thinking和正式预算待预实验确认。正式100题禁止启动；本轮只授权8道已曝光开发题的On/Off预实验。

## 已有证据

旧公开题单、104环境准备、固定快照runner、一键编排和fixture证据保留，不能标成新连续方案已完成。干净官方评分环境有50个源文件发行哈希一致及两题正/负四项健康控制PASS。首次环境准备的ASCII失败原始目录保留，UTF-8修复后已得到真实公开源码环境；其他环境是否完成须实时读取state，不能从旧进度推断。

工作目录 `/Users/lsmax/Coder/dsh-rsi`；dataset为 `/Users/lsmax/Coder/EvoAgentBench/data/swebench/data/test-00000-of-00001.parquet`；评分Python为 `.artifacts/swe-scorer-venv/bin/python`；GGUF为 `.artifacts/models/embeddinggemma-300m-qat-Q8_0.gguf`。已有环境根 `.artifacts/swe-expansion-environments-v2-20261008` 只作材料。保留所有原始日志、资产、评分证据、失败尝试与冻结快照。

## 当前推进

先实现并验证Thinking专用预实验：固定此前连续开发8题全集及原预注册顺序，每题On/Off顺序交替，共16次串行独立任务，真实请求标志与服务推理内容留证，官方判分隔离。题单及结论范围见 `docs/thinking-preexperiment-protocol-20261008.md`。不把开发结果和新100题混分，不按成绩追加预实验题。

预实验结束后报告成功对数、配对变化、耗时、已知token、未知usage和截断/服务异常。先核验模式、usage和INFRA完整性，再以官方通过题数为主；平局结合全部前台known token、墙钟与截断。差1题也只给暂定开发建议，不能称稳定结论；不得自行给差值或成本阈值、替用户确定正式配置或启动100题。随后按用户确认结果固定正式预算与Thinking，实现新的连续runner、持久化原始序列顺序与每20题报告，验证两组隔离、评分不回流、暂停恢复及输入冻结。

旧正式入口start应禁用。新方案验收并重新冻结后，才交付用户自行启动命令。新序列有历史依赖，不给iid置信区间；阶段曲线不直接证明学习收益。SWE-bench本轮完成统一分析后才推进PersonaMem。Git操作继续使用有效lsmax身份；是否提交或push按当前授权执行，不从历史文档推导新授权。
