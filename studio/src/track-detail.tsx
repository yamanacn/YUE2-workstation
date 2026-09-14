import {useEffect,useRef,useState} from 'react';
import {Button,Collapsible,IconButton,Waveform} from './components';
import {CopyIcon,DownloadIcon,PauseIcon,PlayIcon,PlusIcon,QueueIcon,RetryIcon,WarningIcon,XIcon} from './icons';
import {formatDate,formatTime,runProgress,sourceLabel,stageLabels,terminalStates,type Run,type Track} from './domain';
import {playback,usePlayback} from './audio';
import './track-detail.css';

export type DetailTarget={kind:'track';track:Track}|{kind:'run';run:Run};
export type TrackActions={play:()=>void;locate:()=>void;reuse:()=>void;regenerate:()=>void;export:()=>void;addReference:()=>void};
export type RunActions={cancel:()=>void;retry:()=>void;queue:()=>void};

/* Stable per-work tint: the same work always gets the same diffuse glow. */
function detailGlow(seedText:string){
  let hash=0;
  for(const character of seedText)hash=(hash*31+character.charCodeAt(0))%100003;
  const hue=hash%360,hueAlt=(hue+38+hash%44)%360;
  const x1=6+hash%22,y1=-14+(hash>>3)%10;
  const x2=62+(hash>>5)%30,y2=-4+(hash>>7)%18;
  const radius=52+(hash>>9)%20;
  return `radial-gradient(${radius}% 78% at ${x1}% ${y1}%, hsl(${hue} 60% 56% / .26), transparent 70%),`
    +`radial-gradient(${radius+12}% 86% at ${x2}% ${y2}%, hsl(${hueAlt} 58% 52% / .2), transparent 72%),`
    +`linear-gradient(180deg, hsl(${hue} 42% 44% / .14), transparent 68%)`;
}

