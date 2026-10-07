# dsh-rsi 32对回答离线审计

仅开发，不是blind。无模型/网络调用；未改原数据、评分或学习输入。事实计数来自保存官方结果；assistant审阅分类是解释，错误因果全部未知。
事实计数：32对/64回答；官方21/32与20/32。选项不同11对：基线独对3、RSI独对1、均错7；同选项21对。全体均对18、均错9、基线独对3、RSI独对2。严格格式异常3条。
输出选项规则：最后 `<final_answer>` 后首个括号或独立a-d，大小写忽略；仅离线描述，不重算成绩。公开协议未禁止解释，因此严格尾部单选失败不等于协议违约。
源目录：[study](/Users/lsmax/Coder/dsh-rsi/.artifacts/personamem-native-v2-replication-20261006)；以下B/R引用均为该目录相对路径，JSON数组索引0基。完整哈希、qid与原回答定位见 [paired-audit.json](paired-audit.json)。

|用户/题|qid|官方B/R|选项B/R|严格B/R|不同|assistant审阅分类|
|---|---|---|---|---|---|---|
|9/1|a719edb3-a43f-4792-b820-fb45293c4e19|1/1|b/b|合格/合格|0|同选项；无可识别增量贡献|
|9/2|b502d7dc-2345-41a3-8a22-0fb9ff719c9e|0/1|c/c|尾部多文本/合格|0|同选项而官方不同；解析干扰|
|9/3|b35349e0-993b-452a-bb5e-67668833b39b|1/0|a/c|合格/合格|1|无推理的选择变更；资产适用性疑点|
|9/4|436e377a-98ba-44fc-809c-1743bbf4e033|1/1|c/c|合格/尾部多文本|0|同选项均对；严格格式异常|
|4/1|8c6f3412-d822-4131-9a51-184e6da3f476|1/1|d/d|合格/合格|0|同选项；无可识别增量贡献|
|4/2|bd39c6a3-3ebb-4f12-a9b5-f690ebdf5bca|1/1|a/a|合格/合格|0|同选项；无可识别增量贡献|
|4/3|8dbe465c-85ad-4663-a517-da7b86418cde|0/0|a/a|合格/合格|0|同选项；无可识别增量贡献|
|4/4|64e6edb1-2675-4bec-bac5-ac3cffb7a36c|1/1|c/c|合格/合格|0|同选项；无可识别增量贡献|
|12/1|194ce23e-d6d7-46f9-99b0-a0eba223a0ee|1/0|d/a|合格/合格|1|选项比较标准偏移|
|12/2|a64ba818-abee-404e-9a38-f440b74bcca7|1/1|b/b|合格/合格|0|同选项均对；题目重复选项|
|12/3|8be28bb6-049f-4735-8957-a15234c138f4|1/1|a/a|合格/合格|0|同选项；无可识别增量贡献|
|12/4|cb4799ed-15e8-4dda-a716-b81fa1d6d9da|1/0|d/a|合格/合格|1|泛化聊天与个性化桥接差异|
|14/1|a30c10c5-145a-49b0-b3d5-1479bf3c6797|1/1|a/a|合格/合格|0|同选项均对；明确跨领域Skill加载|
|14/2|e86a1aad-0117-4021-9c68-f923f4111d5f|1/1|a/a|合格/合格|0|同选项；无可识别增量贡献|
|14/3|8d52f6de-0bc5-4cac-8873-ca57060186b3|1/1|d/d|合格/尾部多文本|0|同选项均对；严格格式异常|
|14/4|4b742ee7-077d-4cce-9c27-51dfe81fcdc4|0/0|d/b|合格/合格|1|两组均错；身份与行为历史权重差异|
|3/1|9c209ff7-a6a8-48d8-ab38-e0b8aa2aaef7|1/1|d/d|合格/合格|0|同选项；无可识别增量贡献|
|3/2|945fb104-45bd-457f-a9a8-19620159e47d|0/0|d/b|合格/合格|1|两组均错；约束权重差异|
|3/3|d3767473-d464-42c1-9ead-7a61d922f120|0/0|d/b|合格/合格|1|两组均错；时间/事件解析待诊断|
|3/4|a966820a-8b42-4ec9-8427-958468f98d3b|1/1|a/a|合格/合格|0|同选项；无可识别增量贡献|
|17/1|5e856191-b76f-47ec-b5a4-f04893d8a313|0/0|b/c|合格/合格|1|两组均错；推荐权重差异|
|17/2|59eb073a-174e-4115-aa22-b40eb447b1a2|1/1|d/d|合格/合格|0|同选项均对；题干/选项错配|
|17/3|9ac098cd-a109-412a-ad1a-ad90f2f8a6d3|0/1|a/b|合格/合格|1|官方改善；跨领域偏好类比|
|17/4|f0f1c22f-ab86-4d6f-a017-6cdb7f5e88f4|1/1|d/d|合格/合格|0|同选项；无可识别增量贡献|
|19/1|0441a1ba-0d67-47a1-a910-00306910a6e3|0/0|a/c|合格/合格|1|两组均错；无RSI决策证据|
|19/2|d6d4a4e8-96c4-4b72-bdd3-204b44ec1826|1/1|b/b|合格/合格|0|同选项；无可识别增量贡献|
|19/3|fcfde00b-be10-4c52-922d-85cf7ae9f556|1/1|b/b|合格/合格|0|同选项；无可识别增量贡献|
|19/4|28200b70-034f-4c0c-bde7-21754136740d|0/0|a/b|合格/合格|1|两组均错；无RSI决策证据|
|15/1|0034a537-925f-448b-b275-eae07f3d9ae5|1/1|d/d|合格/合格|0|同选项；无可识别增量贡献|
|15/2|4b803069-7679-411e-8310-d885e6ed1e7d|0/0|b/b|合格/合格|0|同选项均对；阶段泛化风险|
|15/3|d0b826d3-9805-416c-a8a8-343ffe1c9098|0/0|c/b|合格/合格|1|两组均错；风格权重与泛化回应差异|
|15/4|29c557de-15e3-43c5-b416-de5d4f1845e5|1/1|d/d|合格/合格|0|同选项；无可识别增量贡献|

