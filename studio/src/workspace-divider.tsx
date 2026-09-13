import {useEffect,useRef,useState} from 'react';
import './workspace-divider.css';
export function WorkspaceDivider(){
 const ref=useRef<HTMLDivElement>(null),drag=useRef(false);
 const [ratio,setRatio]=useState(()=>{try{const n=Number(localStorage.getItem('yue2-composer-ratio'));return n>=.2&&n<=.65?n:.4}catch{return .4}});
 useEffect(()=>{
   const host=ref.current?.parentElement;
   if(!host)return;
   const apply=()=>{
     const width=host.clientWidth;
     host.style.setProperty('--composer-width',`${Math.max(320,Math.min(width-440,width*ratio))}px`);
   };
   apply();
   const observer=new ResizeObserver(apply);
   observer.observe(host);
   try{localStorage.setItem('yue2-composer-ratio',String(ratio))}catch{}
   return()=>observer.disconnect()
 },[ratio]);
 return <div ref={ref} className="workspace-divider" role="separator" tabIndex={0} aria-label="调整创作区宽度" aria-orientation="vertical" aria-valuemin={20} aria-valuemax={65} aria-valuenow={Math.round(ratio*100)} onDoubleClick={()=>setRatio(.3)} onPointerDown={e=>{if(e.button!==0)return;drag.current=true;e.currentTarget.setPointerCapture(e.pointerId);e.preventDefault()}} onPointerMove={e=>{if(!drag.current)return;const box=e.currentTarget.parentElement!.getBoundingClientRect();setRatio(Math.max(.2,Math.min(.65,(e.clientX-box.left)/box.width)))}} onPointerUp={()=>{drag.current=false}} onLostPointerCapture={()=>{drag.current=false}} onPointerCancel={()=>{drag.current=false}} onKeyDown={e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();setRatio(r=>Math.max(.2,Math.min(.65,r+(e.key==='ArrowLeft'?-.02:.02))))}}}><span/></div>
}
