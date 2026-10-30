import {join} from 'node:path';

/** Preserve native asset text; only the host's tool guide needs name adaptation. */
export function recallToolGuide(result:any) {
  const guide=result?.appendSystemContext?.match(/<memory-tools-guide>[\s\S]*?<\/memory-tools-guide>/)?.[0];
  if(!guide)return '';
  return guide.replaceAll('tdai_memory_search','rsi_memory_search').replaceAll('tdai_conversation_search','rsi_conversation_search').replaceAll('read_file','rsi_profile_read')+'\n读取 profile 时，rsi_profile_read 的 query 为给出的完整文件路径。';
}

/** Budget the native ordered output at complete persisted-entry boundaries, never body prefixes. */
export function fitNativeMemoryEntries(result:any,stored:any[],budget:number) {
  if(!result?.prependContext)return result;
  const context=result.prependContext,split=context.indexOf('\n\n'),close='\n</relevant-memories>';
  if(split<0 || !context.startsWith('<relevant-memories>\n') || !context.endsWith(close))throw new Error('原生召回结构无法核对');
  const prefix=context.slice(0,split+2),body=context.slice(split+2,-close.length),entries:any[]=[];
  let offset=0;
  while(offset<body.length){
    const candidates=[];
    for(const row of stored){
      const tag=row.scene_name?`${row.type}|${row.scene_name}`:row.type;
      const head=`- [${tag}] ${row.content}`;
      if(!body.startsWith(head,offset))continue;
      const suffix=body.slice(offset+head.length).match(/^ \(活动时间: [^\n]*\)(?=\n|$)/)?.[0] ?? '';
      const end=offset+head.length+suffix.length;
      if(end!==body.length && body[end]!=='\n')continue;
      candidates.push({row,end,suffix});
    }
    const end=Math.max(...candidates.map(candidate=>candidate.end));
    const matches=candidates.filter(candidate=>candidate.end===end);
    if(!matches.length)throw new Error('召回正文无法对应完整资产，拒绝送达片段');
    const row=matches[0].row,suffix=matches[0].suffix;
    // Native fallback is the record's persistence timestamp, not an observed activity date.
    const hasActivityTime=(row:any)=>[row.metadata?.activity_start_time,row.metadata?.activity_end_time].some(value=>typeof value==='string' && /^\d{4}-\d{2}-\d{2}/.test(value));
    const activity=matches.map(candidate=>hasActivityTime(candidate.row));
    const timeKind=activity.every(Boolean)?'activity':activity.every(value=>!value)?'recorded':'ambiguous';
    const label=timeKind==='recorded'?'记录时间':timeKind==='ambiguous'?'时间来源待核实':'活动时间';
    const text=body.slice(offset,end-suffix.length)+suffix.replace('活动时间:',`${label}:`);
    const native=result.recalledL1Memories?.[entries.length] ?? {};
    entries.push({text,memory:{...native,content:row.content,type:row.type,timeKind,...(matches.length===1?{id:row.id,version:row.version}:{id:undefined,version:undefined,sourceAmbiguous:true,sourceCandidates:matches.map(candidate=>({id:candidate.row.id,version:candidate.row.version}))})}});
    offset=end+(end<body.length?1:0);
  }
  if(entries.length!==(result.recalledL1Memories?.length ?? 0))throw new Error('召回条目与原生顺序无法核对');
  const selected=[];let used=0;
  for(const entry of entries){const size=entry.text.length+(selected.length?1:0);if(used+size>budget)break;selected.push(entry);used+=size;}
  return {...result,prependContext:selected.length?prefix+selected.map(entry=>entry.text).join('\n')+close:undefined,recalledL1Memories:selected.map(entry=>entry.memory),memoryPresentation:{nativeSelectedCount:entries.length,deliveredCount:selected.length,droppedCount:entries.length-selected.length,completeBodies:true,budgetChars:budget}};
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
