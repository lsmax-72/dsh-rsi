/** Native custom strategy changes fact selection, preserving its file/tool protocols. */
export function profileSourceStrategy(layer: 'l2' | 'l3') {
  return {
    source: 'instance' as const, layer, memory_prompt_id: 'dsh-rsi-source-grounding', version: 1,
    prompt: `仅归纳来源明确支持的用户事实、偏好、变化及例外。按原生 Markdown 协议保留结构；没有依据的洞察栏目留空，不为填满模板补充故事。
不要从收藏品、作品角色、消费方式或助手的回应推断用户性别、人格、触感偏好、经济/空间动机；不添加来源未说明的原因。既有派生 Scene/Persona 的推测不是独立证据，本次不要把它们继续归纳为事实或行为规则。
逐项保留过去与当前的区别、接受范围、例外和否定词的作用范围。“不是只收藏数字版”不等于“拒绝数字版”；处理重复物品不等于整体偏好改变。
输入 created_at、文件 META 时间和当前时间仅是记录/处理元数据。无来源日期时只写相对先后或日期未知；来源明确给出的日期才可作为活动时间。保留原生文件 META 的处理时间语义。
正文长度与有依据的事实数量相称；优先简洁明确的事实，不复述宽泛人格、互动风格或无依据的动机。`,
  };
}
