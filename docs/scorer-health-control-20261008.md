# 官方评分器健康检查的负控修正

2026-10-08。使用 `.artifacts/swe-scorer-venv/bin/python` 中原始 `swebench==3.0.0`，逐文件核对安装分发哈希；没有修改官方测试生成、parser 或 grading。

## 原失败原因

旧负控只在 `django/__init__.py` 添加无关注释。对 `django__django-10973`，测试执行到未修复的 subprocess 路径，因评分镜像没有 `psql` 得到 5 个 ERROR。最后一个 SIGINT 测试有多行 docstring；官方 Django parser 在失败日志中记录短方法名，却没有生成数据集要求的完整 docstring 标识。因此官方报告虽然是 `resolved=false`，脚本的严格 `FAIL_TO_PASS` 完整解析检查仍失败。原始证据保留在 `.artifacts/swe-expansion-scorer-health-20261008/grader-only`。

## 最小修正与边界

仅改变宿主侧 `scripts/probe-scorer.py` 的 10973 负控构造：在 grader-only 进程中从正控补丁构造明确错误的密码参数，使普通单行测试失败，保留多行 SIGINT 测试正常执行。正控、负控均仍使用官方 `run_instance` 与 parser；断言仍要求所有 `FAIL_TO_PASS` 标识真实可解析，并分别要求 `resolved=true/false`。11292 保留原非空无关补丁负控。答案、测试补丁和控制补丁只留在 grader-only 目录，不进入任务容器。

这是健康控制的兼容修正，不能宣称修复官方 parser 对任意多行 ERROR 日志的解析缺口，也不能把旧负控报告当作完整健康验收。验证没有模型请求。

## 实际验证

完整 2 题 × 2 条件检查返回码 0，回执为 `.artifacts/swe-expansion-scorer-health-v2-20261008/receipt.json`，状态 `PASS`。10973：正控 resolved=true、F2P=5、parsed=5；负控 resolved=false、F2P=5、parsed=8，官方报告 2 通过/3 失败。11292：正控 resolved=true、F2P=1、parsed=32；负控 resolved=false、F2P=1、parsed=33。全部 F2P 标识包含在原始官方 parser 输出中；parsed 包含额外测试或错误短标识，不能当作 F2P 数量。真实模型请求为 0。

运行命令：

```sh
.artifacts/swe-scorer-venv/bin/python -B scripts/probe-scorer.py \
  --dataset /Users/lsmax/Coder/EvoAgentBench/data/swebench/data/test-00000-of-00001.parquet \
  --work-dir .artifacts/swe-expansion-scorer-health-v2-20261008/grader-only \
  --output .artifacts/swe-expansion-scorer-health-v2-20261008/receipt.json
```
