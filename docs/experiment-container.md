# dsh 实验容器接入

更新：2026-10-03。当前验收仅覆盖断网固定响应夹具，不代表真实任务能力或正式 benchmark 效果。

## 方案和复用

整个官方 dsh 与 dsh-rsi 放在 Linux 容器内。沿用官方 Agent、LLM、工具注册、会话持久化、Bash/PTY、子进程、文件和 PTC；插件的冻结记忆与技能核心保持不变。新增脚本只负责 Docker 配置与检查、安装官方包、驱动固定模型响应和收集结果。

- `scripts/container/Dockerfile`：固定 Node 镜像 digest、官方 dsh 版本与插件 npm lock；源码副本构建，无个人数据。
- `scripts/probe-container.py`：临时目录、真实宿主标记文件、配置审查、容器生命周期与结果汇总。
- `scripts/isolation-probe.mjs`：用官方 Agent 接受固定响应，真正派发官方工具；PTC 嵌套调用另外记录，不与顶层调用混计。
- `scripts/probe-runtime.py`：直接复用已有完整原生资产闭环与恢复检查。

容器内固定 `cwd=/workspace`、独立 DSH_HOME 与资产库，两种 Bash 分别运行在全新容器。sdk-minimal 是官方服务组合起点，容器提供外部隔离；该 profile 的 `danger-full-access` 本身不提供隔离。文件工具使用官方 local provider，其路径解析默认值也不构成边界。

## 已验收的入口

| 入口 | 实际检查 |
| --- | --- |
| 文件 `write/read/edit` | 实际读写与内容修改；宿主标记不存在；镜像修改报 EROFS |
| `glob/grep` | 官方工具通过子进程运行 ripgrep，检索容器内真实文件 |
| 普通 Bash | 官方 dsh-bash-local 与 tool-bash；真实 Node 与 Python 子进程 |
| 持久 Bash | 官方 terminal-bash 与 tool-bash-persistent；相同边界检查 |
| `run_code` | 官方 Node PTC 进程；直接文件与子进程操作、外网尝试、嵌套官方 read |
| 原生资产 | Linux 下完整既有闭环夹具及独立进程恢复 |

本次暴露的工具目录记录在回执中。没有加载 Web、MCP、子 Agent、LSP 或其他实验扩展，不将此结果外推为所有未来插件都已验收。真实任务运行必须冻结同一工具目录；新增任何可执行入口需要重新审查。

## Docker 边界

运行时断网、非 root UID 1000、只读镜像、移除所有 capabilities、no-new-privileges、独立 PID/IPC，无宿主目录或 Docker socket 挂载。可写位置只有临时 `/workspace`、`/state`、`/tmp`，上限分别为 64/256/128 MiB；2 CPU、2 GiB 内存、256 进程。

官方原生模块加载器会把共享库复制到 `/tmp` 再加载。Docker tmpfs 默认 noexec 导致 native binding 报错，因此该临时目录显式设置 `exec`；镜像继续只读，不增加宿主访问。官方 subprocess 安装脚本用于恢复 PTY spawn-helper 的可执行位，没有修改官方实现。

资产、日志和任务同处容器，当前任务工具可以接触自己的实验资产；这是容器内数据边界，不能声称资产对任务进程不可见。宿主个人资产完全不挂载。后续如测量前序经验迁移，快照与可见范围必须另行固定。

## 复现

需要 Docker，可执行 `npm run test:container -- --output docs/evidence/container-isolation-20261003.json`。准备阶段下载公开镜像与官方包；执行阶段断网。脚本只删除自己创建的容器和临时目录，保留构建镜像供后续复用，不修改其他 Docker 资源。

官方 CLI 版本固定，当前官方包的传递依赖由本次镜像固化；在正式实验前还需冻结宿主 npm lock、任务镜像与工具目录。当前只记录不可变 imageId，不宣称跨日期重新安装的传递依赖完全一致。

## 下一步与停止条件

先设置只允许声明模型服务的 egress，再验证 qwen3.8-27b 的工具调用和官方判分器；之后少量真实任务试跑，保留轨迹、资产形成/消费与成本记录。正式配对 benchmark 前停止并报告。固定响应检查不能替代真实模型结果。

## 模型服务访问边界与真实工具兼容性（2026-10-03）

已通过内部 Docker network + 固定上游模型网关检查。任务容器仅连接 internal network；网关另外连接出站网络，没有发布端口，不挂载宿主目录或 socket。网关只转发声明模型的 `/v1/models` 和 `/v1/chat/completions`，拒绝其他 URL、模型和重定向，限制请求数量、请求体大小和输出 token 上限。task 侧通用网页访问与外网 TCP 失败。AMD64 和 Ubuntu 官方任务基础环境的真实工具检查也已通过。

`qwen / qwen3.8-27b` 使用官方 dsh-llm-pi-ai 的 `openai-completions` 协议，经 3 次真实请求完成 `write → read`。公开模型目录返回 `max_model_len=262144`，试跑容量据此固定为 262144。当前服务不要求转发密钥；任务容器的 QWEN_API_KEY 为非秘密占位符 EMPTY，没有读取或复制个人凭据。

模型 API 对容器内所有进程可见，Bash/PTC 也可能请求该 API；不能声称只有 LLM adapter 拥有联网权限。固定上游网关不提供网页搜索或任意 HTTP 代理，网关请求上限同时覆盖绕过 Agent 直接访问的推理成本。事件请求数与网关计数还需在真实任务结束后核对。

复现：先构建 `test:container` 的镜像，再运行 `npm run test:model -- --upstream <声明的模型服务地址/v1> --output <回执路径>`。地址不写入仓库；该命令会进行真实模型推理。见 [兼容性回执](evidence/model-compatibility-20261003.json)。本次真实任务仅为两题接入试跑，正式配对 benchmark 前停止。
