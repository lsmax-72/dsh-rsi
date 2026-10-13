# SWE 连续学习实验存储恢复

## 原因与处理

第25题 RSI 在 Docker 镜像导出阶段遇到 `input/output error`，没有启动任务、模型网关或学习。缺失 `receipt.json` 是构建失败的后果，不能计成题目失败。保留原 HALTED 记录、构建日志和学习额度凭证。

已清理用户授权的可重新下载缓存。Docker 重启后，镜像清单恢复读取，原先运行的12个容器恢复。可用空间恢复到约40 GiB；本次恢复阶段未删除实验镜像、卷、日志、历史或资产。无模型、无网络的实际构建与写后读取探针通过。

## 恢复边界

新增 `scripts/recover-swe-prelaunch.py`，复用冻结 Runner 的配置、镜像、原生状态校验、统计及后台启动入口。冻结代码仍为 `3df8f2712b6017f40f678510ad5c8c53bafc4236`，预算、Thinking Off、题序、算法和 Prompt 均未改变。

仅允许恢复“完整安全关闭前缀后的一次 RSI 构建导出存储失败”。必须同时满足：

- 原 Worker 已结束，两把控制锁可取得。
- 原冻结数据、代码、200个任务/评分镜像引用及模型身份一致；至少30 GiB可用空间。
- 全部已关闭检查点有效，失败题来源严格等于前一道同组检查点。
- 失败目录仅有构建、来源和额度凭证；没有模型、任务、评分、资产输出或检查点。
- 失败学习租约已明确结算为 `used=0 / NO_TASK_STARTED`，无未结算租约，无残留运行资源。

验收后，将未启动事务和旧统计归档到 `prelaunch-recovery/`，保留零调用租约，不伪造回执或判分。核对49个原记录字节不变，转入可续跑状态，由原冻结后台入口 `start --resume` 继续第25题 RSI。已关闭49次运行不重跑。

## 验证与当前状态

- 12项离线控制通过，包括模型/状态证据、额度不明、错误来源、后续记录和检查点等拒绝恢复情形。
- 真实冻结校验、49个检查点、来源快照、模型部署及预算检查通过。
- 真实 Docker 写读通过。第一次探针错误地把镜像ID用于 Dockerfile `FROM`，引发远程元数据查询；已改用核验过的本地标签并禁止拉取，保留两次探针记录。没有任务或模型调用。
- 原 Runner 和原缓存维护脚本独立后台运行，从第25题 RSI 续跑。

实际恢复证据见 `docs/evidence/swe-storage-recovery-20261013.json`。这证明安全恢复与后台启动，不代表实验已经完成或 RSI 效果已验证。未来基础设施、冻结或状态安全问题仍按原协议停止派发。

## 入口

```bash
# 仅审计，默认不改变状态
python3 -B scripts/recover-swe-prelaunch.py --output .artifacts/swe-continuous-formal-20261011

# 审计通过后归档未启动事务并后台续跑；当前批次已经执行，不要重复运行
python3 -B scripts/recover-swe-prelaunch.py --output .artifacts/swe-continuous-formal-20261011 --apply

# 观察实际实验状态
python3 -B scripts/start-swe-continuous-study.py status --output .artifacts/swe-continuous-launch-resume-20261012
```

每20题阶段与最终统计继续由原后台 Runner 自动生成，不依赖交互窗口或 Codex 持续参与。
