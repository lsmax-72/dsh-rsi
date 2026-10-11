# SWE-bench 连续学习后台启动

## 当前授权与正式配置

用户已通过资产消费验收并确认正式预算，授权工程检查通过后自动启动；无需再次确认。正式序列为100道未曝光Django任务、两组共200次执行，seed20261008固定同题序，无额外4题预热。从空历史/空资产开始，各组连续继承自己的原生历史，RSI自然更新和消费Memory/Skill；每题重置源码，评分不回流。

- Qwen3.8-27B，Thinking Off。
- 两组每题前台60次、1200秒、单次输出8192 Token；原生压缩调用同样计费和计入前台预算。
- RSI后台每题20次，全序列持久共享池2000次；等待最多900秒。
- 等待只观察原生运行状态：本题日志已捕获、游标到达turn/end、任务完成、队列空闲、缓冲和延迟提炼均已清空、Profile无在途工作时立即交接。仅队列暂时为空不能提前结束。
- 达到等待上限时安全关闭、保存原生状态；不能伪造学习完成。原生规则不学习`aborted`轮次；安全取消保留历史和资产，不能误判成漏学。首次模型调用前取消时，保存零调用日志并列为INFRA，不冒充请求审计通过或官方任务失败。关闭状态存在漏捕获、重复任务、在途调用或无法结算额度时停止新派发。

## 一次启动，无需Codex在线

入口 `scripts/start-swe-continuous-study.py` 复用环境准备器、连续Runner、冻结校验和独立官方Verifier。它等待全部100题环境就绪，逐项核验数据、公开输入、源码树、镜像、官方评分发行及验收证据，然后使用独立锁定代码工作树冻结并启动后台Runner。

```bash
cd /Users/lsmax/Coder/dsh-rsi
python3 -B scripts/start-swe-continuous-study.py start \
  --output .artifacts/swe-continuous-launch-20261011 \
  --spec docs/evidence/swe-continuous-approved-20261011.json \
  --environments .artifacts/swe-continuous-environments-20261009 \
  --study .artifacts/swe-continuous-formal-20261011 \
  --dataset /Users/lsmax/Coder/EvoAgentBench/data/swebench/data/test-00000-of-00001.parquet \
  --scorer .artifacts/swe-scorer-venv/bin/python \
  --embedding .artifacts/models/embeddinggemma-300m-qat-Q8_0.gguf
```

同一输出目录只允许启动一次。已有目录先查状态，不重复执行start。另有后台缓存维护：空间低于30GiB时，只按记录ID清理未共享、可回收且描述明确属于本项目的构建缓存；保留镜像和状态，操作清单写入启动目录。关闭检查点之间重复的本组历史使用APFS独立文件克隆共享物理块，前后核验原哈希；文件仍独立，后续写入不改动上一检查点，不清除历史。模型服务与Docker须保持可用、电脑不能关机；进程会脱离当前窗口，但不跨系统重启。

```bash
python3 -B scripts/start-swe-continuous-study.py status --output .artifacts/swe-continuous-launch-20261011
python3 -B scripts/start-swe-continuous-study.py stop --output .artifacts/swe-continuous-launch-20261011
```

`WAITING_ENVIRONMENTS`表示正式模型任务尚未开始；`RUNNER_LAUNCHED`表示连续Runner已交接启动。实际派发和进度以状态返回的`study`与`formal100Started`为准。正式Runner `COMPLETE`才表示200次执行全部关闭；有INFRA时不能声称全部获得有效官方判分。

准备失败、空间低于15GiB、冻结校验失败、跨组污染或状态不安全会写出`HALTED`/停止状态及原因。禁止自动删除尝试、重复跑题、换题或改预算。环境准备阶段的已识别网络传输失败，只有输出目录完全空、无模型派发且旧进程退出时才自动归档恢复，每题最多3次；保留每次日志。部分源码/构建产物或非网络错误不得自动重试。冻结前主目录代码/构建产物需保持不变；冻结后主目录编辑不影响独立实验工作树。

## 结果位置

正式目录 `.artifacts/swe-continuous-formal-20261011/` 保存冻结`protocol.json`及哈希、逐题`record.json`、关闭检查点、预测补丁、原生请求Trace和独立评分日志。`background.log`记录运行异常，`state.json`记录结束或停止原因。

`summary.json`每次关闭后自动更新，包含每20题阶段和累计通过率、同题配对净差、Memory/Skill生成与正文消费、前台/后台实际Token、未知usage、嵌入调用/字符/耗时及执行异常；`report.md`列出逐题状态。单条连续序列存在历史依赖，不计算100次独立重复的置信区间。资产正文进入请求仅证明消费，不能单独证明相关性或决策收益。

完整100题官方通过率及净差仅在判分完整时提供；INFRA单列，不能当成官方失败。等待逻辑、容器交接和启动器的固定回复/合成测试属于工程验证，不是正式实验成绩。
