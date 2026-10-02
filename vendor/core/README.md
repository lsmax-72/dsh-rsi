# 记忆与技能核心子集

本目录固定复用版本 `e09899c2136fb6bc27ecc68505e32bdb637cdfa8` 的运行时依赖子集。`manifest.json` 记录每个源码文件的 SHA-256；构建前自动核对。源码保持原有提炼、写入、技能版本与存储逻辑，没有另写一套提炼器。

这是运行时依赖子集，尚未作为独立、类型完整的公共 TypeScript 库发布。当前提供 esbuild 构建入口，未宣称通过全库类型检查。

## 构建适配边界

- 原宿主模型调用器替换为强制报错的入口：必须注入 dsh runner，不能回落到其他模型 HTTP 路径。
- 远端观测后端工厂只接到已有的默认 NoopObservabilityBackend，不加载远端 SDK；模型输入、输出、工具与用量由 dsh 日志记录。
- 观测日志门面关闭原有 `/data/log` 写入；提炼业务日志仍使用调用方 logger。

适配文件放在项目根目录 `adapters/`，没有改动被固定的核心源码。必要版权与 MIT 许可保留在 `LICENSE`。

## 已运行与未运行

已通过安装版 dsh 运行 L1 提炼写入、SkillExtractor 工具写入、SkillCore 版本管理及本地存储。MemoryPipelineManager 已导出，尚未接入 dsh 的轮次事件；L0、L2/L3、完整召回、记忆检索索引、跨轮去重、向量检索及 Skill 自动队列未接通，不能把当前子集视为完整 Chat Memory 产品。
