import {useCallback,useEffect,useState} from 'react';
import {api} from './engine-api';
import {SelectControl} from './select-control';
import {SparkleIcon} from './icons';
import type {AdapterConfig} from './domain';
import './lora-card.css';

export type AdapterInfo = {id:string;name:string;family?:string;file?:string;format?:string;rank:number|null;bytes:number;sha256?:string;recommendedNarAdapterId?:string|null;default?:boolean};
export type AdapterCatalog = {artist:AdapterInfo[];nar:AdapterInfo[]};
export type AdapterValue = AdapterConfig;
export const MAX_ADAPTER_SCALE=1.5;

/* Loads the adapter registry once per visit; the engine keeps the paths, the browser only sees ids. */
export function LoraCard({value,onChange,active=true}:{value:AdapterValue;onChange:(next:AdapterValue)=>void;active?:boolean}){
  const [catalog,setCatalog]=useState<AdapterCatalog|null>(null),[loading,setLoading]=useState(false),[error,setError]=useState('');
  const load=useCallback(async()=>{
    setLoading(true);setError('');
    try{setCatalog(await api<AdapterCatalog>('/adapters'))}
    catch(problem){setError(problem instanceof Error&&problem.message?problem.message:'无法读取 LoRA 列表。')}
    finally{setLoading(false)}
  },[]);
  useEffect(()=>{if(active)void load()},[active,load]);
  const artists=catalog?.artist??[],narItems=catalog?.nar??[];
  const artist=artists.find(item=>item.id===value.artistId)??null;
  const recommendation=artist?.recommendedNarAdapterId??null;
  const suggested=narItems.find(item=>item.id===recommendation)??null;
  return <section className="reference-card has-reference lora-card" aria-label="LoRA 风格适配器">
    <div className="reference-heading lora-heading"><SparkleIcon size={18}/><label id="lora-heading">LoRA 风格适配器</label><button type="button" className="text-button" disabled={loading} onClick={()=>void load()}>{loading?'读取中…':'刷新'}</button></div>
    <div className="lora-row"><span className="lora-label">风格</span><SelectControl value={value.artistId??''} disabled={loading||!artists.length} onChange={event=>onChange({...value,artistId:event.target.value||null})}><option value="">不使用</option>{artists.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</SelectControl></div>
    {artist?<>
      <div className="lora-row"><span className="lora-label">强度</span><input className="lora-range" type="range" min={0} max={MAX_ADAPTER_SCALE} step={0.05} value={value.artistScale} aria-label={`${artist.name} 强度`} onChange={event=>onChange({...value,artistScale:Number(event.target.value)})}/><output className="lora-value">{value.artistScale.toFixed(2)}</output><button type="button" className="text-button" onClick={()=>onChange({...value,artistId:null})}>卸载</button></div>
      <p className="lora-hint">强度越高风格约束越强；改动对下一次生成生效。</p>
    </>:null}
    {narItems.length?<div className="lora-row"><span className="lora-label">复音细节</span><SelectControl value={value.narEnabled?(value.narId??''):''} disabled={loading} onChange={event=>onChange(event.target.value?{...value,narId:event.target.value,narEnabled:true}:{...value,narId:null,narEnabled:false})}><option value="">不使用</option>{narItems.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}</SelectControl></div>:null}
    {suggested&&!value.narEnabled?<div className="lora-suggest"><span>建议搭配 {suggested.name}</span><button type="button" className="text-button" onClick={()=>onChange({...value,narId:suggested.id,narEnabled:true})}>启用</button></div>:null}
    {error?<p className="reference-error" role="alert">{error}</p>:null}
    {catalog&&!artists.length&&!narItems.length?<p className="lora-hint">把 LoRA 放进 models/loras 后点「刷新」。</p>:null}
  </section>;
}
