/** Small JSON contract shared by the host validator and the native client mount. */
export const operations=['snapshot','settings','learn','versions','skill','skillFile','editSkill','memoryLayer','disable','rollback','editMemory','deleteMemory','importSkill','promote','export','clear','originalSkills','searchConversations','rebuildProfile','convertSkill','convertMemory'] as const;
export function parseOperation(value:any) {if(typeof value!=='string' || !operations.includes(value as any))throw new Error('未知管理操作');return value;}
export function parsePayload(value:any) {
  if(!value || typeof value!=='object' || Array.isArray(value))throw new Error('请求格式无效');
  const encoded=JSON.stringify(value);if(encoded.length>262144)throw new Error('管理请求过大');
  for(const key of Object.keys(value))if(!['cwd','scope','id','version','settings','disabled','content','name','confirm','query','language','path','layer','offset','expectedVersion'].includes(key))throw new Error(`未知请求字段：${key}`);
  for(const key of ['cwd','scope','id','content','name','confirm','query','language','path','layer'])if(value[key]!==undefined && typeof value[key]!=='string')throw new Error(`请求字段 ${key} 无效`);
  for(const key of ['version','offset','expectedVersion'])if(value[key]!==undefined&&(!Number.isSafeInteger(value[key])||value[key]<(key==='offset'?0:1)))throw new Error(`请求字段 ${key} 无效`);
  return value;
}
export const remoteContribution={package:'dsh-rsi',descriptors:[{id:'dsh-rsi:rsi/request',service:'rsi',namespace:'rsi',method:'request',invocation:{kind:'direct'},parameters:[
  {name:'operation',wire:'operation',source:'json',codec:{mode:'strict',typeSymbol:'dsh-rsi.Operation',create:()=>({parse:parseOperation})}},
  {name:'payload',wire:'payload',source:'json',codec:{mode:'strict',typeSymbol:'dsh-rsi.Payload',create:()=>({parse:parsePayload})}},
],result:{mode:'src-json'},sourceLocation:{file:'src/index.ts',line:14,column:1}}]};
export async function clientRequest(ctx:any,operation:string,payload:any) {
  const result=await ctx.remote.rsi.request(operation,payload);
  if(!result.ok)throw new Error(result.error?.message ?? '宿主管理请求失败');
  return result.value;
}
