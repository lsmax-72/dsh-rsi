# SWE 连续学习 Runner（2026-10-09）

## 本轮交付和边界

Thinking Off已确认。8个Off开发轨迹中6个触及40次上限，2个触顶题通过；触顶发生在2–5分钟，部分题直到38/40次仍修改。因此建议正式前台60次/20分钟/每次8192，尚未声称增加预算会提高成绩。正式预算等待确认，100题尚未启动或完成准备。

新Runner为 `scripts/run-swe-continuous.py`。从空历史/空资产开始，串行执行同一题序，两组分别直接继承自己的原生会话；RSI另继承自然生成的Memory/Skill。每题源码恢复初始版本，不恢复前题源码补丁；阶段统计不重置历史或资产。原固定100题集合保留，seed20261008一次打乱，不包含曝光题或额外4题预热。

复用：原生Agent、seed/fork、会话持久化、压缩与裁剪，现有隔离任务执行器、请求/服务字节审计、持久学习额度池和独立官方Verifier。新增：顺序协调、各组关闭状态交接、冻结代码工作树、阶段报告与交接审计。生产后端仅修改fork下的捕获边界，跳过继承事件，防止前题学习重复排队；没有修改Memory/Skill提炼、向量召回、原生压缩或官方评分算法。

## 无需Codex在线的运行方式

先commit/build，再freeze到独立锁定工作树。冻结数据集、公有题输入、题序、模型部署元数据、镜像ID、完整代码/产物哈希和所有预算。后台进程运行冻结工作树，主目录后续普通编辑不会使批次停下。

```sh
cd /Users/lsmax/Coder/dsh-rsi
python3 -B scripts/run-swe-continuous.py freeze \
  --output .artifacts/swe-continuous-development-20261009 \
  --spec docs/evidence/swe-continuous-development-spec-20261009.json \
  --dataset /Users/lsmax/Coder/EvoAgentBench/data/swebench/data/test-00000-of-00001.parquet \
  --scorer .artifacts/swe-scorer-venv/bin/python \
  --embedding .artifacts/models/embeddinggemma-300m-qat-Q8_0.gguf
python3 -B scripts/run-swe-continuous.py start --output .artifacts/swe-continuous-development-20261009
python3 -B scripts/run-swe-continuous.py status --output .artifacts/swe-continuous-development-20261009
```

以上是2道已曝光开发题×2组的入口，不是正式100题。前台40次/1200秒，学习每题20次、共享40次、每题最多等待900秒，输出8192。目录已存在时不要重新freeze或重跑；以status确认是否已经启动。

`state.json` 的COMPLETE表示所有计划尝试安全关闭；并不保证全部判分有效或交接验收通过。结束自动生成 `report.md`、`summary.json`、`inheritance-audit.json`，逐题保留补丁、官方评分及原始轨迹。安全关闭的评分/模型异常继续后题并单列INFRA；完整官方通过率/配对净差在判分缺口存在时留空，观察到的已判分率另列。没有自动重试。请求stop只在当前任务结束后停止；无法安全关闭、冻结篡改、跨组污染不能继续。

## 必须验证的真实交接

先用固定模型回复验证真实容器、原生Agent/工具/持久化/fork、源代码重置、字节一致的原历史恢复及不重复捕获旧轮次。另强制一次原生idle compaction，验证摘要进入后续请求、源日志保留、压缩调用计入预算；该测试只验证管线，不是Qwen能力或RSI效果证据。

随后两道曝光题使用真实Qwen自然运行、学习和消费，不预写经验、不按评分挑资产、不注入指定Skill。批次完成后离线审计确认：两组实际下一题请求继承前序对话，Memory正文来自前题关闭资产，Skill由本题正常工具加载且正文匹配前题资产。消费缺口如实报告；固定回复测试和“文件存在”都不能放行正式冻结。

## 结果与成本

每题记录官方通过、运行/评分异常、调用次数、实际输入/输出Token、未知usage、时间、停止原因、补丁版本、完整正文来源、资产创建/更新/移除。原生压缩调用属于前台，RSI提炼调用属于学习。原生本地embedding单列调用、字符和耗时，不把字符估计为Token；当前未提供embedding Token计量，不能声称得到精确全链路总Token。

Memory实际模型正文消费与Skill本题加载、继承的旧加载正文分别可查。正文送达不证明相关性或影响决策；固定诊断位置再离线审阅相关性、正文长度、首次有效补丁以及重复排查/测试。最早保存修改的轨迹位置不能直接宣称最早官方有效修改。每20题阶段及累计结果自动写出，不进行iid区间或中途调参。

## 正式入口仍有门槛

正式draft仅记录100题候选、固定顺序和预算建议。冻结要求预算已确认、100题环境均可核验，以及本实现的 `PASS_REAL_CONTINUOUS_STATE` 真实交接/双资产消费证据。正式环境准备器现在接受100题无前序规范，但本轮还未启动100题准备或实验。
