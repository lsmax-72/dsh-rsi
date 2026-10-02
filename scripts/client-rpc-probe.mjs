import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import {webcrypto} from 'node:crypto';
import * as cordis from '@deepseek-ai/cordis';
import {remoteContribution,clientRequest} from '../lib/rpc-contract.js';
/** Execute the official client artifact against the actual host Gateway in one fixture process. */
export async function checkClientRpc(host,cwd) {
  let gateway;
  const script=await readFile(new URL('../node_modules/@deepseek-ai/dsh-api-gateway/lib/client.js',import.meta.url),'utf8');
  vm.runInNewContext(script,{window:{__ModuleLoader__:{load:({factory})=>{gateway=factory(name=>{assert.equal(name,'@deepseek-ai/cordis');return cordis;});}}},crypto:webcrypto,AbortController,AbortSignal,Promise,setTimeout,clearTimeout,Uint8Array,console,TextEncoder,TextDecoder},{filename:'official-client-gateway.js'});
  const client=new cordis.Context(),calls=[];
  client.provide('typert',{remotes:{register:()=>()=>{}},contexts:{getClient:()=>undefined}});
  client.provide('connection',{registerGenerationSource:()=>()=>{},start:()=>({stop(){}}),rpc:{open:()=>{throw new Error('Streams are not used by this probe');},call:async(path,endpoint,payload)=>{calls.push({path,endpoint,payload});const [namespace,method]=endpoint.split('/');return {ok:true,value:await host.typertGateway.invoke({namespace,method,args:payload.args})};}}});
  const fiber=client.plugin(gateway);await fiber;
  const mount=client.plugin({inject:['remote'],async apply(ctx){const dispose=await ctx.remote.$mount(remoteContribution);ctx.effect(()=>dispose);}});await mount;
  const business=client.plugin({inject:['remote','remote.rsi'],async apply(ctx){const snapshot=await clientRequest(ctx,'snapshot',{cwd});assert.equal(snapshot.workspace.cwd,cwd);assert.equal(calls[0].endpoint,'rsi/request');assert.deepEqual(JSON.parse(JSON.stringify(calls[0].payload)),{args:{operation:'snapshot',payload:{cwd}}});}});await business;
  await business.dispose();await mount.dispose();await fiber.dispose();return {status:'PASS',calls:calls.length,carrier:'official client projection to actual host Gateway; in-process fixture carrier'};
}
