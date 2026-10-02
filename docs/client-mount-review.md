# 管理页挂载修复与验收

日期：2026-10-03。兼容目标：官方安装版 dsh 0.2.0-rc.2。

## 现象与原因

用户安装本地目录后，组件显示运行中，插件详情没有管理界面。在独立临时 DSH_HOME 中，通过官方 CLI 安装相同本地 bundle 并启动官方 web profile，复现相同现象。

`plugins.bundle.config` 是 keyed 插槽，原客户端注册误写为 `id: dsh-rsi`。安装版 `SlotCore` 对该注册明确抛出 `keyed slot "plugins.bundle.config" requires options.key`，必须使用 `key: dsh-rsi`。此前预览夹具也误按 id 校验，因此没有发现真实插槽错误。

包清单原先没有导出 `./package.json`，插件管理页未展示 description。补上导出后官方页面正确显示包描述。

## 最小修复

- `src/client/index.tsx`：将管理页注册的 id 改为 key。
- `scripts/preview-fixture.tsx`：按 keyed 插槽的 name/key 校验，阻止原错误再次被预览接受。
- `package.json`：导出 `./package.json`，供宿主读取包元数据。
- 重新构建；56 个核心文件和 10 个界面复用文件的哈希全部通过，没有修改复用算法。

## 实际验收

临时 profile 为 rsi-ui，显式暂停自动学习，不配置模型密钥。实际运行官方客户端、模块加载器、Cordis 插槽、Client RPC、Host Gateway 和本地 SQLite。

1. 修复前：组件运行，但详情缺少管理页。
2. 修复后：概览、记忆、技能、设置四个页签显示并可切换；读取真实空资产库。
3. 在设置页将每日调用上限改为 101 并保存，独立 SQLite 读取确认持久化成功，自动学习保持暂停、调用记账为 0。
4. 关闭 bundle 后管理页卸载，重新启用后恢复，设置仍为 101。

回执：[实际挂载验收](evidence/client-mount-20261003.json)。截图：[官方详情页](evidence/ui/host-mounted-20261003.png)。未使用模拟业务数据证明实际挂载；没有执行真实模型调用或任务命令。

## 用户桌面更新

当前桌面安装方式是 `link:/Users/lsmax/Coder/dsh-rsi`，重新构建已更新同一份本地代码。官方客户端模块发现结果和构建快照缓存到宿主重启，因此先完整退出并重新打开 dsh，再进入插件详情。通常无需卸载本地链接。个人桌面重启后的结果仍需用户确认。

远程 Git URL 安装、其他平台和真实模型效果不属于本次通过范围。
