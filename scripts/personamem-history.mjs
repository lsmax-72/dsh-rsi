import assert from 'node:assert/strict';
import {createAssistantMessage,createSystemMessage,createUserMessage} from '@deepseek-ai/dsh-llm';

/** Import public history as native events; this performs no model dispatch or asset write. */
export function appendPersonaHistory(session,history) {
  const events=[],append=(...args)=>{const event=session.append(...args);events.push(event);return event;};
  append('turn/start',{turn:1});
  append('step/start',{turn:1,step:1});
  const messageIds=[];
  for(const [index,row] of history.entries()){
    assert.ok(['system','user','assistant'].includes(row.role));assert.equal(typeof row.content,'string');
    const content=[{type:'text',text:row.content}];let message;
    if(row.role==='user'){
      message=createUserMessage({content,source:{kind:'user',dataset:'PersonaMem-v1',datasetIndex:index}});
      append('user/message',message,{surfaceOp:'append'});
    }else if(row.role==='assistant'){
      // Dataset responses are imported evidence, never attributed to the current qwen route.
      message=createAssistantMessage({content,source:{provider:'dataset',model:'PersonaMem-v1'}});
      append('assistant/message',{turn:1,step:1,message,stream:[]},{surfaceOp:'append'});
    }else{
      message=createSystemMessage(row.content);
      append('system/message',{turn:1,step:1,message},{surfaceOp:'append'});
    }
    messageIds.push(message.id);
  }
  append('step/end',{turn:1,step:1});
  // This closes an import operation, not a claim that an experimental task succeeded.
  append('turn/end',{turn:1,reason:{kind:'completed'}});
  const reconstructed=[...session.deriveMessages()].map(m=>({role:m.role,content:m.content.map(b=>b.text).join('')}));
  assert.deepEqual(reconstructed,history);
  return {events,messageIds,reconstructed};
}
