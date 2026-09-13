import {useRef} from 'react';
import './editor-resize.css';

export function EditorResizeHandle({label}:{label:string}){
  const drag=useRef<{y:number;height:number;field:HTMLElement;scroll:HTMLElement|null;scrollTop:number}|null>(null);
  const resize=(field:HTMLElement,height:number)=>field.style.setProperty('--editor-height',`${Math.max(80,Math.min(1600,height))}px`);
  return <button type="button" className="editor-resize-handle" aria-label={`调整${label}高度`} title="上下拖动调整高度，也可用上下方向键"
    onPointerDown={e=>{if(e.button!==0)return;const field=e.currentTarget.closest('.field') as HTMLElement;const area=field.querySelector('textarea')!;const scroll=field.closest('.composer-scroll') as HTMLElement|null;drag.current={y:e.clientY,height:area.getBoundingClientRect().height,field,scroll,scrollTop:scroll?.scrollTop??0};e.preventDefault();e.currentTarget.setPointerCapture(e.pointerId);field.dataset.resizing='true'}}
    onPointerMove={e=>{const d=drag.current;if(d)resize(d.field,d.height+e.clientY-d.y+(d.scroll?.scrollTop??0)-d.scrollTop)}}
    onPointerUp={e=>{if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId)}}
    onLostPointerCapture={()=>{if(drag.current)delete drag.current.field.dataset.resizing;drag.current=null}}
    onPointerCancel={()=>{if(drag.current)delete drag.current.field.dataset.resizing;drag.current=null}}
    onKeyDown={e=>{if(e.key!=='ArrowDown'&&e.key!=='ArrowUp')return;e.preventDefault();const field=e.currentTarget.closest('.field') as HTMLElement;resize(field,field.querySelector('textarea')!.getBoundingClientRect().height+(e.key==='ArrowDown'?32:-32))}}
  ><span aria-hidden="true">⋰</span></button>
}
