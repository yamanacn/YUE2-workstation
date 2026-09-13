import {AnimatePresence,motion} from 'motion/react';
import {api} from './engine-api';
import type {ReferenceSource,ReferenceStrength} from './domain';
import {playback} from './audio';
import {useEffect,useRef,useState,type PointerEvent} from 'react';
import {CaretDownIcon,FileAudioIcon,PauseIcon,PlayIcon,RetryIcon,TrashIcon} from './icons';
import './reference-audio.css';

export type ReferenceAudio = {source?:ReferenceSource;file:File;url:string;duration:number;peaks:number[];range:[number,number]|null;preserve:'melody'|'full';strength:ReferenceStrength};
export type TranscriptionState={status:'idle'|'transcribing'|'ready'|'stale'|'error';sourceId?:string;signature?:string;message?:string};
const stamp=(seconds:number)=>{const rounded=Math.round(seconds*10);return `${Math.floor(rounded/600).toString().padStart(2,'0')}:${((rounded%600)/10).toFixed(1).padStart(4,'0')}`};
const clamp=(n:number,min:number,max:number)=>Math.max(min,Math.min(max,n));

export function ReferenceAudioCard({value,onChange,onBusyChange,source,onMissing,purpose='cover',active=true,transcription,onTranscribe}:{purpose?:'cover'|'score'|'advanced';active?:boolean;value:ReferenceAudio|null;onChange:(value:ReferenceAudio|null)=>void;onBusyChange:(busy:boolean)=>void;source?:ReferenceSource;onMissing:(source:ReferenceSource)=>void;transcription?:TranscriptionState;onTranscribe?:()=>void}){
  const audio=useRef<HTMLAudioElement>(null),wave=useRef<HTMLDivElement>(null);
  const revision=useRef(0),latest=useRef(value),previousUrl=useRef<string|null>(null);
  const drag=useRef<{kind:'new'|'start'|'end';x:number;anchor:number;before:[number,number]|null;moved:boolean}|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[expanded,setExpanded]=useState(purpose!=='advanced'),[playing,setPlaying]=useState(false),[position,setPosition]=useState(0),[over,setOver]=useState(false);
  latest.current=value;
  useEffect(()=>setExpanded(purpose!=='advanced'),[purpose]);
  useEffect(()=>{if(!active)audio.current?.pause()},[active]);
  useEffect(()=>{onBusyChange(busy)},[busy,onBusyChange]);
  useEffect(()=>playback.subscribe(()=>{if(playback.getState().playing)audio.current?.pause()}),[]);
  useEffect(()=>{if(previousUrl.current&&previousUrl.current!==value?.url)URL.revokeObjectURL(previousUrl.current);previousUrl.current=value?.url??null;setPosition(0);setPlaying(false)},[value?.url]);
  useEffect(()=>()=>{revision.current++;loadedId.current=undefined;if(previousUrl.current)URL.revokeObjectURL(previousUrl.current)},[]);
  useEffect(()=>{const a=audio.current;if(!a||!value)return;const [start,end]=value.range??[0,value.duration];if(a.currentTime<start||a.currentTime>=end){a.pause();a.currentTime=start;setPosition(start)}},[value?.range]);
  useEffect(()=>{if(!playing)return;let frame=0;const tick=()=>{const a=audio.current,v=latest.current;if(a&&v){const end=v.range?.[1]??v.duration;if(a.currentTime>=end){a.pause();a.currentTime=end}setPosition(a.currentTime)}frame=requestAnimationFrame(tick)};frame=requestAnimationFrame(tick);return()=>cancelAnimationFrame(frame)},[playing]);
  const loadedId=useRef<string|undefined>(undefined);
  useEffect(()=>{if(source?.id&&source.id!==loadedId.current){loadedId.current=source.id;void restore(source)}else if(!source){loadedId.current=undefined}},[source?.id]);
  async function restore(saved:ReferenceSource){
    const restoreRevision=++revision.current;setBusy(true);
    try{await api(`/references/${saved.id}`);const response=await fetch(`/api/v1/references/${saved.id}/audio`);if(!response.ok)throw new Error();const bytes=await response.blob();if(restoreRevision!==revision.current)return;await load(new File([bytes],saved.name),saved)}catch{if(restoreRevision===revision.current)onMissing(saved)}finally{if(restoreRevision===revision.current||restoreRevision+1===revision.current)setBusy(false)}
  }
  async function pick(){
    setError('');if(purpose==='advanced')setExpanded(false);setBusy(true);
    try{const response=await fetch('/api/v1/references/pick',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({picker:'native'})});if(!response.ok){let detail='';try{const body=await response.json();detail=typeof body.detail==='string'?body.detail:''}catch{}throw new Error(detail||`本地文件选择失败（HTTP ${response.status}）。`)}const selected=await response.json();if(selected){loadedId.current=selected.id;await restore({...selected,range:null,preserve:purpose==='advanced'?'full':'melody',strength:purpose==='advanced'?'faithful':'balanced'})}}catch(error){setError(error instanceof Error&&error.message?error.message:'本地文件选择失败，请重试。')}finally{setBusy(false)}
  }
  async function load(file?:File,saved?:ReferenceSource){
    if(!file)return;
    const id=++revision.current;setBusy(true);setError('');audio.current?.pause();
    let context:AudioContext|undefined;
    try{
      context=new AudioContext();
      const decoded=await context.decodeAudioData(await file.arrayBuffer());
      if(!Number.isFinite(decoded.duration)||decoded.duration<=0)throw new Error('音频为空');
      const channels=Array.from({length:decoded.numberOfChannels},(_,i)=>decoded.getChannelData(i));
      const peaks=Array.from({length:160},(_,i)=>{let peak=0;const start=Math.floor(i*decoded.length/160),end=Math.floor((i+1)*decoded.length/160);for(let j=start;j<end;j++)for(const channel of channels)peak=Math.max(peak,Math.abs(channel[j]));return peak});
      const max=Math.max(...peaks,.001);
      if(id!==revision.current)return;
      onChange({source:saved,file,url:URL.createObjectURL(file),duration:decoded.duration,peaks:peaks.map(p=>p/max),range:saved?.range??null,preserve:saved?.preserve??(purpose==='advanced'?'full':'melody'),strength:saved?.strength??(purpose==='advanced'?'faithful':'balanced')});
    }catch{if(id===revision.current)setError('无法读取这份音频，请换用可播放的 MP3、WAV 或 FLAC 文件。')}
    finally{if(context)void context.close();if(id===revision.current)setBusy(false)}
  }
  function remove(){revision.current++;audio.current?.pause();onChange(null);setBusy(false);setError('')}
  function timeAt(x:number){const rect=wave.current!.getBoundingClientRect();return clamp((x-rect.left)/rect.width,0,1)*value!.duration}
  function pointerDown(e:PointerEvent<HTMLDivElement>){
    if(!value||e.button!==0)return;
    const kind=(e.target as HTMLElement).closest<HTMLElement>('[data-handle]')?.dataset.handle as 'start'|'end'|undefined;
    drag.current={kind:kind??'new',x:e.clientX,anchor:timeAt(e.clientX),before:value.range,moved:false};
    e.currentTarget.setPointerCapture(e.pointerId);audio.current?.pause();
  }
  function pointerMove(e:PointerEvent<HTMLDivElement>){
    const d=drag.current,v=latest.current;if(!d||!v)return;
    if(Math.abs(e.clientX-d.x)<4&&!d.moved)return;d.moved=true;
    const t=timeAt(e.clientX),gap=Math.min(.1,v.duration),before=d.before??[0,v.duration];
    let range:[number,number];
    if(d.kind==='start')range=[clamp(t,0,before[1]-gap),before[1]];
    else if(d.kind==='end')range=[before[0],clamp(t,before[0]+gap,v.duration)];
    else{const left=Math.min(t,d.anchor),right=Math.max(t,d.anchor);range=[clamp(left,0,v.duration-gap),Math.min(v.duration,Math.max(right,left+gap))]}
    onChange({...v,range});
  }
  function pointerUp(e:PointerEvent<HTMLDivElement>){
    const d=drag.current,v=latest.current;if(!d||!v)return;
    if(!d.moved&&d.kind==='new'&&audio.current){const [start,end]=v.range??[0,v.duration];audio.current.currentTime=clamp(timeAt(e.clientX),start,end);setPosition(audio.current.currentTime)}
    drag.current=null;if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);
  }
  function adjust(edge:0|1,direction:number){if(!value)return;const range:[number,number]=[...(value.range??[0,value.duration])];const gap=Math.min(.1,value.duration);range[edge]=edge===0?clamp(range[0]+direction,0,range[1]-gap):clamp(range[1]+direction,range[0]+gap,value.duration);onChange({...value,range})}
  async function toggle(){const a=audio.current;if(!a||!value)return;if(!a.paused){a.pause();return}const [start,end]=value.range??[0,value.duration];if(a.currentTime<start||a.currentTime>=end-.02)a.currentTime=start;try{playback.pause();await a.play()}catch{setError('试听未能开始，请再次点击播放。')}}
  const range=value?.range,start=range?.[0]??0,end=range?.[1]??value?.duration??0;
  const transcriptionStatus=transcription?.status??'idle';
  const transcribeLabel=transcriptionStatus==='transcribing'?'转谱中…':transcriptionStatus==='ready'||transcriptionStatus==='stale'?'重新转谱':transcriptionStatus==='error'?'重试转谱':'转谱';
  return <section className={`reference-card ${value?'has-reference':''} ${over?'drag-over':''}`} aria-label={purpose==='score'?'分析音频':'参考音频'} onDragOver={e=>{e.preventDefault();setOver(true)}} onDragLeave={e=>{if(!(e.relatedTarget instanceof Node&&e.currentTarget.contains(e.relatedTarget)))setOver(false)}} onDrop={e=>{e.preventDefault();setOver(false);setError(`要记录原文件路径，请点击${purpose==='score'?'添加音频':'添加参考'}，在本地文件选择器中选择这份音频。`)}}>
    <AnimatePresence initial={false} mode="wait">{!value?<motion.div key="empty" initial={{height:0,opacity:0}} animate={{height:"auto",opacity:1}} exit={{height:0,opacity:0}} style={{overflow:"clip"}}><button className="add-reference" disabled={busy} onClick={()=>void pick()}><span className="reference-plus">＋</span>{busy?'正在读取音频…':purpose==='score'?'添加音频':'添加参考'}<span className="reference-add-hint">选择本地音乐</span></button></motion.div>:<motion.div key="reference" initial={{height:0,opacity:0}} animate={{height:"auto",opacity:1}} exit={{height:0,opacity:0}} style={{overflow:"clip"}}>
      <div className="reference-heading"><span>{purpose==='score'?'分析音频':purpose==='advanced'?'参考音频 → ABC':'参考音频'}</span>{purpose==='cover'&&<span className="reference-mode"><RetryIcon size={14}/>翻唱</span>}{purpose==='advanced'&&(onTranscribe?<button type="button" className="reference-mode reference-transcribe" disabled={busy||transcriptionStatus==='transcribing'} onClick={onTranscribe}><FileAudioIcon size={14}/>{transcribeLabel}</button>:<span className="reference-mode"><FileAudioIcon size={14}/>转谱</span>)}<button className="reference-icon" aria-label="移除参考音频" onClick={remove}><TrashIcon size={17}/></button></div>
      <div className="reference-file"><button className="reference-play" aria-label={playing?'暂停参考音频':'试听参考音频'} onClick={()=>void toggle()}>{playing?<PauseIcon weight="fill"/>:<PlayIcon weight="fill"/>}</button><div><strong title={value.file.name}>{value.file.name}</strong><span>{stamp(position)} / {stamp(value.duration)}</span></div><button className="reference-replace" disabled={busy} onClick={()=>void pick()}>{busy?'读取中…':'替换'}</button>{purpose==='score'&&<button className="reference-icon" aria-label="移除分析音频" onClick={remove}><TrashIcon size={16}/></button>}</div>
      <div ref={wave} className="reference-wave" aria-label="音频波形，拖动选取片段" onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp} onPointerCancel={()=>{const d=drag.current;if(d&&latest.current)onChange({...latest.current,range:d.before});drag.current=null}}>
        <div className="reference-bars" aria-hidden="true">{value.peaks.map((p,i)=><i key={i} className={range&&(i/160*value.duration<start||i/160*value.duration>end)?'outside':''} style={{height:`${Math.max(3,p*82)}%`}}/>)}</div>
        {range&&<div className="reference-selection" style={{left:`${start/value.duration*100}%`,width:`${(end-start)/value.duration*100}%`}}/>}
        {range&&([0,1] as const).map(edge=><button key={edge} type="button" role="slider" aria-label={edge===0?'选区开始时间':'选区结束时间'} aria-valuemin={edge===0?0:start+Math.min(.1,value.duration)} aria-valuemax={edge===0?end-Math.min(.1,value.duration):value.duration} aria-valuenow={range[edge]} aria-valuetext={stamp(range[edge])} data-handle={edge===0?'start':'end'} className="reference-handle" style={{left:`${range[edge]/value.duration*100}%`}} onKeyDown={e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();adjust(edge,(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?1:.1))}}}><span/></button>)}
        <div className="reference-playhead" style={{left:`${position/value.duration*100}%`}} aria-hidden="true"/>
      </div>
      <div className="reference-range-info">{range?<><span>{stamp(start)} — {stamp(end)} · {(end-start).toFixed(1)} 秒</span><button onClick={()=>onChange({...value,range:null})}>恢复整首</button></>:<><span>整首 · {stamp(value.duration)}</span><span>拖动波形选取片段</span></>}</div>
      {purpose!=='score'&&<div className="reference-cover"><button className="reference-cover-toggle" aria-expanded={expanded} aria-controls="reference-cover-settings" onClick={()=>setExpanded(!expanded)}>{purpose==='advanced'?'转谱设置':'翻唱设置'}<CaretDownIcon size={14} className={expanded?'expanded':''}/></button><div id="reference-cover-settings" inert={!expanded} aria-hidden={!expanded} data-collapsed={!expanded}><div className="reference-preserve"><span>{purpose==='advanced'?'提取内容':'保留内容'}</span><div role="group" aria-label={purpose==='advanced'?'转谱提取内容':'翻唱保留内容'}>{(['melody','full'] as const).map(p=><button key={p} aria-pressed={value.preserve===p} onClick={()=>onChange({...value,preserve:p})}>{p==='melody'?'旋律':'旋律与和弦'}</button>)}</div></div><div className="reference-strength"><span>{purpose==='advanced'?'谱面保真度':'参考强度'}</span><div role="group" aria-label={purpose==='advanced'?'谱面保真度':'参考强度'}>{([['free','自由'],['balanced','平衡'],['faithful','保真']] as const).map(([s,label])=><button key={s} aria-pressed={value.strength===s} onClick={()=>onChange({...value,strength:s})}>{label}</button>)}</div></div><p>{purpose==='advanced'?(value.preserve==='melody'?'只提取旋律，伴奏由 YuE2 重新设计。':'提取旋律与和弦，供下方 ABC 编辑器继续修改。'):(value.preserve==='melody'?'沿用旋律，让伴奏随新风格变化。':'沿用旋律与和弦，重新演绎声音和编曲。')} 当前强度：{value.strength==='free'?'保留旋律轮廓，允许更大改编':value.strength==='faithful'?'尽量贴近音高、节奏和乐句':'保留主旋律和节奏，允许局部变化'}。</p></div></div>}
      {purpose==='advanced'&&transcription&&<div className={`reference-transcription ${transcription.status}`} role="status"><span>{transcription.status==='transcribing'?'正在提取 ABC…':transcription.status==='ready'?'ABC 已生成，可在下方编辑':transcription.status==='stale'?'转谱设置已变化，需要重新转谱':transcription.status==='error'?(transcription.message||'ABC 转谱失败，请点击上方「转谱」重试。'):'尚未转谱，点击上方「转谱」开始'}</span></div>}
      <p className="reference-session"><FileAudioIcon size={12}/>{value.source?.path??'未记录源路径'}</p>
      <audio ref={audio} src={value.url} onPlay={()=>setPlaying(true)} onPause={()=>setPlaying(false)} onEnded={()=>setPlaying(false)} onTimeUpdate={e=>{const a=e.currentTarget;setPosition(a.currentTime);if(a.currentTime>=end){a.pause();if(a.currentTime>end)a.currentTime=end}}}/>
    </motion.div>}</AnimatePresence>
    {error&&<p className="reference-error" role="alert">{error}</p>}
  </section>;
}
