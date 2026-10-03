// Deterministic test double only: proves wiring and native sqlite-vec/RRF, never model quality.
export function fixtureEmbedding() {
  const vector=text=>{const result=new Float32Array(768);result[0]=1;for(const char of text)result[1+(char.codePointAt(0)%767)]+=1;const norm=Math.sqrt(result.reduce((sum,value)=>sum+value*value,0));return result.map(value=>value/norm);};
  return {getDimensions:()=>768,getProviderInfo:()=>({provider:'fixture',model:'character-hash-test-double'}),isReady:()=>true,startWarmup(){},close(){},embed:async text=>vector(text),embedBatch:async texts=>texts.map(vector)};
}
