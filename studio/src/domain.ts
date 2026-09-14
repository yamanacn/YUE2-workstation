export type Stage = 'queued'|'checking'|'planning'|'generating_tokens'|'synthesizing'|'decoding'|'finalizing'|'cancelling'|'cancelled'|'succeeded'|'failed'|'interrupted';
export type SeedMode = 'random'|'fixed'|'increment';
export type PerformanceConfig = { fp8CudaGraph?:boolean; quantization:'none'|'fp8'; offloadAr:boolean; vaeCoreFrames:256|512|1024; memoryBudgetGiB:number; dynamicTokens:boolean; targetSeconds:number; attention:'auto'|'sdpa'; queryChunkSize:64|128|256 };
export const performancePresets:Record<'performance'|'balanced'|'extreme',PerformanceConfig>={
  performance:{fp8CudaGraph:false,quantization:'none',offloadAr:false,vaeCoreFrames:1024,memoryBudgetGiB:0,dynamicTokens:true,targetSeconds:0,attention:'auto',queryChunkSize:256},
  balanced:{fp8CudaGraph:false,quantization:'none',offloadAr:true,vaeCoreFrames:512,memoryBudgetGiB:0,dynamicTokens:true,targetSeconds:0,attention:'auto',queryChunkSize:128},
  extreme:{fp8CudaGraph:false,quantization:'fp8',offloadAr:true,vaeCoreFrames:512,memoryBudgetGiB:0,dynamicTokens:true,targetSeconds:0,attention:'auto',queryChunkSize:64},
};
export type AdapterConfig = { artistId:string|null; artistScale:number; narId:string|null; narEnabled:boolean };
export type Config = { cot: 'full'|'melody'|'off'; temperature:number; topP:number; topK:number; repetitionPenalty:number; maxTokens:number; odeSteps:number; cfg:'auto'|number; performance?:PerformanceConfig; adapters?:AdapterConfig };
export type ReferenceStrength='free'|'balanced'|'faithful';
export type ReferenceSource={id:string;path:string;name:string;range:[number,number]|null;preserve:'melody'|'full';strength?:ReferenceStrength;sha256?:string};
export type VocalMode='auto'|'male'|'female'|'instrumental';
export type CreationMode='quick'|'advanced';
export type Draft = {reference?:ReferenceSource;abc?:string;title:string; lyrics:string; style:string; vocalMode:VocalMode; count:1|2|4; seedMode:SeedMode; seed:string; config:Config};
export type Snapshot = Readonly<{draft:Draft; seed:string; submittedAt:string; runtime:'demo'|'local-yue2'; requestId:string}>;
export type Run = {id:string; batchId:string; snapshot:Snapshot; state:Stage; stageStarted:number; created:number; error?:string; parentId?:string; attemptOf?:string; demoOutcome?:'success'|'fail'|'warning'; elapsed:number; progress?:{phase:string;detail?:string;completed:number|null;total:number|null;unit:string|null;elapsedSeconds:number}};
export type Track = {id:string; title:string; version:string; style:string; lyrics:string; artwork:string; duration:number; created:string; favorite:boolean; removed:boolean; runId?:string; snapshot:Snapshot; audioUrl:string; audioKind:'official-demo'|'local'|'generated'; audioFormat?:string; sampleRate?:number; channels?:number; subtype?:string; missing?:boolean; warning?:string; sourceTitle?:string};
export function originalExtension(track:Track){return track.audioFormat??(track.audioKind==='local'?(track.sourceTitle?.split('.').pop()||'mp3'):track.audioKind==='generated'?'flac':'mp3')}
export function sourceLabel(track:Track){return track.audioKind==='generated'?'本机生成':track.audioKind==='official-demo'?'官方示例':'本地关联'}
export function runProgress(run:Run){const p=run.progress;if(!p)return '';const count=p.completed!=null?`${p.completed}${p.total!=null?` / ${p.total}`:''} ${p.unit??''}`:'';return [p.detail,count,run.elapsed?`已用时 ${formatTime(run.elapsed)}`:''].filter(Boolean).join(' · ')}
export const defaultAdapters:AdapterConfig={artistId:null,artistScale:1,narId:null,narEnabled:false};
export const defaultConfig:Config={cot:'full',temperature:1,topP:.95,topK:100,repetitionPenalty:1.2,maxTokens:9000,odeSteps:32,cfg:1,performance:{...performancePresets.balanced},adapters:{...defaultAdapters}};
export const sampleLyrics='[Verse]\n末班车经过了街角\n你把晚风留在我的外套\n路灯下那些没说完的话\n陪着影子慢慢走回家\n\n[Chorus]\n在雨停之前 再等一遍\n让这座城市安静一点';
export const initialDraft:Draft={title:'雨停之前',lyrics:sampleLyrics,style:'独立流行 · 温暖男声 · 木吉他 · 松弛鼓点',vocalMode:'auto',count:1,seedMode:'random',seed:'831001',config:{...defaultConfig,adapters:{...defaultAdapters}}};
export const sampleAudio='/audio/tonight-awake.mp3';
export const stageLabels:Record<Stage,string>={queued:'等待开始',checking:'检查生成条件',planning:'构思旋律与和弦',generating_tokens:'生成音乐序列',synthesizing:'合成音频',decoding:'解码音频',finalizing:'保存作品',cancelling:'正在取消',cancelled:'已取消',succeeded:'已完成',failed:'生成失败',interrupted:'已中断'};
export const terminalStates:Stage[]=['cancelled','succeeded','failed','interrupted'];
export const activeStates:Stage[]=['checking','planning','generating_tokens','synthesizing','decoding','finalizing','cancelling'];
export const MAX_SEED=9223372036854775807n;
export function uid(){return crypto.randomUUID()}
export function cloneDraft(d:Draft):Draft{return {...structuredClone(d),vocalMode:d.vocalMode??'auto'}}
export function draftForCreationMode(draft:Draft,mode:CreationMode):Draft{const next=cloneDraft(draft);if(mode==='quick')delete next.abc;else delete next.reference;if(!next.abc?.trim())delete next.abc;return next}
function immutable<T extends object>(value:T):T{for(const nested of Object.values(value)){if(nested&&typeof nested==='object')immutable(nested)}return Object.freeze(value)}
export function validateDraft(d:Draft):{field:string;message:string}[]{
  const errors=[];

  if(!d.style.trim())errors.push({field:'style',message:'描述一下希望听到的曲风、人声或乐器。'});
  if(d.seedMode!=='random'){
    if(!/^\d+$/.test(d.seed))errors.push({field:'seed',message:'种子需要是非负整数。'});
    else if(BigInt(d.seed)>MAX_SEED||(d.seedMode==='increment'&&BigInt(d.seed)+BigInt(d.count-1)>MAX_SEED))errors.push({field:'seed',message:'种子超出范围，请输入 0 到 9223372036854775807 之间的整数。'});
  }
  const c=d.config;
  const p=c.performance;
  if(p&&((p.fp8CudaGraph!==undefined&&typeof p.fp8CudaGraph!=='boolean')||!['none','fp8'].includes(p.quantization)||typeof p.offloadAr!=='boolean'||typeof p.dynamicTokens!=='boolean'||![256,512,1024].includes(p.vaeCoreFrames)||![64,128,256].includes(p.queryChunkSize)||!['auto','sdpa'].includes(p.attention)||!Number.isFinite(p.memoryBudgetGiB)||(p.memoryBudgetGiB!==0&&p.memoryBudgetGiB<=2)||!Number.isFinite(p.targetSeconds)||p.targetSeconds<0||p.targetSeconds>960))errors.push({field:'config',message:'请检查性能参数：预算为 0 或大于 2 GiB，目标时长为 0–960 秒。'});
  if(!Number.isFinite(c.temperature)||c.temperature<0||c.temperature>5||!Number.isFinite(c.topP)||c.topP<=0||c.topP>1||!Number.isInteger(c.topK)||c.topK<1||!Number.isFinite(c.repetitionPenalty)||c.repetitionPenalty<=0||!Number.isInteger(c.maxTokens)||c.maxTokens<200||c.maxTokens>24575||!Number.isInteger(c.odeSteps)||c.odeSteps<1||(c.cfg!=='auto'&&(!Number.isFinite(c.cfg)||c.cfg<0||c.cfg>20)))errors.push({field:'config',message:'高级参数有无效值，请检查范围。'});
  return errors;
}
export function resolveSeeds(d:Draft):string[]{
  if(d.seedMode!=='random')return Array.from({length:d.count},(_,i)=>(BigInt(d.seed)+(d.seedMode==='increment'?BigInt(i):0n)).toString());
  const used=new Set<string>();
  while(used.size<d.count){const bytes=crypto.getRandomValues(new Uint32Array(2));used.add(((BigInt(bytes[0])<<32n|BigInt(bytes[1]))&MAX_SEED).toString())}
  return [...used];
}
export function createBatch(draft:Draft,requestId=uid(),seeds?:string[],parentId?:string):Run[]{
  if(validateDraft(draft).length)throw new Error('Invalid draft');
  const now=Date.now();
  return (seeds??resolveSeeds(draft)).map((seed,i)=>({id:uid(),batchId:requestId,snapshot:immutable({draft:cloneDraft(draft),seed,submittedAt:new Date(now).toISOString(),runtime:'demo' as const,requestId}),state:'queued',created:now+i,stageStarted:now,elapsed:0,parentId}));
}
export function transitionRun(run:Run,next:Stage,now=Date.now()):Run{
  if(terminalStates.includes(run.state))return run;
  if(run.state==='cancelling'&&next!=='cancelled'&&next!=='failed'&&next!=='interrupted')return run;
  const nextStates:Partial<Record<Stage,Stage[]>>={queued:['checking','cancelled','failed','interrupted'],checking:['planning','generating_tokens','cancelling','failed','interrupted'],planning:['generating_tokens','cancelling','failed','interrupted'],generating_tokens:['synthesizing','cancelling','failed','interrupted'],synthesizing:['decoding','cancelling','failed','interrupted'],decoding:['finalizing','cancelling','failed','interrupted'],finalizing:['succeeded','cancelling','failed','interrupted'],cancelling:['cancelled','failed','interrupted']};
  if(!nextStates[run.state]?.includes(next))return run;
  return {...run,state:next,stageStarted:now,elapsed:Math.max(0,Math.round((now-run.created)/1000))};
}
export function trackFromRun(run:Run):Track{
  if(run.snapshot.runtime!=='demo')throw new Error('Real results must come from the local engine.');
  const d=run.snapshot.draft;
  return {id:uid(),title:d.title.trim()||'未命名作品',version:'V01',style:d.style,lyrics:d.lyrics,artwork:'/assets/opal-glass.webp',duration:203.52,created:new Date().toISOString(),favorite:false,removed:false,runId:run.id,snapshot:run.snapshot,audioUrl:sampleAudio,audioKind:'official-demo',sourceTitle:'今晚不眠'};
}
export function makeSamples():Track[]{
  const data=[['雨停之前','V02','独立流行 · 温暖男声 · 木吉他','opal-glass','2026-09-10T14:32:00+08:00'],['晚风经过','V01','中文民谣 · 轻声演唱 · 指弹吉他','warm-dunes','2026-09-10T11:46:00+08:00'],['凌晨两点的海','V03','Dream pop · 女声 · 空间感合成器','frost-mountain','2026-09-10T09:21:00+08:00'],['城市的回声','V01','流行 · 温柔女声 · 钢琴','stone-fold','2026-09-09T22:17:00+08:00']];
  return data.map(([title,version,style,asset,created],i)=>({id:'sample-'+i,title,version,style,lyrics:i===0?sampleLyrics:i===1?'[Verse]\n晚风经过门前的小巷\n带走白天没说完的愿望':i===2?'[Verse]\n凌晨两点的海\n还在等潮汐回来':'[Verse]\n穿过长街的微光\n回声停在你身旁',artwork:`/assets/${asset}.webp`,duration:203.52,created,favorite:false,removed:false,snapshot:{draft:{...cloneDraft(initialDraft),title,style},seed:String(831001+i),submittedAt:created,runtime:'demo',requestId:'sample-'+i},audioUrl:sampleAudio,audioKind:'official-demo',sourceTitle:'今晚不眠'}));
}
export function configChanges(config:Config){return (Object.keys(defaultConfig) as (keyof Config)[]).filter(k=>JSON.stringify(config[k]??defaultConfig[k])!==JSON.stringify(defaultConfig[k])).length}
export function formatTime(seconds:number){const s=Math.max(0,Math.floor(Number.isFinite(seconds)?seconds:0));return `${String(Math.floor(s/60)).padStart(2,'0')}:${String(s%60).padStart(2,'0')}`}
export function formatDate(value:string){const d=new Date(value);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')} ${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`}
export function safeFilename(name:string){return (name.replace(/[<>:"/\\|?*\u0000-\u001f]/g,'_').replace(/[. ]+$/,'').trim()||'YuE2作品').slice(0,120)}
export type SavedState={version:1;draft:Draft;tracks:Track[];runs:Run[];paused:boolean};
export function recoverState(value:unknown):SavedState|null{
  if(!value||typeof value!=='object')return null;
  const s=value as SavedState;
  if(s.version!==1||!s.draft||typeof s.draft.lyrics!=='string'||typeof s.draft.style!=='string'||!s.draft.config||!Array.isArray(s.tracks)||!Array.isArray(s.runs))return null;
  return {...s,draft:{...initialDraft,...s.draft,config:{...defaultConfig,...s.draft.config}},tracks:s.tracks.map(t=>({...t,missing:t.audioKind==='local'||t.missing})),runs:s.runs.map(r=>activeStates.includes(r.state)?{...r,state:'interrupted',error:'上次关闭时任务尚未结束。'}:r),paused:s.runs.some(r=>activeStates.includes(r.state)||r.state==='queued')||s.paused};
}