export function DetailPanel({target,open,referenceBusy,trackActions,runActions,onClose,onClosed,onCopy}:{
  target:DetailTarget;open:boolean;referenceBusy:boolean;trackActions:TrackActions|null;runActions:RunActions|null;onClose:()=>void;onClosed:()=>void;onCopy:(text:string,label:string)=>void;
}){
  const audio=usePlayback(),rootRef=useRef<HTMLElement>(null);
  const track=target.kind==='track'?target.track:null,run=target.kind==='run'?target.run:null;
  const title=track?(track.title||'未命名作品'):(run!.snapshot.draft.title||'未命名作品');
  const label=track?`${track.version} · ${sourceLabel(track)}`:`V01 · ${run!.snapshot.runtime==='local-yue2'?'本机生成':'演示生成'}`;
  const same=track?audio.trackId===track.id:false;
  const duration=track?(same?audio.duration:track.duration):0,current=same?audio.current:0;
  useEffect(()=>{rootRef.current?.querySelector<HTMLButtonElement>('[data-detail-close]')?.focus()},[]);
  const playing=same&&audio.playing;
  const progress=run?.progress;
  const percent=progress&&progress.total!=null&&progress.total>0&&progress.completed!=null?Math.round(Math.max(0,Math.min(1,progress.completed/progress.total))*100):null;
  const style=track?track.style:run!.snapshot.draft.style,lyrics=track?track.lyrics:run!.snapshot.draft.lyrics;
  const styleTextRef=useRef<HTMLSpanElement|null>(null);
  const [styleExpanded,setStyleExpanded]=useState(false),[styleOverflow,setStyleOverflow]=useState(false);
  const targetKey=track?`t:${track.id}`:`r:${run!.id}`;
  // A new work always starts folded: the panel should not remember the last work's expansion.
  useEffect(()=>{setStyleExpanded(false)},[targetKey]);
  useEffect(()=>{
    const el=styleTextRef.current;
    if(!el){setStyleOverflow(false);return}
    const measure=()=>{const line=parseFloat(getComputedStyle(el).lineHeight)||22;setStyleOverflow(el.scrollHeight>Math.round(line*3)+1)};
    measure();
    const observer=new ResizeObserver(measure);
    observer.observe(el);
    return ()=>observer.disconnect();
  },[targetKey,style]);
  const styleSection=style.trim()?<section className="track-detail-section">
    <div className="track-detail-section-head"><h3>风格描述</h3>{styleOverflow?<button type="button" className="text-button detail-expand" aria-expanded={styleExpanded} onClick={()=>setStyleExpanded(value=>!value)}>{styleExpanded?'收起':'展开'}</button>:null}<IconButton label="复制风格描述" onClick={()=>onCopy(style,'风格描述')}><CopyIcon/></IconButton></div>
    <p className="track-detail-style"><span ref={styleTextRef} className="track-detail-style-text" data-expanded={styleExpanded} data-overflow={styleOverflow}>{style}</span></p>
  </section>:null;
  return <aside ref={rootRef} className="track-detail" data-open={open} data-kind={target.kind} aria-label={`${title} ${track?'作品详情':'任务详情'}`}
    onTransitionEnd={event=>{if(!open&&event.propertyName==='width')onClosed()}}>
    <div className="track-detail-glow" style={{background:detailGlow(`${target.kind==='track'?track!.id:run!.id}|${run?run.snapshot.seed:track!.snapshot?.seed??''}`)}} aria-hidden="true"/>
    <div className="track-detail-head">
      <div><h2>{title}</h2><span className="version">{label}</span></div>
      <IconButton label={track?'关闭作品详情':'关闭任务详情'} data-detail-close onClick={onClose}><XIcon/></IconButton>
    </div>
    {track?
    <div className="track-detail-body">
      <div className="track-detail-hero">
        <img src={track.artwork} alt={`${track.title} 封面`}/>
        <div className="track-detail-hero-meta">
          <Button onClick={track.missing?()=>trackActions?.locate():()=>trackActions?.play()}>{playing?<><PauseIcon weight="fill"/>暂停</>:<><PlayIcon weight="fill"/>试听</>}</Button>
          <span className="track-detail-meta">{formatTime(track.duration)} · {formatDate(track.created)}</span>
        </div>
      </div>
      {track.missing?<div className="inline-warning"><WarningIcon/><span>音频文件不可用</span><button onClick={()=>trackActions?.locate()}>{track.audioKind==='generated'?'检查引擎':'重新定位'}</button></div>:<>
        <Waveform url={track.audioUrl} progress={duration?current/duration:0} duration={duration} onSeek={same?n=>playback.seek(n):undefined}/>
        <div className="expanded-timeline"><span>{formatTime(current)}</span><input type="range" min={0} max={duration} step=".1" value={current} aria-label={`${track.title} 播放进度`} onChange={e=>{if(same)playback.seek(Number(e.target.value))}} disabled={!same}/><span>{formatTime(duration)}</span></div>
      </>}
      {track.warning?<div className="inline-warning"><WarningIcon/><span>{track.warning}</span></div>:null}
      {styleSection}
      {lyrics.trim()?<section className="track-detail-section">
        <div className="track-detail-section-head"><h3>歌词</h3><IconButton label="复制歌词" onClick={()=>onCopy(lyrics,'歌词')}><CopyIcon/></IconButton></div>
        <p className="track-detail-lyrics">{lyrics}</p>
      </section>:null}
      <Collapsible title="参数与运行记录"><dl className="detail-parameters"><dt>实际种子</dt><dd>{track.snapshot.seed}</dd><dt>规划模式</dt><dd>{track.snapshot.draft.config.cot}</dd><dt>随机性</dt><dd>{track.snapshot.draft.config.temperature}</dd><dt>声学步数</dt><dd>{track.snapshot.draft.config.odeSteps}</dd><dt>音频来源</dt><dd>{track.sourceTitle??'本地文件'}</dd><dt>记录类型</dt><dd>{sourceLabel(track)}</dd></dl></Collapsible>
    </div>
    :
    <div className="track-detail-body">
      <div className="track-detail-hero">
        <img src="/assets/opal-glass.webp" alt="生成中的作品封面"/>
        <div className="track-detail-hero-meta">
          <span className={`detail-stage${terminalStates.includes(run!.state)?' is-settled':''}`}>{stageLabels[run!.state]}</span>
          <span className="track-detail-meta">{runProgress(run!)||`已用时 ${formatTime(run!.elapsed)}`}</span>
        </div>
      </div>
      {percent!==null?<div className="detail-progress" role="progressbar" aria-label={stageLabels[run!.state]} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{width:`${percent}%`}}/></div>
        :<div className="detail-progress" data-unknown="true" role="progressbar" aria-label={stageLabels[run!.state]}><span/></div>}
      {run!.error?<div className="inline-warning"><WarningIcon/><span>{run!.error.replace(/^[A-Za-z]+Error:\s*/,'')}</span></div>:null}
      {styleSection}
      {lyrics.trim()?<section className="track-detail-section">
        <div className="track-detail-section-head"><h3>歌词</h3><IconButton label="复制歌词" onClick={()=>onCopy(lyrics,'歌词')}><CopyIcon/></IconButton></div>
        <p className="track-detail-lyrics">{lyrics}</p>
      </section>:null}
      <Collapsible title="参数与运行记录"><dl className="detail-parameters"><dt>本次种子</dt><dd>{run!.snapshot.seed}</dd><dt>规划模式</dt><dd>{run!.snapshot.draft.config.cot}</dd><dt>随机性</dt><dd>{run!.snapshot.draft.config.temperature}</dd><dt>声学步数</dt><dd>{run!.snapshot.draft.config.odeSteps}</dd><dt>运行位置</dt><dd>{run!.snapshot.runtime==='local-yue2'?'本机引擎':'演示模式'}</dd><dt>提交时间</dt><dd>{formatDate(run!.snapshot.submittedAt)}</dd></dl></Collapsible>
    </div>}
    {track?
    <div className="track-detail-footer">
      <Button className="primary" disabled={track.missing||referenceBusy} onClick={()=>trackActions?.addReference()}><PlusIcon/>{referenceBusy?'正在添加…':'添加到参考音频'}</Button>
      <div className="track-detail-footer-row">
        <Button onClick={()=>trackActions?.reuse()}><CopyIcon/>复用参数</Button>
        <Button onClick={()=>trackActions?.regenerate()}><RetryIcon/>再生成一版</Button>
        <Button onClick={()=>trackActions?.export()} disabled={track.missing}><DownloadIcon/>导出</Button>
      </div>
    </div>
    :
    <div className="track-detail-footer">
      {terminalStates.includes(run!.state)
        ?<Button className="primary" onClick={()=>runActions?.retry()}><RetryIcon/>重试这次生成</Button>
        :<Button className="primary" disabled={run!.state==='cancelling'} onClick={()=>runActions?.cancel()}><XIcon/>{run!.state==='cancelling'?'正在取消':'取消生成'}</Button>}
      <div className="track-detail-footer-row">
        <Button onClick={()=>runActions?.queue()}><QueueIcon/>查看队列</Button>
        <Button onClick={()=>onCopy(JSON.stringify(run!.snapshot,null,2),'任务快照')}><CopyIcon/>复制快照</Button>
      </div>
    </div>}
  </aside>
}
