import {motion} from 'motion/react';
import {useEffect,useRef,useState} from 'react';
import * as Menu from '@radix-ui/react-dropdown-menu';
import {IconButton} from './components';
import {MoreIcon,QueueIcon,XIcon} from './icons';
import {formatTime,type Run,stageLabels} from './domain';
import './generating-track.css';
export function GeneratingTrack({run,selected,onDetails,onQueue,onCancel}:{run:Run;selected:boolean;onDetails:()=>void;onQueue:()=>void;onCancel:()=>void}){
 const [clock,setClock]=useState(Date.now());
 const root=useRef<HTMLElement|null>(null);
 useEffect(()=>{const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer)},[]);
 useEffect(()=>{const element=root.current;if(!element)return;const observer=new IntersectionObserver(([entry])=>{element.dataset.offscreen=String(!entry.isIntersecting)},{threshold:0});observer.observe(element);return()=>observer.disconnect()},[]);
 const p=run.progress;
 const known=!!p&&p.total!=null&&p.total>0&&p.completed!=null;
 const fraction=known?Math.max(0,Math.min(1,p!.completed!/p!.total!)):null;
 const cancelling=run.state==='cancelling';
 const elapsed=Math.max(run.elapsed,Math.floor((clock-run.created)/1000));
 const label=stageLabels[run.state];
 return <motion.article ref={root} layout="position" initial={{opacity:0,height:0}} animate={{opacity:1,height:"auto"}} exit={{opacity:0,height:0}} style={{overflow:"clip"}} className={`track generating-track ${selected?'selected':''} ${cancelling?'is-cancelling':''}`} aria-label={`正在生成 ${run.snapshot.draft.title||'未命名作品'}`}>
  <div className="track-summary" onClick={event=>{if((event.target as HTMLElement).closest('button,input,a'))return;onDetails()}}>
   <button className="track-artwork generating-cover" aria-label="查看生成详情" onClick={onDetails}><img src="/assets/opal-glass.webp" alt="生成中的作品封面"/><span className="cover-light" aria-hidden="true"/></button>
   <div className="track-copy">
    <div className="title-version"><button onClick={onDetails} aria-expanded={selected} aria-haspopup="dialog">{run.snapshot.draft.title||'未命名作品'}</button><span className="version">V01 · {run.snapshot.runtime==='local-yue2'?'本机生成':'演示生成'}</span></div>
    <p>{run.snapshot.draft.style}</p>
    <div className="generation-flow" data-known={known} role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={fraction===null?undefined:Math.round(fraction*100)} aria-valuetext={fraction===null?label:`${label}，当前阶段 ${Math.round(fraction*100)}%`}>
      <div className="flow-rail"/><div className="flow-body" style={{transform:`scaleX(${fraction===null?1:fraction})`}}><span className="flow-mist"/><span className="flow-silk"/><span className="flow-current"/><span className="flow-front"/></div>
    </div>
    <div className="generation-status"><button onClick={onDetails}>{label}<span className="generation-ellipsis" aria-hidden="true">…</span></button><span className="generation-time">{formatTime(elapsed)}</span>{known&&<span className="generation-phase-percent">当前阶段 {Math.round(fraction!*100)}%</span>}</div>
   </div>
   <Menu.Root><Menu.Trigger asChild><IconButton label="生成任务选项"><MoreIcon/></IconButton></Menu.Trigger><Menu.Portal><Menu.Content className="dropdown" align="end"><Menu.Item onSelect={onDetails}><QueueIcon/>任务详情</Menu.Item><Menu.Item onSelect={onQueue}><QueueIcon/>查看队列</Menu.Item><Menu.Separator/><Menu.Item disabled={cancelling} onSelect={onCancel}><XIcon/>{cancelling?'正在取消':'取消生成'}</Menu.Item></Menu.Content></Menu.Portal></Menu.Root>
  </div>
 </motion.article>
}
