import { AsyncLocalStorage } from 'node:async_hooks';
import { FileLogger } from '../vendor/core/src/core/report/file-logger.js';
import { NoopObservabilityBackend } from '../vendor/core/src/core/report/noop-backend.js';
const context=new AsyncLocalStorage<{sink:FileLogger,attrs:Record<string,unknown>}>();
export { FileLogger };
/** Keep native event fields and attach host provenance without a global data directory. */
export function withLocalDiagnostics<T>(sink:FileLogger,attrs:Record<string,unknown>,operation:()=>T):T {
  return context.run({sink,attrs:{...context.getStore()?.attrs,...attrs}},operation);
}
export function diagnosticEvent(level:string,event:string,attrs:any={},error?:any) {
  try {
    const current=context.getStore();
    current?.sink.write(level,event,{...attrs,...current.attrs,...(error?{'error.message':error.message,'error.type':error.name}:{})});
  }catch{/* Diagnostics must not interrupt native work. */}
}
const base=new NoopObservabilityBackend();
const backend=Object.assign(base,{
  type:'local-file',
  log:{type:'local-file',info:(event:string,attrs?:any)=>diagnosticEvent('INFO',event,attrs),warn:(event:string,attrs?:any)=>diagnosticEvent('WARN',event,attrs),error:(event:string,attrs?:any,error?:any)=>diagnosticEvent('ERROR',event,attrs,error),debug:(event:string,attrs?:any)=>diagnosticEvent('DEBUG',event,attrs)},
  trace:Object.assign(base.trace,{type:'local-file',report:(event:string,attrs?:any)=>diagnosticEvent('TRACE',event,attrs)}),
  metric:{type:'local-file',send:(message:any)=>diagnosticEvent('METRIC',message.metric,message),async initialize(){},async destroy(){}},
});
// Distributed span processors remain disabled; local native events are persisted.
export function getObservabilityBackend(){return backend;}
