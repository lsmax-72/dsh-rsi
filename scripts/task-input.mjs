// Identical execution guidance remains model-visible in both arms, with its own provenance.
export const taskProtocol='修复以下 Django 仓库问题。工作区为 /workspace，测试环境已离线准备，python 来自官方 testbed 环境。先验证环境，再运行聚焦测试，保留失败原因。禁止联网检索答案。完成后用中文说明修改、测试及局限。连续任务中，本组先前执行的原始会话日志位于 /state/home/sessions，可用文件读取工具查阅。';

/** Producer guidance names only verified restored task logs; the current log is never history. */
export function taskHistoryGuidance(currentSessionId, priorTaskLogs=[]) {
  if(!/^pilot-[a-zA-Z0-9_-]+$/.test(currentSessionId))throw new Error('Invalid current task session ID');
  for(const log of priorTaskLogs) {
    if(!/^pilot-django__django-\d+-task$/.test(log.sessionId) || !/^--workspace--\/pilot-django__django-\d+-task\/session\.v4\.jsonl$/.test(log.relativePath) || log.relativePath!==`--workspace--/${log.sessionId}/session.v4.jsonl` || log.sessionId===currentSessionId)throw new Error('Invalid prior task log target');
  }
  const available=priorTaskLogs.length?priorTaskLogs.map(log=>`- /state/home/sessions/${log.relativePath}`).join('\n'):'本组没有先前任务日志；无需寻找历史。';
  return `当前会话是 ${currentSessionId}，其日志不是先前任务历史。以下仅列出本组已关闭并原样恢复的任务日志（可选查阅，不要求逐个扫描）：\n${available}\n日志是原生 v4 JSONL 事件流：type=user/message 的 data.content 是用户内容；type=assistant/message 的 data.message.content 是助手内容；type=tool/result 的 data.message.content 是工具输出。content 是文本块数组，文本在 text 字段。它不是 type=message/顶层 role 的扁平聊天格式。无需读取当前会话来寻找先前经验。`;
}
