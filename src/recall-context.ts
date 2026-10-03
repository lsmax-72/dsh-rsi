import {join} from 'node:path';

/** Preserve native asset text; only the host's tool guide needs name adaptation. */
export function recallToolGuide(result:any) {
  const guide=result?.appendSystemContext?.match(/<memory-tools-guide>[\s\S]*?<\/memory-tools-guide>/)?.[0];
  if(!guide)return '';
  return guide.replaceAll('tdai_memory_search','rsi_memory_search').replaceAll('tdai_conversation_search','rsi_conversation_search').replaceAll('read_file','rsi_profile_read')+'\n读取 profile 时，rsi_profile_read 的 query 为给出的完整文件路径。';
}

/** Host budget applies to complete native blocks, with paths for oversized profiles. */
export function fitRecallScope(result:any,scope:string,profileDir:string,budget:number,allowProfiles=true) {
  const parts:string[]=[],memories:any[]=[];
  const open=`<memory-scope scope="${scope}">\n`,close='\n</memory-scope>';
  let remaining=budget-open.length-close.length;
  const add=(text:string)=>{const size=text.length+(parts.length?1:0);if(size>remaining)return false;parts.push(text);remaining-=size;return true;};
  if(result?.prependContext && add(result.prependContext))memories.push(...(result.recalledL1Memories ?? []));
  if(allowProfiles)for(const match of result?.appendSystemContext?.matchAll(/<(user-persona|scene-navigation)>[\s\S]*?<\/\1>/g) ?? []) {
    if(add(match[0]))continue;
    const file=match[1]==='user-persona'?'persona.md':'.metadata/scene_index.json';
    add(`<${match[1]}>\n内容超出当前预算，完整内容请调用 rsi_profile_read：${join(profileDir,file)}\n</${match[1]}>`);
  }
  return {text:parts.length?open+parts.join('\n')+close:'',memories};
}
