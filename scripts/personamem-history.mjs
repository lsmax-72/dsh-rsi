import assert from 'node:assert/strict';
import {createAssistantMessage,createSystemMessage,createUserMessage} from '@deepseek-ai/dsh-llm';

// Shared producer context for both arms. The source dataset has no message timestamps.
export const importedHistoryTimeNote='Original source message times are unknown. Native session event times are import/recording metadata only; do not use them or the current runtime date as calendar anchors for events in the historical text. Preserve dates explicitly present in source prose. Otherwise keep relative time wording without inferring an absolute date.';

export function personaHistoryContext(history) {
  const backgrounds=history.map((row,index)=>({...row,index})).filter(row=>row.role==='system');
  return importedHistoryTimeNote+'\n\nOriginal system backgrounds in this public history, in historical order (indices refer to the imported log):\n'
    +backgrounds.map(row=>`[Historical system at original index ${row.index}]\n${row.content}`).join('\n\n');
}

/** Import public history as native events; this performs no model dispatch or asset write. */
export async function appendPersonaHistory(session,history,{systemBoundaries=false}={}) {
  const events=[],append=(...args)=>{const event=session.append(...args);events.push(event);return event;};
  let turn=1;const turnBoundaries=[0];
  append('turn/start',{turn});
  append('step/start',{turn,step:1});
  const messageIds=[];
  for(const [index,row] of history.entries()){
    if(systemBoundaries&&index>0&&row.role==='system'){
      // Public system boundaries delimit original history segments; never invent summaries or discard text.
      append('step/end',{turn,step:1});append('turn/end',{turn,reason:{kind:'completed'}});
      // Native capture cursors use strict epoch-ms ordering across turns. Imported data has no timestamps.
      // Wait for a real clock tick rather than forging event times or bypassing the native cursor.
      const previousTime=events.at(-1).time;
      while(Date.now()<=previousTime)await new Promise(resolve=>setTimeout(resolve,1));
      turn++;turnBoundaries.push(index);append('turn/start',{turn});append('step/start',{turn,step:1});
    }
    assert.ok(['system','user','assistant'].includes(row.role));assert.equal(typeof row.content,'string');
    // Event time remains the real import clock; the dataset supplies no historical message time.
    const content=[{type:'text',text:row.content}];let message;
    if(row.role==='user'){
      message=createUserMessage({content,source:{kind:'user',dataset:'PersonaMem-v1',datasetIndex:index,timestampKind:'imported-unknown'}});
      append('user/message',message,{surfaceOp:'append'});
    }else if(row.role==='assistant'){
      // Dataset responses are imported evidence, never attributed to the current qwen route.
      message=createAssistantMessage({content,source:{provider:'dataset',model:'PersonaMem-v1',timestampKind:'imported-unknown'}});
      append('assistant/message',{turn,step:1,message,stream:[]},{surfaceOp:'append'});
    }else{
      message=createSystemMessage(row.content);
      append('system/message',{turn,step:1,message},{surfaceOp:'append'});
    }
    messageIds.push(message.id);
  }
  append('step/end',{turn,step:1});
  // This closes an import operation, not a claim that an experimental task succeeded.
  append('turn/end',{turn,reason:{kind:'completed'}});
  const reconstructed=[...session.deriveMessages()].map(m=>({role:m.role,content:m.content.map(b=>b.text).join('')}));
  assert.deepEqual(reconstructed,history);
  return {events,messageIds,reconstructed,turnBoundaries};
}