## 11对不同选项：assistant审阅解释（非因果结论）
- 用户9 Q3：基线以收藏杂乱、卖海报及极简倾向选a；RSI只选c。已保存注释证明重复读画像、加载电影推荐Skill；是否适用于本题仍需核对；缺少规则到选项推理，不能归因错误。 Skill交付1次；源：persona-9-{baseline,rsi}/state/pilot/persona-9/answers.json，数组索引2；annotations/persona-9.json。
- 用户12 Q1：基线引用ADR枯燥/渴望真实案例选d；RSI认为a更详细、d太短，未解释该历史约束。固定召回含过去枯燥与后来课程改善；这不证明资产导致偏移。 Skill交付0次；源：persona-12-{baseline,rsi}/state/pilot/persona-12/answers.json，数组索引0；annotations/persona-12.json。
- 用户12 Q4：基线最终用法律/策略兴趣桥接历史拼图选d；RSI先自由回应、选a。闲聊Skill确实交付，但无显式规则引用，不能把错误归于简短/共情规则，也不能认定该聊天任务不适用。 Skill交付1次；源：persona-12-{baseline,rsi}/state/pilot/persona-12/answers.json，数组索引3；annotations/persona-12.json。
- 用户14 Q4：基线显式讨论身份画像与音乐史冲突，偏重文化身份/尤克里里选d；RSI只选b。代码Skill跨域加载发生在Q1且Q1两组均对，不可移植为Q4错因。 Skill交付0次；源：persona-14-{baseline,rsi}/state/pilot/persona-14/answers.json，数组索引3；annotations/persona-14.json。
- 用户3 Q2：基线偏重新颖及文化身份选d；RSI明确引用Memory/Scene与历史，偏重放松、旅行疲惫与陶艺疗愈选b。旅行条目遗漏后续疲惫可观察，但RSI推理实际考虑疲惫；不是漏记导致该错误的证据。 Skill交付0次；源：persona-3-{baseline,rsi}/state/pilot/persona-3/answers.json，数组索引1；annotations/persona-3.json。
- 用户3 Q3：基线显式区分首次卡拉OK焦虑与较晚正向经历，最终选d；RSI只选b。两次体验不能合并成单一永久偏好；没有RSI决策链，因果未知。 Skill交付0次；源：persona-3-{baseline,rsi}/state/pilot/persona-3/answers.json，数组索引2；annotations/persona-3.json。
- 用户17 Q1：基线偏重自由与小团体选b；RSI自然搜索后区分阅读马拉松正向与后来压力，以深度交流选c。历史阶段已在RSI推理体现；Cosplay态度省略属资产问题，尚不能归因本题。 Skill交付0次；源：persona-17-{baseline,rsi}/state/pilot/persona-17/answers.json，数组索引0；annotations/persona-17.json。
- 用户17 Q3：基线仅选a；RSI以近期自由/低压力倾向以及阅读/电影历史类比绘画自主活动选b。两组都有完整历史，未证明增量Memory贡献，且无Skill自然加载。 Skill交付0次；源：persona-17-{baseline,rsi}/state/pilot/persona-17/answers.json，数组索引2；annotations/persona-17.json。
- 用户19 Q1：基线权衡私密日记、艺术挫折与旅行vlog，选a；RSI加载多话题聊天Skill后只选c。一般策略类比与正文交付可观察，不足以证明规则导致错误。 Skill交付1次；源：persona-19-{baseline,rsi}/state/pilot/persona-19/answers.json，数组索引0；annotations/persona-19.json。
- 用户19 Q4：基线用远离网红/偏好本地真实体验选a；RSI加载旅行聊天Skill后只选b。Skill投资挑战例证归属错误在另一话题，不能据此认定它导致本题文化体验错答。 Skill交付1次；源：persona-19-{baseline,rsi}/state/pilot/persona-19/answers.json，数组索引3；annotations/persona-19.json。
- 用户15 Q3：基线较长推理先质疑c跳跃，最终因历史助手长回应风格选c；RSI加载理财Skill后只选b。投资社区阶段在Skill遗漏属已观察质量问题，尚无本题纪录片选择因果证据。 Skill交付1次；源：persona-15-{baseline,rsi}/state/pilot/persona-15/answers.json，数组索引2；annotations/persona-15.json。

