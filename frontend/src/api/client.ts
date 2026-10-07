import type { components } from './generated';
import { apiBase, streamURL } from './routing';
export type Models = components['schemas'];
export type Session = Models['LoginResponse'];
export type Job = Models['JobResponse'];
export type Trace = Models['TraceEvent'];
export type Schema = Models['SchemaResponse'];
export const base = apiBase({api: import.meta.env.VITE_API_BASE_URL, legacy: import.meta.env.VITE_API_URL});
export class ApiError extends Error {
  constructor(public status:number, public body:Models['ErrorResponse']) { super(body.detail); }
}
async function request<T>(path:string, token?:string, body?:unknown, signal?:AbortSignal):Promise<T> {
  const response=await fetch(base+path,{method:body===undefined?'GET':'POST',signal,cache:'no-store',
    headers:{...(body===undefined?{}:{'Content-Type':'application/json'}),...(token?{Authorization:`Bearer ${token}`}:{})},
    body:body===undefined?undefined:JSON.stringify(body)});
  const json=await response.json();
  if(!response.ok) throw new ApiError(response.status,typeof json.detail==='string'?json:{detail:'Service unavailable.',error_code:'HTTP_ERROR',ast_trace:[]});
  return json as T;
}
export const api={
  login:(user_id:string,password:string)=>request<Session>('/auth/login',undefined,{user_id,password}),
  health:(signal?:AbortSignal)=>request<Models['HealthResponse']>('/health',undefined,undefined,signal),
  schema:(token:string,signal?:AbortSignal)=>request<Schema>('/schema',token,undefined,signal),
  classify:(token:string,question:string,signal?:AbortSignal)=>request<Models['ClassifyResponse']>('/query/classify',token,{question},signal),
  execute:(token:string,question:string,signal?:AbortSignal)=>request<Job>('/query/execute',token,{question},signal),
  job:(token:string,id:string)=>request<Job>(`/query/jobs/${encodeURIComponent(id)}`,token),
  cancel:(token:string,id:string)=>request<Job>(`/query/jobs/${encodeURIComponent(id)}/cancel`,token,{}),
  audit:(token:string,id:string,after=0)=>request<Models['AuditResponse']>(`/telemetry/audit-logs?job_id=${encodeURIComponent(id)}&after_sequence=${after}&limit=100`,token),
};
export function websocketURL(){return streamURL(base, import.meta.env.VITE_WS_BASE_URL, window.location.origin);}
