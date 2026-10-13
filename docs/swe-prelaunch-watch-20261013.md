# SWE 未启动构建失败的后台恢复

## 本次停止原因

第30题 RSI 的 `npm ci --ignore-scripts` 下载依赖遇到 `EIDLETIMEOUT`，注册表为 `registry.npmjs.org`。构建失败发生在 Agent、模型网关和学习启动之前。缺失回执是下游症状，不是题目失败。磁盘仍有约37 GiB空间，Docker镜像存储读取正常，未再次重启Docker。

真实宿主与Docker内注册表探针均返回HTTP 200。冻结部署、200个镜像引用、58个安全关闭检查点及第29题RSI来源快照核验通过。故障租约明确为零调用且保留，原学习额度没有重置。已归档未启动事务，由原冻结Runner恢复第30题RSI；58次已关闭运行字节未变，不重跑。

## 复用与改动

- 扩展现有 `recover-swe-prelaunch.py`，额外识别 npm 注册表传输错误 `EIDLETIMEOUT / ETIMEDOUT / ECONNRESET / EAI_AGAIN`。
- 拒绝依赖完整性、lockfile、未知构建错误、任务/模型已有输出、状态不明、未结算额度、残留运行资源及任何冻结校验失败。
- 每题最多归档恢复3次未启动构建事务。任务真正执行后的错误不会通过此路径重跑。
- 新增 `watch-swe-prelaunch.py`，独立后台轮询状态；复用上述完整验收与原冻结Runner启动入口，恢复后启动原缓存维护脚本。
- 实验停止或完成、用户STOP时守护退出。无法通过安全验收时写入 `BLOCKED` 并退出，保留原HALTED状态；不修改预算、依赖锁定版本、题序、生产算法或Prompt。

冻结实验代码仍为 `3df8f2712b6017f40f678510ad5c8c53bafc4236`。后台守护属于外部恢复工具，不进入Agent工具集或模型上下文，也不消费评分结果。

## 验证

16项恢复入口控制及6项守护状态控制通过。真实后台入口已完成 HALTED → 归档 → 原Runner续跑 → WATCHING 的交接，所有58个已关闭记录哈希保持一致。证据见 `docs/evidence/swe-npm-recovery-20261013.json`。

本次验证证明安全的零调用基础设施恢复，不证明网络不会再次超时，也不代表100题实验完成或RSI有效。

## 查询

```bash
python3 -B scripts/start-swe-continuous-study.py status --output .artifacts/swe-continuous-launch-resume-20261012
cat .artifacts/swe-continuous-launch-resume-20261012/prelaunch-watch/state.json
```

守护状态 `WATCHING` 表示后台守护存活；`BLOCKED` 需查看其 `error` 与归档日志；`FINISHED` 表示守护结束。实际任务状态仍以 `study.status` 为准。守护已后台启动，不要重复启动。
