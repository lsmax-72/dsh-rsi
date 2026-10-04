# PersonaMem 小型预演准备

来源：[官方仓库](https://github.com/bowen-upenn/PersonaMem)、[PersonaMem-v1 数据](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v1)，使用官方 32k 文件。固定数据与源码修订见 [来源回执](evidence/personamem-provenance-20261004.json)。原始数据、答案、源码及 MIT 许可在评分侧独立目录；没有加入任务镜像或个人资产。

当前只完成准备与导入夹具，尚未派发 PersonaMem 的真实模型请求。开发阶段首位用户、相同 shared_context_id 和相同截止点的两道题已准备；两个条件均使用原文 history[:end_index]，不删除基线历史。182 条消息含 5 条 system、102 条 user、75 条 assistant，全文 152,394 字符。题目只含公开问句和四个选项，correct_answer 另存评分目录。见 [准备回执](evidence/personamem-preparation-20261004.json)。

评分函数从固定修订 inference_standalone_openai.py 的 Evaluation.extract_answer 原样抽取，未运行其推理客户端或加载 API token。正确、错误和多选歧义三个控制通过；不是效果成绩。

原生导入使用官方消息构造器与 Session.append 的返回事件，再经正式 Agent seed/persistence 接入。历史 seed 不会重发事件，因此导入完成后调用既有 turn/end 观察入口，进入同一个持久日志读取、原生调度及 L0 记录流程。没有手写答案记忆、直接插数据库或另起提炼算法。最初误用不存在的 session.events 属性、缺少 skills 服务及直接 Session 创建不持久化的问题已修正；不能把缺失回执/空历史当作通过。

[原生导入夹具](evidence/personamem-import-20261004.json)逐字重建全部历史角色和正文；177 条用户/助手进入 L0，system 历史不伪装成用户偏好。原始 assistant 明确标为 dataset/PersonaMem-v1，并非本轮 qwen 生成；关闭的历史导入轮次不代表实验任务成功。夹具调用原生提炼但返回固定响应，真实模型调用为 0。

求解历史夹具发现普通 Agent 会清除/重写原始 5 个 system 节点（原索引 0、47、78、109、154）。必要适配：原有 user/assistant 仍经正式 seed 保留；5 条 system 原文以标明历史索引的 producer 消息补入，避免当作本轮宿主 system 指令。两组采用相同投影，不删减基线信息。角色投影发生改变，因此不声称实际求解请求与官方原始 OpenAI 请求角色完全等价。全部历史原文逐字出现在实际请求中，回执：[历史消费](evidence/personamem-history-consumption-20261004.json)。

待验证：qwen 完整请求容量、真实历史学习与两类资产消费、全链路成本。服务报告 max_model_len=262144，只是容量声明，不能替代实际请求。不同 persona 使用独立插件数据目录，避免 global 资产混合；多道题的准确率与区间按用户分组。

开发用户不进入后续独立评价用户。通过预演后再固定最终用户、题单、顺序及预算；本次两题不是最终评测方案。

## 真实预演计划

[运行前清单](evidence/personamem-pilot-plan-20261004.json)：同一用户两题，两组都完整保留历史与同一角色投影；每题最多 6 次前台、每次 4096 输出 token、120 秒。RSI 历史学习最多 12 次后台、900 秒窗口，要求队列完成并至少 45 秒无后台调用后才冻结学习并作答。历史单次原生导入，未追加人工记忆或指定 Skill。每题独立 seed 同一截止点，不带前一道题答案。失败保留且单独分类，不扩大预算补分。

基线先运行以验证实际完整请求容量；随后 RSI 组。全程复用只读 Docker 隔离运行器，移除本阶段不需要的 shell/文件工具；只向既有 qwen 服务发送公开历史与隔离派生资产。官方答案及评分器没有复制到镜像。固定响应夹具属于运行器验证；RSI 短历史夹具不证明真实 32k 容量或效果。

[隔离运行器夹具](evidence/personamem-runner-fixtures-20261004.json)通过：完整历史基线 2 次固定响应、短历史 RSI 2 次提炼加 2 次固定响应，真实请求为 0。保留初始准备态 Session flush 错误及移除 PTC 后未切换 native 工具模式的错误。两组现在明确使用相同 native 工具模式；不把这些运行器失败算模型任务失败。

公开题目与输出格式协议已分字段，协议经 producer 消息持久化，检索仅使用问题及选项；[新的公开输入回执](evidence/personamem-preparation-separated-protocol-20261004.json)记录新哈希，题目、历史和答案保持相同。

## 首次真实预演：容量通过，导入轮次需修正

[首次结果](evidence/personamem-pilot-first-outcome-20261004.json)：基线完整历史两题均正常停止，输入分别 29,183/29,388 token，合计 59,347。RSI 原生 L0 完整存入 177 条；L1 输入 39,337、输出 4096、总 43,433 token，返回 max-tokens。实际输出仍在列举同一场景的来源 UUID，尚无完整资产记录。两组本次已知总 102,780 token，RSI 未答题，不能记作 0% 准确率或上下文容量失败。

问题是宿主导入将全部历史包装为一个人工大轮次。修正只恢复原文 system 分段索引 0/47/78/109/154，每段使用正式原生 turn/start、消息事件及 turn/end；历史全部角色、顺序、正文保持不变。原生提炼、检查点与调度继续按实际轮次处理，没有摘要、手写记忆或另写批处理算法。旧单轮次记录保留。分段夹具先验收，重新运行须另记方法修订及原预算，不能覆盖失败或悄悄增加额度。

分段导入进一步暴露两个宿主边界：活动任务期间后续通知被原生队列去重时，适配返回值缺失 hasMore，导致后续轮次不再调度；批量导入不同轮次的事件共享毫秒，原生严格 timestamp 游标会漏掉部分 L0。分别修复为返回原生 backlog 信号（仍由原生 idle 计时器处理），以及导入分段间等待真实时钟跨毫秒（不伪造源时间、不改原生过滤算法）。数据不含真实日期，事件时间仅代表导入时间。

[分段验收](evidence/personamem-segmented-import-20261004.json)：全部 182 条历史逐字重建、177 条 L0、5 个原生工作全部完成，10 次后台夹具调用加 2 次前台夹具调用，真实请求 0。真实场景/画像和 Skill 工具循环还需额外调用；原单轮预演的 12 次后台额度不能视作已验证适合五轮全链路。

下一次真实修正预演的 [具体方案](evidence/personamem-corrected-pilot-proposal-20261004.json)仍使用同一两题，不进入正式评测。提议单独最多 30 次后台、1800 秒学习窗口，输出上限 4096/题前台 6 次/120 秒不变；失败与额外费用单独保留，不覆盖原预算或结果。因用户明确要求不擅自扩大固定题单/预算，新增调用额度须确认后执行。
