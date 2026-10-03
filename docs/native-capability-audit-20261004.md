# dsh-rsi 原生能力装配审计

日期：2026-10-04。审计对象：`459134d9d6a72299191799b35af6eb88bb68b454`，运行时源码与首轮正式实验冻结版 `99af6ba2d10250d2950dc08983211feac5cdf69b` 相同。本次只检查、复现并记录问题，没有修复生产代码、调用真实模型或重跑实验。

## 结论

有其他同类问题。除了已经确认的 Chat Memory 向量链路关闭，还发现 Skill 生产提示词被替换、画像触发与计数装配不完整、列表及导出漏分页、上下文粗截断、错误未传播至原生管道，以及部分原生诊断被清空。**复用源码未改，不等于生产能力完整接入。**

56 个核心文件通过 SHA-256 检查，并逐一与选定来源修订 `e09899c2136fb6bc27ecc68505e32bdb637cdfa8` 的 `MemoryCore/src/` 比对，内容差异为零；10 个界面文件也通过清单检查。比较的是项目选定的来源修订，不代表已审计官方最新发行版的全部能力。

## 已确认的问题

| 项目 | 当前实际行为 | 影响与证据 | 优先级 |
| --- | --- | --- | --- |
| Chat Memory 向量链路关闭 | `src/local-core.ts:15` 使用零维 VectorStore；`:52`、`:59`、`:79` 未注入 embeddingService；`:62` 强制 keyword。L0 索引写入也没有 embedding | 不仅召回没有向量/RRF：L1 写入不生成向量，冲突去重候选只能走原生 FTS 分支。原生 L1 写入、去重及混合召回分支存在，却未装配 | 高 |
| Skill 生产提示词被简写替代 | `src/local-core.ts:44` 使用几句自定义 systemPrompt；原生生产入口明确传入 `SKILL_REVIEW_PROMPT` | 工具循环、SkillCore 和版本仍是复用代码，但原生提示词中的完整会话审阅、复用/更新判断、输入角色隔离、SOP/背景/偏好整理及输出约定没有随生产配置接入。这是提炼策略替换，不是必要的模型 API 适配 | 高 |
| 画像触发及计数装配不完整 | `src/runtime.ts:79`、`:89` 直接调用 PersonaGenerator；没有 PersonaTrigger。适配代码也未接原生工厂中的 L1 完成计数、场景完成计数及上一场景状态 | 原生工厂先调用 PersonaTrigger，结合冷启动、恢复、主动请求和阈值决定是否生成。Generator 自身的“无变化跳过”仍保留，因此不能说每次都调用模型；但有变化时缺少原生触发判断，可能增加后台成本。只补 Trigger 还不够，相关检查点更新也需恢复 | 高 |
| Skill 和版本列表漏分页 | 候选、snapshot、导出都只调用一次 `skills.list()`；版本接口和导出只调用一次 `listVersions()` | 原生默认每页 50 条。隔离数据实测：51 个 Skill，候选/管理/导出各只有 50 个；51 个版本，版本管理和导出各只有 50 个，v1 未导出。数据库资产仍在，但消费与导出不完整 | 高 |
| 上下文合并后粗截断，来源记录未同步裁剪 | `src/runtime.ts:201` 先合并通用和工作区结果，再 `slice(0, recallMaxChars)`；refs 在截断之前生成 | 原生预算主要作用于 L1 召回条目；适配层又截断完整合并文本。实测长通用画像占满默认 6000 字符，工作区记忆在原生结果中存在，却没有进入返回文本；refs 仍包含该记忆，画像闭合标签及 profile 工具指引也被截掉 | 高 |
| 提炼错误没有传播给原生管道 | `src/runtime.ts:185` 保存 failed/paused/interrupted 状态后正常返回 processedCount/profileScopes | 原生 MemoryPipelineManager 仅在 runner 抛错时恢复缓冲、限制重试并阻止后续阶段推进。离线注入非预算提炼错误后，job 为 failed，runner 仍正常返回；原生错误重试路径收不到异常。自动恢复列表又不包含 failed，不能将其称为原生重试完整保留 | 高 |
| 原生结构化诊断被清空 | 构建将 obs-logger 替换为 `adapters/local-obs-logger.ts`，info/warn/error 都为空函数；结构化观测 backend 为原生 Noop | 普通 logger、dsh 请求日志和 usage 仍在；但 Skill 提炼的部分结构化事件没有写入任何本地记录。“关闭旧日志目录”不足以描述这个结果。完整生成来源关联也不能仅靠源码校验推定已保留 | 中 |

原生对照位置：`MemoryCore/src/gateway/server.ts:2079` 的 Skill 生产构造；`MemoryCore/src/core/skill/prompts/skill-review-prompt.ts`；`MemoryCore/src/utils/pipeline-factory.ts` 的 L1/L2/L3 工厂；`MemoryCore/src/core/persona/persona-trigger.ts`。以上均按固定修订读取，避免把来源工作区未提交的修改混入比较。

注意：普通提炼错误的修复不能仅增加 `throw`。还要明确哪些任务可进入受限重试，避免原生再次触发时因为 job 已是 failed 而空处理，并保持预算暂停、关停和真正失败的区别。

## 有变化但应区别判断的地方

