# 官方判分器检查

更新：2026-10-03。仅验证判分可靠性，不代表插件效果。

使用全新 Python 环境安装固定 `swebench==3.0.0`，逐文件校验发行包 RECORD：50 个 Python 源文件全部匹配。此前环境存在已修改的解析器，因此未用于本次判分。沿用官方 `make_test_spec`、`run_instance`、`get_logs_eval`，没有重写解析器、测试生成或评分。

| 任务 | 官方正确补丁 | 非空错误补丁 | FAIL_TO_PASS 数 |
| --- | --- | --- | --- |
| django__django-10973 | resolved=true | resolved=false | 5 |
| django__django-11292 | resolved=true | resolved=false | 1 |

错误补丁实际修改无关注释并执行测试，没有利用空补丁提前返回。四次运行均解析到所有指定 FAIL_TO_PASS 测试；正确补丁分别解析 5、32 项，错误补丁分别解析 10、33 项。每次使用独立 run ID，避免缓存复用。

评分读取官方 Verified parquet，正确补丁与 test patch 仅存在独立判分目录和评分容器，禁止传入任务 Agent。任务只得到源码、问题描述和公开测试。评分容器断网，限制内存、进程和 capabilities；准备阶段可以下载公开依赖。CPU 架构固定 x86_64，与官方缓存任务镜像一致。

复现入口：在全新环境安装 `swebench==3.0.0`、`pyarrow`、`docker` 后，运行：

```bash
python scripts/probe-scorer.py --dataset <官方Verified.parquet> --work-dir <独立判分目录> --output <回执.json>
```

该脚本仅负责准备、边界配置和收集官方结果。回执见 [scorer-preflight-20261003.json](evidence/scorer-preflight-20261003.json)。真实生成补丁须另行评分；不能把控制实验的通过率报告成模型或插件成绩。
