import { getObservabilityBackend } from './local-observability.js';
export const obsLogger={
  info:(event:string,attrs?:any)=>getObservabilityBackend().log.info(event,attrs),
  warn:(event:string,attrs?:any)=>getObservabilityBackend().log.warn(event,attrs),
  error:(event:string,attrs?:any,error?:any)=>getObservabilityBackend().log.error(event,attrs,error),
};
