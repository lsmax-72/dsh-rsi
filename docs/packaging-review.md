# 安装与发布审查

更新：2026-10-02。本次仅改构建/打包、验证脚本和文档；记忆与技能核心算法未修改。

## 源码构建

`lib/` 继续保持为忽略的生成目录。`package.json` 增加 `prepare: npm run build`，源码目录执行普通 `npm ci` / `npm install`、`npm pack` 时生成构建产物，tarball 通过既有 `files` 清单携带 `lib/`。不需要同时再加一次相同的 `prepack` 构建。

[npm 官方生命周期说明](https://docs.npmjs.com/cli/v11/using-npm/scripts/)还规定：Git 依赖含 `prepare` 时，先安装其运行依赖与开发依赖，再构建、打包和安装。当前验证覆盖本地全新源码目录与 tarball，尚未验证远程 Git URL 经 dsh 安装器的完整路径。禁用生命周期脚本的源码安装仍需显式构建。

## React 核查

审查前的客户端产物已分别 `require("react")` 和 `require("react/jsx-runtime")`，没有嵌入 React 源码。[esbuild 的 package external 规则](https://esbuild.github.io/api/#external)会覆盖包内子路径；本机最小构建探针也验证了此行为。因此不能据原配置断言已经存在两份 React。

为便于审查，配置现在显式写为 `external: ['react', 'react/jsx-runtime']`，并用构建 metafile 阻止 React 源码被内嵌。安装包探针再检查客户端外部模块引用。渲染与 Hook 的交互仍由浏览器检查；没有用 Node 的 DOM 模拟器代替页面验收。

## 中文分词依赖

后端构建使用 `packages: 'external'`。`chunk-RCU25K3F.js` 中的是核心代码调用 `require("@node-rs/jieba")` / `require("@node-rs/jieba/dict")`，不是将 jieba 包或其二进制打进 chunk。

jieba 需要平台原生二进制，通过依赖包的 `optionalDependencies` 选择。当前本机为 macOS ARM64，已确认 `.node` 被实际加载，且中文分词成功。生产安装探针通过核心的 `buildFtsQuery` 检查二进制确实加载，避免把缺失二进制后的原生回退当成兼容验证成功。

新增 `.github/workflows/package.yml` 对 Linux/macOS/Windows 配置 Node 24 安装检查。配置尚未提交或推送，CI 未运行；不能声称三个平台都已通过，也不能由 OS 名称覆盖所有 CPU/libc 组合。

## 发布状态

- 保持 `private: true`，当前是开发包；本地 `npm pack` 不受该字段阻止，正式 npm 发布前必须解除。
- 只读查询公共 npm registry 的 `dsh-rsi` 返回 E404。目前没有查到公开包；这不证明名称已被保留或当前账号有发布权。
- 包名及 scope 在正式发布前按实际 npm 账号权限确认；若改名，需要同步客户端模块 ID 与 RPC contribution 的 package 字段，不能只改 `package.json`。
- 桌面安装与页面挂载仍待验收；打包探针不代替 dsh 安装器和真实 benchmark。

## 重现验证

```sh
npm run test:package -- --output docs/evidence/package-20261002.json
```

探针在临时目录复制不含 `lib/` 和 `node_modules/` 的源码，执行安装生命周期；生成 tarball 后在另一目录只装生产依赖、禁止消费者构建脚本；加载服务端导出、实际中文 FTS 分词及客户端外部引用。结束清理临时目录，不调用真实模型或任务工具。
