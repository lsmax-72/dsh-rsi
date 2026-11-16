# dsh-rsi

让 Coding Agent 从历史任务中积累可复用的 Memory 与 Skill，并在后续会话中按需使用。

## 功能

- 采集真实会话与工具执行轨迹，异步提炼 L0–L3 分层 Chat Memory 和可复用 Skill。
- 在模型步骤开始前按预算注入相关记忆、场景导航和用户画像。
- 通过 Skill Provider 暴露 `rsi-` 前缀的技能，由 Agent 按需加载正文和资源。
- 在插件详情页管理记忆、技能、版本、学习任务和调用成本。

## 使用

安装并启用后，在 dsh 左侧「插件」→ dsh-rsi 打开管理页。正常执行任务，后台学习会在满足稳定条件时入队；后续在相同工作区的新会话中消费资产。

默认数据目录为 `$DSH_HOME/plugin-data/dsh-rsi`，可用 `config.dataDir` 覆盖。

## 配置

```yaml
- id: dsh-rsi
  config:
    dataDir: /absolute/path
    embedding:
      provider: local
      modelPath: /absolute/path/embeddinggemma-300m-qat-Q8_0.gguf
```

`embedding` 默认使用本地 `embeddinggemma-300m`（768 维），首次启动从 Hugging Face 下载；无法访问时指定已有 GGUF 文件。向量模型未就绪时，记忆检索会明确报错，不会静默退回关键词检索。

## 限制

- 单用户、本地插件；资产按工作区与通用范围隔离，不提供团队或权限管理。
- 后台学习会调用模型并消耗调用预算；预算不是费用或 Token 总量上限。
- 资产由模型提炼，可能出现错误或不完整，需要在管理页人工检查。
- 兼容范围由 `package.json` 的 `engines.dsh` 声明；RC 版本变化不保证向后兼容。
