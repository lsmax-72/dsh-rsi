# PersonaMem 小型预演准备

来源：[官方仓库](https://github.com/bowen-upenn/PersonaMem)、[PersonaMem-v1 数据](https://huggingface.co/datasets/bowen-upenn/PersonaMem-v1)，使用官方 32k 文件。固定数据与源码修订见 [来源回执](evidence/personamem-provenance-20261004.json)。原始数据、答案、源码及 MIT 许可在评分侧独立目录；没有加入任务镜像或个人资产。

当前只完成准备与导入夹具，尚未派发 PersonaMem 的真实模型请求。开发阶段首位用户、相同 shared_context_id 和相同截止点的两道题已准备；两个条件均使用原文 history[:end_index]，不删除基线历史。182 条消息含 5 条 system、102 条 user、75 条 assistant，全文 152,394 字符。题目只含公开问句和四个选项，correct_answer 另存评分目录。见 [准备回执](evidence/personamem-preparation-20261004.json)。

评分函数从固定修订 inference_standalone_openai.py 的 Evaluation.extract_answer 原样抽取，未运行其推理客户端或加载 API token。正确、错误和多选歧义三个控制通过；不是效果成绩。

原生导入使用官方消息构造器与 Session.append 的返回事件，再经正式 Agent seed/persistence 接入。历史 seed 不会重发事件，因此导入完成后调用既有 turn/end 观察入口，进入同一个持久日志读取、原生调度及 L0 记录流程。没有手写答案记忆、直接插数据库或另起提炼算法。最初误用不存在的 session.events 属性、缺少 skills 服务及直接 Session 创建不持久化的问题已修正；不能把缺失回执/空历史当作通过。

[原生导入夹具](evidence/personamem-import-20261004.json)逐字重建全部历史角色和正文；177 条用户/助手进入 L0，system 历史不伪装成用户偏好。原始 assistant 明确标为 dataset/PersonaMem-v1，并非本轮 qwen 生成；关闭的历史导入轮次不代表实验任务成功。夹具调用原生提炼但返回固定响应，真实模型调用为 0。

待验证：求解请求中的历史仍逐字存在（特别是多个 system 节点，防止宿主重新渲染覆盖）、qwen 完整请求容量、真实历史学习与两类资产消费、全链路成本。服务报告 max_model_len=262144，只是容量声明，不能替代实际请求。不同 persona 使用独立插件数据目录，避免 global 资产混合；多道题的准确率与区间按用户分组。

开发用户不进入后续独立评价用户。通过预演后再固定最终用户、题单、顺序及预算；本次两题不是最终评测方案。
