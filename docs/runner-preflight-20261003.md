# 统一运行器与中断验收

2026-10-03；断网固定响应检查通过，正式配对实验未启动。

## 本轮修正

复用已有官方 dsh Agent、会话持久化、工具、Skill 服务和固定上游模型网关。`scripts/probe-runner.py` 仅负责配置、容器及证据导出；`scripts/pilot-task.mjs` 负责驱动同一官方 Agent 和观测请求，不实现学习算法。

- `--arm baseline` 从启动 patch 中删除插件。原始组没有插件服务、资产目录、记忆注入和插件 Skill provider；保留相同基础工具。
- `--arm rsi` 使用完整插件。快照复制到每次独立的实验卷，不修改来源库。恢复后检查实际预算，配置不匹配立即退出。已保留一次启动预算 15 与快照预算 30 不一致的失败，没有发模型请求。
- 请求正文在调用前落盘并 fsync，官方会话先 flush；usage 返回后及时保存，工具结果后保存补丁。结束与异常分别保存运行器状态，官方 resolved 尚未判分时保持 null，错误不一律包装为 INFRA。
- 每个前台阶段有独立额度和全程额度。后台使用原有自动调度；不手动调用 learn/captureStored。阶段可恢复初始代码，后续独立会话不在提示中指定 Skill 名称。
- 结束前关闭后台链路，再审计、汇总，避免遗漏关闭阶段的调用。原生发布事件另有持久镜像；强制结束时可从持久卷导出日志、补丁与请求副本。导出失败则保留卷用于恢复，不删除唯一证据。

## 已通过的检查

原始组和插件组的代码树一致，插件组三次初始资产导出一致；真实官方 write 工具产生相同补丁。原始组 8 个基础工具，插件组仅多出 3 个插件检索工具。4 次成功固定响应检查没有真实模型请求。

进程在工具已写文件、第二次请求已持久记录后被 SIGKILL（137）：补丁、原生日志、请求副本完整导出；两次输入均可由官方 Session 重建。第二次没有响应/usage，明确记录为未知；不把固定响应的模拟 token 当作真实成本。

冻结复用核心 56 文件和面板 10 文件哈希仍通过。机器证据：[runner-preflight-20261003.json](evidence/runner-preflight-20261003.json)。完整原始材料位于本地忽略目录 `.artifacts/runner-preflight-20261003`。

## 运行入口

需先构建插件，并准备包含 `/opt/task-source`、公开 `task.json`、官方 dsh 与依赖的隔离任务镜像；不复制隐藏测试、答案补丁、个人 profile 或个人资产。

```bash
python3 scripts/probe-runner.py --arm baseline --fixture --settle-seconds 0 --output /tmp/rsi-baseline-control
python3 scripts/probe-runner.py --arm baseline --fixture --interrupt-checkpoint --settle-seconds 0 --output /tmp/rsi-interruption-control
```

真实预演还需 `--baseline-date` 固定评分镜像的实际 HEAD 时间，且先验证代码树与版本；基础提交时间可能与评分镜像新增提交不同。

真实预演需要将已授权模型地址放入 `RSI_MODEL_UPSTREAM` 环境变量，不写进代码或仓库。运行参数必须先固定；输出目录必须为空，避免覆盖失败材料。入口只执行一次少量预演，不自动扩量为正式 benchmark。

## 剩余范围

固定响应检查不能证明真实默认学习、自然 Skill 选择或效果。接下来从新资产库做有限真实维护任务预演，观察默认 L1/L2/L3 调度、独立消费会话和全量 token。正式题单、规模、预算与重复方案仍须在正式运行前确定。
