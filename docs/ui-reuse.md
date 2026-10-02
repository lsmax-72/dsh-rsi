# 管理页面复用记录

## 采用的边界

管理页面直接采用已有资产工作台组件，而不是根据截图重新实现同样的控件。固定修订与逐文件 SHA-256 见 `vendor/panel/manifest.json`。构建同时校验运行时核心和管理页组件。

| 组件 | 复用方式 | 必要适配 |
| --- | --- | --- |
| `AssetSplitLayout` | 原文件及 CSS 原样保留 | 分栏标签连接本地中文文案；使用独立的宽度存储 key |
| `AssetListPanel` 及列表项组件 | 原文件及 CSS 原样保留 | 工作区/通用范围作为列表数据，接入插件 RPC |
| `AssetPageHeader` | 原文件及 CSS 原样保留 | Card/Body 容器使用轻量宿主包装，省去整个外部组件库 |
| `MarkdownView` | 原文件及 CSS 原样保留 | 通过 CSS token 映射对齐宿主；正文排版适配 |
| `buildFileTree` / `FileTreeView` | 从既有详情页直接提取 | 只增加 export，函数体不修改；对应样式直接提取 |

颜色变量、宿主容器高度和页签范围由 `src/client/styles.ts` 适配。没有引入既有页面的登录、团队/Agent 选择、用户权限或独立 HTTP 服务。整页包含这些服务耦合，因此复用其独立组件，由插件负责薄数据绑定。

## 后端接口

分层管理接口只拼装现有结果：

- L0：原生 `countL0` / `queryL0Paginated`，每页 50 条。
- L1：原生记忆读取及已有来源信息。
- L2：原生 `readSceneIndex` / `parseSceneBlock` 和原生 profile 存储读取。
- L3：同一 profile 存储的 `persona.md`。
- 技能正文和版本：原生 `SkillCore.get` / `listVersions`。
- 编辑：原生 `SkillCore.update` 的 `expected_version` 乐观锁。
- 资源：原生 `SkillCore.readFile`，按版本 manifest 校验；预览上限 1 MB。

附件以原生 base64 编码传回客户端，文本/二进制展示判断留在客户端；后端没有另写文件格式处理。原有 56 个运行时源码文件仍保持原样，提炼、检索、资源与版本算法没有为了页面改写。

## 当前功能与验证范围

记忆页采用范围列表 + L0/L1/L2/L3 详情。L0 显示对话、分页与本页筛选；L1 展示经验、来源和纠正入口；L2 折叠场景正文；L3 展示画像。L2/L3 的管理编辑尚未开放。

技能页采用搜索/范围筛选 + 详情；正文为 Markdown，资源为目录树。保留正文编辑、禁用、语言转换、通用复制和历史回退。资源只读预览，文件创建/修改/删除尚未开放。

`http://127.0.0.1:45177/` 是构建产物的交互夹具，数据均为模拟数据，不能作为真实任务效果证据。宿主管理接口另通过已安装 dsh 的真实 Gateway 与原生存储验证。2026-10-03 已通过独立官方 web profile 的实际界面挂载、RPC 设置保存和启停验收；个人桌面更新后的结果待确认。见 [挂载修复记录](client-mount-review.md)。

验证记录：[管理页交互回执](evidence/ui-reuse-20261002.json)、[原生运行时回执](evidence/runtime-phase2.json)。截图为模拟数据界面：[记忆页](evidence/ui/memory.png)、[技能页](evidence/ui/skills.png)。
