# dsh-rsi

面向官方 DeepSeek Harness 桌面版的本地自动学习插件。复用记忆与技能核心，从任务轨迹中积累 Chat Memory 与 Skill，并通过正式 dsh 接口供后续任务使用。

## 当前状态

已有可构建的开发插件。真实 dsh `0.2.0-rc.2` 运行时下，固定模型夹具验证了任务捕获、原生提炼、记忆注入、官方技能工具消费、工作区隔离、预算、版本与重启恢复。管理 API 使用官方 Gateway，页面构建和交互经过独立夹具检查。

尚未公开发布，未安装到个人日常 profile，未完成任务容器隔离与真实模型 benchmark，不能据此宣称效果提升。详细边界见[实现进度](docs/implementation-progress.md)。

## 本地开发

需要 Node 24 和对应版本的官方 dsh 安装。

```sh
npm ci --ignore-scripts
npm run build
npm run test:integration
npm run test:runtime
```

macOS 探针默认使用应用内 CLI；其他环境通过脚本的 `--dsh` 参数指定 CLI。所有集成检查使用临时目录和固定模型响应，不读取个人模型凭据。

## 安装开发包

完成构建后，在 dsh「插件 → 添加插件」输入本地目录 `/Users/lsmax/Coder/dsh-rsi`。命令行也可创建独立测试 profile：

```sh
dsh plugin --profile rsi-dev add /Users/lsmax/Coder/dsh-rsi
dsh --profile rsi-dev
```

上面的命令是官方本地 bundle 安装方式；本项目尚未记录完整安装验收。建议先用独立测试 profile；不要把缺少沙箱验证的 profile 用于实验任务执行。安装后，进入插件详情页查看「概览 / 记忆 / 技能 / 设置」。

源码安装已配置 `prepare` 自动构建；正常 `npm ci` 会生成 `lib/`。上方使用 `--ignore-scripts` 时仍需显式执行构建。包保持 `private: true`，`npm pack` 可生成本地安装 tarball；远程 Git URL 经 dsh 安装器的流程和正式 npm 发布尚未验收。

## 使用

正常完成任务后自动学习；暂停学习时已有资产仍可消费。学习模型跟随来源会话，后台每次请求写入正式会话日志。默认资产语言中文，每日最多 100 次后台请求，超额暂停新学习调用。

工作区资产与通用资产分开；生成的技能使用独立 provider 和 `rsi-` 名称。已有技能可主动复制为管理副本，包含本地资源；之后的更新保留版本。管理页支持记忆纠正、技能禁用与回退、语言转换、导出和范围清理。

不包含 Wiki、CodeGraph、团队管理、成员权限、Agent/Task 管理、模型训练或插件自身代码修改。

## 文档

- [产品需求](docs/product-requirements.md)
- [实现进度、目录和已知限制](docs/implementation-progress.md)
- [接入审查](docs/integration-audit.md)
- [安装打包与发布审查](docs/packaging-review.md)
- [管理页组件复用与适配边界](docs/ui-reuse.md)
- [整体验收与实验方案](docs/evaluation-plan.md)
- [闭环运行回执](docs/evidence/runtime-phase2.json)
- [复用源码清单](vendor/core/manifest.json)与[许可证](vendor/core/LICENSE)
