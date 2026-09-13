import type {CreationMode,Draft,Run,Track} from './domain.ts';

export type EngineHealth={ok:boolean;status:'ready'|'busy'|'unavailable'|'resource_wait';dependenciesReady:boolean;modelsReady:boolean;modelLoaded:boolean;workerActive:boolean;reason?:string;profile:{backend:string;memoryBudgetGiB:number|'auto';modelName:string;decoderName:string;modelRevision:string;vaeRevision:string};device:{name:string;totalMiB:number;freeMiB:number}|null};
export type EngineState={runs:Run[];tracks:Track[];queuePaused:boolean;eventCursor:number};
export type BatchRequest={requestId:string;draft:Draft;creationMode?:CreationMode;resolvedSeeds?:string[];parentTrackId?:string};
export type PendingRequest={path:string;body:BatchRequest|{requestId:string}};
export type BatchResult={requestId:string;batchId:string;runs:Run[];replayed:boolean};
export type ApiOptions={timeoutMs?:number};
export class ApiError extends Error {status:number;constructor(message:string,status:number){super(message);this.status=status}}
export async function api<T>(path:string,method='GET',body?:unknown,options?:ApiOptions):Promise<T>{
  const writes=['POST','PATCH','PUT','DELETE'].includes(method.toUpperCase());
  const payload=body===undefined&&writes?{}:body;
  const timeoutMs=options?.timeoutMs??10000;
  const response=await fetch(`/api/v1${path}`,{method,headers:{Accept:'application/json',...(payload!==undefined?{'Content-Type':'application/json'}:{})},body:payload!==undefined?JSON.stringify(payload):undefined,signal:AbortSignal.timeout(timeoutMs),cache:'no-store'});
  let data;try{data=await response.json()}catch{throw new ApiError('本地引擎没有返回有效数据。',response.status||502)}
  if(!response.ok)throw new ApiError(typeof data.detail==='string'?data.detail:'引擎请求失败。',response.status);
  return data as T;
}
export async function findAccepted(requestId:string):Promise<BatchResult|null>{try{return await api<BatchResult>(`/batches/by-request/${encodeURIComponent(requestId)}`)}catch(error){if(error instanceof ApiError&&error.status===404)return null;throw error}}
// Reconciliation precedes every retry. The exact persisted request is reused after a lost response.
export async function sendPending(pending:PendingRequest):Promise<BatchResult>{
  const accepted=await findAccepted(pending.body.requestId);if(accepted)return accepted;
  try{return await api<BatchResult>(pending.path,'POST',pending.body)}catch(error){
    if(error instanceof ApiError&&error.status>=400&&error.status<500)throw error;
    try{const found=await findAccepted(pending.body.requestId);if(found)return found}catch{/* Keep original uncertainty and request ID. */}
    throw error;
  }
}
export const PENDING_KEY='yue2-live-pending-v1';
export function readPending():PendingRequest|null{try{const p=JSON.parse(localStorage.getItem(PENDING_KEY)??'null');return p&&typeof p.body?.requestId==='string'&&(p.path==='/batches'||/^\/runs\/[^/]+\/retry$/.test(p.path))?p:null}catch{return null}}
export function effectiveMode(preference:'live'|'demo',online:boolean):'live'|'demo'|'offline'{return preference==='demo'?'demo':online?'live':'offline'}
