# Thinking预实验后台接续

## 本次中止与保留

v3并未跑完：5个真实运行完成，2个完整配对。`django__django-12262/off`在Runner和模型启动之前被冻结检查拦住，原错误为`Frozen revision or clean checkout changed`。Git reflog显示主目录在20:19切到另一个开发分支、20:59回到main，批次在20:24下一例派发前停止。此前第三题On的任务容器已经在切分支前从固定代码构建，因此已保存的结果独立于随后的主目录修改；完整日志、实际请求、Token、补丁与官方判分逐项复核通过。

v3中止记录、报告和已有分数保留，不把未派发记为任务失败，不覆盖或重跑5个已完成例。

## 接续方式

- 独立工作树：`.artifacts/thinking-frozen-84f6025`，detached HEAD固定为`84f6025af94254bf1cfcb384217a0ee93c965666`，工作树已lock以保护运行时文件。
- 原生代码和构建产物的全部冻结哈希一致；原始协议文件及其哈希不变。评分器50个官方源码文件发行哈希核验通过；模型部署身份、数据、任务镜像和公开输入重新验证通过。
- v4目录：`.artifacts/thinking-preexperiment-v4-20261008`，按原顺序接续余下11次真实运行。5份已完成record按字节哈希原样复制，仍指向原补丁/评分证据；原中止的零派发记录保留在v3，接续审计另存`continuation-audit.json`。
- 不增加题目、模型预算、真实任务次数，不改变Prompt或模型设置，不启动正式100题。
- 主目录切分支或提交不再改变该冻结工作树的HEAD、代码或lib。缓存镜像、环境文件和原记录仍保留，身份变动会继续按原规则中止。

## 后台执行和自动结论

批次和最终分析均使用detached进程，stdin为DEVNULL；不用Codex实时参与，也不用逐题监控。最后生成v4的`report.md`和`decision.json`。异常终止生成不完整报告，Thinking建议为空，不拿不足8个配对充当完整结论。结束之后停止，不触发正式100题。

查看状态（不会派发任务）：

```bash
python3 /Users/lsmax/Coder/dsh-rsi/.artifacts/thinking-frozen-84f6025/scripts/run-thinking-preexperiment.py status --output /Users/lsmax/Coder/dsh-rsi/.artifacts/thinking-preexperiment-v4-20261008
```

结束后查看结果：

```bash
cat /Users/lsmax/Coder/dsh-rsi/.artifacts/thinking-preexperiment-v4-20261008/report.md
```

可复用的纯分析入口（只读实验输入，写汇总，不启动模型、求解器或评分器）：

```bash
python3 /Users/lsmax/Coder/dsh-rsi/scripts/report-thinking-preexperiment.py --output /Users/lsmax/Coder/dsh-rsi/.artifacts/thinking-preexperiment-v4-20261008 --wait
```

当前已启动分析进程，不需要再次启动。`--wait`等待批次终态后分析；不加该参数立即分析，未完成时不选择Thinking。原始字节缺失的首例On仍如实披露，其他已完成例完整核验原字节hash；不能称全批原始字节证据毫无缺口。当前仅2个完整配对，不能根据两组不同已完成题数比较通过率。
