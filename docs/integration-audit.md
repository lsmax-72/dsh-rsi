# dsh-rsi 接入审查与接口验证

日期：2026-10-02。状态：已完成安装版本识别、源码审查和无模型接口探针；自动学习闭环尚未接通。

## 1. 审查对象与证据

| 对象 | 本次确认 |
| --- | --- |
| 本机桌面应用 | `/Applications/DeepSeek Harness.app`，版本 `0.2.0-rc.2` |
| 官方附带 CLI | `Contents/Resources/runtime/cli/bin/dsh`，实际运行 `--version` 返回 `0.2.0-rc.2` |
| 随应用附带的运行时清单 | Node `24.18.1`、pnpm `11.7.0`、宿主协议版本 `4` |
| 官方源码审查快照 | `639ed015397290b3745d163aafe02ffee4aa3f84`，源码包版本同为 `0.2.0-rc.2` |
| 记忆与技能核心审查快照 | `e09899c2136fb6bc27ecc68505e32bdb637cdfa8`，审查时核心目录无未提交改动 |

源码版本号相同不代表官方审查快照与安装产物来自同一提交。接口结论优先以安装产物上的运行探针为依据；核心审查快照也尚未决定为最终发布依赖。

本次没有读取用户凭据、启动模型推理或运行 benchmark 任务。探针使用独立临时 `DSH_HOME` 与 `DSH_AGENTS_HOME`，未修改用户的桌面 profile。

## 2. 已通过的接口探针

入口：[probe-host.py](../scripts/probe-host.py)。它通过官方 CLI 的 `sdk-minimal` profile 加载诊断插件，不自行启动替代 harness。

| 检查 | 本次结果 | 能支持的结论 |
| --- | --- | --- |
| 专属目录发现 | PASS，仅发现临时技能 | 专属路径能通过官方 filesystem provider 进入技能目录 |
| 技能正文更新 | PASS，修改后重新加载读到版本二 | 后续加载能取得新正文 |
| 会话事件观察 | PASS，观察到人工追加的 `turn/end` | 插件可以监听正式 `session/event` 入口 |
| 消息日志投影 | PASS，追加正文与 `deriveMessages()` 结果一致 | 合法的模型可见消息能由会话日志投影 |
| flush API | PASS，存在参与的监听器 | 正式 flush API 可调用；尚未证明磁盘保存与重启恢复 |
| 内置 SQLite | PASS，在内存数据库写入并读回 | 安装运行时提供可用的 `node:sqlite` 基础能力 |

[运行回执](evidence/host-probe-20261002.json)记录模型调用次数 `0`、任务命令次数 `0`。SQLite 检查不包含向量扩展或现有资产数据库兼容性。人工追加会话事件不代表真实 Agent 学习流程已完成。

运行时 stderr 中存在 Electron 的 `task_name_for_pid` 提示，本次 CLI 退出码为 `0` 且所有探针断言通过；不将该提示解释为学习能力或沙箱能力已通过。

## 3. 接入选择

### 会话记录与触发

监听 `session/event`，以 `turn/end` 作为已完成轮次的主要接入边界。是否增量接收 `tool/result`，按 Skill 的缓冲和压缩链路需要决定。事件监听器先提交可追踪的工作项，后台执行提炼；不能在会话 append 的观察回调中重入写同一会话。

适配层转换 dsh 的具名消息、工具结果、时间和会话身份，保留来源关联。恢复会话的历史种子不会重新广播为实时事件；重启补录需要使用正式异步读取或投影接口，不能只依赖实时监听，也不新增已废弃的同步事件快照读取。

记忆内部的轮次阈值、空闲触发和分层提炼可以保留为复用候选。Skill 的缓冲、触发、队列和 Worker 单独装配；仅初始化记忆核心不足以启动 Skill 自动提炼。

### 模型与学习日志

所有学习模型请求经 `ctx.llm.stream()`。接口桥接需要同时覆盖纯文本提炼与带资产工具的多轮调用，不能只转发一次纯文本请求。

建议学习使用独立后台会话，关联原始任务会话；每次调用前记录实际消息、提示词、工具定义、模型参数和使用的资产内容或不可变版本。每轮工具调用、结果、用量、失败和取消也要可追溯。

主会话消费记忆时，通过 `agent/pre-step` 返回可持久化的上下文消息，或通过 `agent.inject()` 进入后续请求。前者要调用并保留 `next()` 返回的决定。不能修改已经冻结的请求，也不能用会变化的当前资产内容代替历史输入。

官方标题生成实现提供了“先记录完整辅助请求，再通过模型服务发送”的参考，但不代表学习会话的完整日志与重启恢复已经实现。

### Skill 消费

独立目录加载已经过探针验证。首版生产接入建议注册专属 `SkillProvider`，按调用的 `cwd` 选择全局与当前工作区资产，并处理禁用、版本和重名。

这个 provider 只负责将已有 SkillCore 资产映射给官方技能 registry，不另建提炼或版本系统。写入、回退或禁用后调用 provider 的 invalidation，后续正文加载读取实际选定的版本。

