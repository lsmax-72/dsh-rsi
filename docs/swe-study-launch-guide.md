# SWE-bench 独立后台启动

本轮固定4题前序、100题配对，两组共208次任务执行；使用qwen3.8-27b、thinking off、并发2。对比完整RSI与原始dsh。每个后序任务复制本组固定前序快照，后序学习不会传到其他后序题。题单、预算和分析口径见 [扩样协议](swe-expansion-protocol-20261008.md)。

## 启动一次

在普通终端运行：

```sh
cd /Users/lsmax/Coder/dsh-rsi
python3 -B scripts/start-swe-study.py start
```

命令返回后台PID后即可关闭终端或Codex。后台自动完成剩余102个环境准备、构建、协议冻结、任务执行、官方判分和集中汇总；这些步骤无需Codex逐题参与。当前环境准备已暂停且完成2/104，本轮真实模型调用0次。此命令会恢复准备，并在准备齐备后自动开始模型实验。

保持Docker Desktop运行、电脑唤醒并联网，能访问已配置的qwen服务 `http://10.195.214.152:8100/v1`。关闭Codex与额度耗尽不影响后台进程；电脑睡眠、关机或网络中断会影响运行。运行期间不要修改此仓库代码、提交版本或执行构建，否则冻结检查会停止实验。后台在准备阶段检查磁盘，少于15GiB停止；不会自动清理共享镜像。

沿用前台每题40次/1200秒、RSI前序后台共100次、后序每题后台10次的固定预算。粗估全链路聊天用量120M–160M token，仅为历史成本估计，不是token硬上限；全部尝试与未知用量照实记录。正式完成前只报告进度，不报告效果。

## 查看是否结束

```sh
python3 -B /Users/lsmax/Coder/dsh-rsi/scripts/start-swe-study.py status
```

- `NOT_STARTED`：尚未启动。
- `STARTING` / `RUNNING`：后台执行中，`phase`显示准备、构建、冻结、任务或汇总阶段；`preparation.completed`显示准备进度，`study.closedRuns`显示已判分任务次数。
- `COMPLETE`：实验和汇总完成，`summary`给出结果JSON路径；计划208次执行全部关闭判分。
- `STOPPED`：收到暂停请求或磁盘不足，查看`reason`及准备状态。
- `HALTED`：出现异常，查看`error`及阶段日志；保留证据，不自动重试或换题。

结果目录 `.artifacts/swe-expansion-study-20261008/`；编排状态及逐阶段日志在 `.artifacts/swe-expansion-study-20261008-launcher/`；环境准备日志在 `.artifacts/swe-expansion-environments-v2-20261008/logs/`。summary记录配对成功率、净差区间及已知全链路token，不能把任务交付率当质量指标。资产决策影响等诊断仍需在完成后依据记录审阅；后台可独立跑完并产出统计，不会自动生成研究解释。

## 暂停与恢复

```sh
python3 -B /Users/lsmax/Coder/dsh-rsi/scripts/start-swe-study.py stop
```

停止新派发，当前在途任务允许结束并保存记录。等状态`STOPPED`后，再运行同一`start`命令是显式恢复：清除STOP，只跳过完整关闭的任务，保持原题单和协议。`HALTED`或存在未完成尝试时拒绝恢复，必须先查明原因；不通过删除记录或重跑来掩盖失败。

## 已做的验证

独立控制进程与真实本地fixture子进程完成准备/构建/冻结/执行/汇总编排，STOP、续跑、锁、输入变化和失败停止共7项检查通过，真实模型及Docker操作均为0。基础任务控制器另有15项离线检查；官方评分器两题正负对照共4项实际通过，50个官方源码文件哈希完整。剩余102个真实环境尚未准备，不能把fixture通过视为所有真实任务已经验收。
