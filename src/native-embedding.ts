import { AsyncLocalStorage } from 'node:async_hooks';
import { join } from 'node:path';
import { createEmbeddingService } from './core-entry.js';
import { FileLogger, diagnosticProvenance } from '../adapters/local-observability.js';
const failures=new AsyncLocalStorage<any[]>();
export async function createReadyEmbedding(config:any,directory:string,logger:any) {
  const actual=config ? {...config,...(config.provider==='local' && !config.modelCacheDir?{modelCacheDir:join(directory,'models')}:{})} : {provider:'local',modelCacheDir:join(directory,'models')};
  if(typeof actual.provider!=='string' || !actual.provider || (actual.provider!=='local' && (!actual.baseUrl || !actual.apiKey || !actual.model || !Number.isSafeInteger(actual.dimensions) || actual.dimensions<1)))throw Object.assign(new Error('向量服务配置不完整；不会静默切换模型'),{code:'INVALID_CONFIG'});
  const service=createEmbeddingService(actual,logger);
  service.startWarmup();
  await (service as any).waitForReady?.();
  if(!service.isReady())throw Object.assign(new Error('向量模型未就绪；不会退回关键词检索'),{code:'EMBEDDING_UNAVAILABLE'});
  return service;
}
/** Native components tolerate embedding errors; the host must not accept partial success. */
export async function withEmbeddingIntegrity<T>(operation:()=>Promise<T>):Promise<T> {
  return failures.run([],async()=>{const result=await operation();if(failures.getStore()!.length)throw failures.getStore()![0];return result;});
}
export function guardedEmbedding(service:any,sink:FileLogger) {
  const dimensions=service.getDimensions();
  if(!service.isReady() || !Number.isSafeInteger(dimensions) || dimensions<1)throw Object.assign(new Error('向量配置或就绪状态无效'),{code:'EMBEDDING_UNAVAILABLE'});
  const call=async(method:'embed'|'embedBatch',input:any,options:any)=>{
    const started=Date.now(),texts=method==='embed'?[input]:input;
    try {
      const result=await service[method](input,options),vectors=method==='embed'?[result]:result;
      if(vectors.length!==texts.length || vectors.some((vector:any)=>vector.length!==dimensions || !Array.from(vector).every(Number.isFinite) || !Array.from(vector).some(value=>value!==0)))throw Object.assign(new Error('向量输出维度或数值无效'),{code:'EMBEDDING_INVALID_OUTPUT'});
      sink.write('INFO','rsi.embedding.call',{...diagnosticProvenance(),method,text_count:texts.length,input_chars:texts.reduce((sum:number,text:string)=>sum+text.length,0),duration_ms:Date.now()-started,dimensions,token_usage:null,status:'completed'});
      return result;
    }catch(error:any){
      failures.getStore()?.push(error);
      sink.write('ERROR','rsi.embedding.call',{...diagnosticProvenance(),method,text_count:texts.length,input_chars:texts.reduce((sum:number,text:string)=>sum+text.length,0),duration_ms:Date.now()-started,dimensions,token_usage:null,status:'failed',code:error.code ?? error.name,message:error.message});
      throw error;
    }
  };
  return {getDimensions:()=>dimensions,getProviderInfo:()=>service.getProviderInfo(),isReady:()=>service.isReady(),startWarmup:()=>service.startWarmup(),embed:(text:string,options?:any)=>call('embed',text,options),embedBatch:(texts:string[],options?:any)=>call('embedBatch',texts,options)};
}
export function verifyVectorCoverage(memory:any) {
  const db=memory.getRawDb();
  const missingL1=Number(db.prepare('SELECT COUNT(*) AS count FROM l1_records WHERE record_id NOT IN (SELECT record_id FROM l1_vec)').get().count);
  const missingL0=Number(db.prepare('SELECT COUNT(*) AS count FROM l0_conversations WHERE record_id NOT IN (SELECT record_id FROM l0_vec)').get().count);
  return {missingL1,missingL0};
}