仅配置一个固定的 `customSkillDirs` 列表不足以实现多工作区动态隔离；目录探针也没有验证工具选择、模型调用技能或技能内容是否改善任务结果。

### 管理页面

按一个可安装 bundle 交付，宿主侧负责资产和后台学习，浏览器侧提供管理界面。官方 `plugins.bundle.config` 插槽按包名注册，满足已确认的插件详情页入口。

宿主与浏览器之间通过正式 API/RPC 提供数据和操作，不从浏览器直接访问本地资产文件。页面集成、四个标签及真实操作尚未实现。

## 4. 核心复用边界与需要的改动

| 能力 | 复用候选 | 必要适配或未决事项 |
| --- | --- | --- |
| 记忆 | L0 记录、分层调度、提炼、检索 | dsh 消息格式、作用范围、模型桥接及生命周期 |
| Skill | SkillCore、资源存储、版本、SkillExtractor | 模型与工具桥接、独立 provider、语言配置 |
| 自动提炼 | 本地缓冲、触发、队列、Worker | 明确启动、停止与重启恢复；不能将本地内存队列误称为持久队列 |
| 本地存储 | SQLite 与本地 StorageAdapter | 向量扩展、资源路径和实际安装依赖仍需运行验证 |
| 上层资产管理 | 本插件管理页 | 可选资产元数据钩子不要求引入团队与成员管理 |

源码审查发现三处明确的接入问题：

1. 当前发布包只导出原宿主插件根入口，没有独立的核心库入口；需要建立可构建、可测试的内部核心入口与依赖清单。
2. 记忆有 HostAdapter/LLMRunnerFactory 接口，但 Skill 的模型调用器在核心内部直接构造，并带有原有凭据检查。应让 Skill 接收外部 runner，或在适配层独立装配现有 SkillExtractor；不能靠填写虚假凭据或绕过 dsh 模型服务解决。
3. Skill 自动提炼的队列和 Worker 由宿主装配。已有本地队列实现可作为候选，但后台任务恢复、取消和插件卸载仍需验证。

这些是封装与宿主适配问题，目前不足以推出必须重写记忆或技能的核心机制。也不能把源码中存在接口等同于可直接安装运行。

## 5. 沙箱结论

本次使用的 `sdk-minimal` 默认配置包含 `danger-full-access`。探针没有执行任务命令；该配置不作为正式 benchmark 的隔离环境。

后续实验需要把文件、终端、子进程等入口统一指向实验容器，并验证其他已加载工具不能绕过。安装环境中的 Skill 目录加载和 SQLite 检查没有证明容器隔离成立。

## 6. 下一阶段的完成条件

1. 建立内部核心入口与可安装 bundle，固定兼容目标和依赖。
2. 通过真实 dsh 会话完成记录、调度、模型调用、资产更新与后续消费，保存实际输入与资产版本证据。
3. 验证工作区隔离、禁用和回退生效，以及重启后的持久化恢复。
4. 再接入任务容器和官方判分器，执行少量任务试跑。

模型调用桥接、完整后台日志、自动学习与容器执行均为下一阶段工作，本次不报告效果提升。

## 7. 官方源码依据

- [架构与 profile](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/docs/architecture.md)
- [bundle 打包与安装](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/docs/user/develop/basic/publish.md)
- [Skill provider 接口](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/skill/skill/src/index.ts)
- [独立技能目录](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/skill/skill-filesystem/README.md)
- [会话事件与 flush API](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/core/session/src/index.ts)
- [模型调用接口](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/llm/llm/README.md)
- [辅助请求日志示例](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/session/session-title-llm/src/index.ts)
- [管理页面插槽](https://github.com/deepseek-ai/deepseek-harness/blob/639ed015397290b3745d163aafe02ffee4aa3f84/packages/client/ui-plugin-manager/README.md)

## 8. 后续实现进度（2026-10-02）

核心入口与模型桥接阶段已完成安装版宿主集成检查。现有 L1 提炼、SkillExtractor/SkillCore 和版本存储通过 dsh 模型服务运行；固定模型夹具的请求与持久会话投影一致，第二个独立进程成功恢复资产与日志。详见[实现进度与边界](implementation-progress.md)及[回执](evidence/bridge-probe-20261002.json)。

这更新了前面接口探针阶段的“尚未验证持久化”状态，未改变自动学习、完整召回、前台消费、UI 和任务容器仍待实现的结论。

## 9. 闭环与管理 API 更新

已完成真实 Agent 任务结束捕获、原生 L0/L1/L2/L3、Skill 自进化、正式上下文消息与官方技能 provider 的后续消费；工作区、预算、附件、版本、语言转换及重启检查见 [闭环回执](evidence/runtime-phase2.json)。官方 Client RPC 挂载与 Host Gateway 同时经过验证。页面使用官方闭包工厂格式和 bundle 详情插槽。原文中的“下一阶段”保留为审查时点记录，当前状态以 [实现进度](implementation-progress.md) 为准。

未完成个人桌面 profile 的安装验收，也未验证任务容器边界或产生 benchmark 分数。