- **Skill 前台选择由 dsh 承担。** provider 列候选，宿主与模型选择，再通过官方 skill 工具取最新正文。这是宿主接入方式；分页遗漏才是已证实的消费缺口。原生 SkillExtractor 内部的现有技能前缀检索仍在。
- **本地 SkillStore 的向量/RRF 限制来自所选源实现。** `vendor/core/src/core/skill/skill-store.ts:555` 明确仅实现 BM25；embedding/hybrid 分支仍回 BM25。不能把 Chat Memory 已实现的向量/RRF能力直接套到 SkillStore，也不能称这部分已实现但被本插件关掉。
- **记忆提炼输入仍只有 user/assistant。** Skill 接收工具调用/结果及记录的轮次结果；Chat Memory 不接收这些独立工具记录。所选原生 ConversationMessage/L0 本来也只接 user/assistant，因此不能直接认定这是插件删除了原生工具结果能力。不过用于代码任务时，记忆里的“修复/测试成功”仍需和执行证据区分，不能仅信助手自述。
- **L1 输入窗口及连续场景状态改变。** 插件为保留一轮 dsh 任务中的用户输入扩大 native 最近消息窗口，但没有接 `previousSceneName` 的持久衔接。前者有具体宿主适配原因；后者是遗漏。完整长轮次输入对成本的影响需记录，不能自动认为与原生产输入分组等价。
- **召回查询及消息位置改变。** `src/index.ts:37` 将当前消息列表里所有 user 来源文本拼为查询；`:42` 将原生 prependContext 和 appendSystemContext 合并为一个 user 消息。相比当前意图查询与稳定/动态内容分别放置，这改变了检索和缓存语义；尚未测得它对命中或 token 的独立影响。
- **L2 输入范围扩大到工作区。** 原生生产工厂按来源 session 筛增量输入，输出再按 profile 分组；插件用单工作区 L2 key/cursor 处理工作区内新增 L1。现有 key 与 cursor 粒度是一致的，不能凭忽略 `_key` 就断言会重复全量处理；但它确实扩大了单次输入范围。多个工作区同时更新通用 profile 的并发语义还需专项验证。
- **persona 类型自动进入通用库。** 这是现有产品的作用范围路由，不是原生提炼算法本身。应持续验证模型是否将项目约束误判为跨工作区偏好。

## 属于必要适配或产品排除的部分

模型桥使用正式 `prepareCall()` / `prepared.stream()`，dispatch 前持久化日志；用 turn/end 捕获正式事件；后台任务、预算和作用范围由本地插件管理；原生 Runner 的兜底路径被替换成要求注入 dsh runner 的守卫。这些有明确宿主约束，不应与自行简写 Skill 提炼策略混为一谈。

单用户工作区/通用资产的物理隔离、独立 rsi- 名称及资产目录、已有 Skill 的受控复制，是产品要求。团队、用户权限、Agent 管理、Wiki、CodeGraph、远程对象存储和管理服务栈不在目标范围，不能把未接入这些服务列成缺陷。

SkillCore、ResourceStore、SkillVersioning、L0 记录、L1 提炼/FTS/写入、SceneExtractor 和 PersonaGenerator 的实际调用仍存在；此前资源、正文加载和回退检查不是伪实现。但“调用了组件”与“保留全部原生生产装配策略”需要分别陈述。

## 本次复现方法和证据

回执：[隔离复现和来源校验](evidence/native-capability-audit-20261004.json)。脚本：[离线能力审计探针](../scripts/probe-capability-audit.mjs)。运行示例：

```sh
node scripts/probe-capability-audit.mjs "$(git rev-parse HEAD)" > /private/tmp/dsh-rsi-capability-audit-replay.json
```

探针复用现有构建，只临时增加 Runtime 导出并调整模块定位，以便在临时目录中调用同一套 Runtime/SkillCore/存储；生产方法不变。使用临时数据库、51 个 Skill、51 个版本、长通用画像和一个明确的提炼失败夹具。真实模型请求为 0，任务命令执行为 0，既有工作区和实验资产不受影响。

此探针断言的是**审计时缺陷可复现**，不是功能验收通过。修复后应将对应断言改为正确行为，并沿真实宿主消费链验收。现有小样本夹具没有覆盖资产数量增长、长 profile 和普通失败重试，这解释了为何先前接口检查没有发现这些边界。

## 对首轮实验和下一步的约束

首轮分数、请求、token 和冻结资产继续原样保留。该实验度量的是旧适配版 dsh-rsi，不能据此声称已度量完整原生生产策略。分页缺陷在只有少量资产时未必触发；长画像截断复现也不证明首轮 20 个实际请求都曾漏注入；提示词替换与成本增加之间的因果关系尚未验证。不要将所有实验得失归因到本次发现。

下一步先修复消费/导出完整性和错误传播，再恢复 Skill 生产提示词及画像触发/检查点装配，核对连续场景与诊断。向量能力需恢复原生 embedding 服务、存储扩展、写入/更新/召回、已有资产索引和失败语义的完整链路；仅修改 strategy 为 hybrid 不会生成缺失向量。

完成这些验收后，再固定新的代码与资产快照，保持可比任务/预算重测。继续统计前台、后台、全链路 token；恢复 embedding 后，另外记录其请求和可获得的用量。此轮不扩大题单，也不开始下一轮正式实验。