## 三损失与最小开发诊断
深读实际交付/原历史0基索引见 [three-loss-focus.json](three-loss-focus.json)。用户9 Q3同时交付减杂乱事件与仍偏重收藏的global画像；先固定其余输入，仅修画像阶段或撤去该画像。错误因果仍未知，不能保证救回答案。用户12 Q1原资产保留ADR前后阶段，但真实案例诉求被概括，实际理由为a更详细/d更短，需单独诊断决策标准；Q4相关检出片段含负向桌游，不能据此认定所有交付遗漏正向场次。
其他最小控制：用户9 Q2解析异常；用户14 Q1代码Skill跨域加载但答对；用户15投资社区Skill阶段遗漏与Memory阶段保留。都仅开发，不宣称blind。
评分器最小建议：标记存在时仅解析明确选项，禁止任意正文单字母fallback；明确最后标记、leading choice、额外正文与歧义规则。虚拟标签控制及原异常响应回归，版本记录，新旧结果分开；本次不改实现。
标准答案隔离：本审计未读取评分标准答案，未生成含标准答案的学习输入；官方结果仅用于离线分类。审阅解释由gpt-6.1-sol assistant给出，并非人类人工标注。
特别边界：用户9 Q2同c却官方不同；用户9 Q4和14 Q3严格异常但官方对。用户12 Q2重复选项，用户17 Q2绘画题/阅读选项错配。事实正确、阶段忠实、适用性、消费与因果贡献分别判断。
