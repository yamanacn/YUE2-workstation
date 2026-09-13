import {useCallback,useEffect,useRef,useState} from 'react';
import {api,effectiveMode,findAccepted,type EngineHealth,type EngineState} from './engine-api';
const MODE_KEY='yue2-workspace-mode-v1';
const EMPTY:EngineState={runs:[],tracks:[],queuePaused:false,eventCursor:0};
export function useEngine(){
  const [preference,setPreference]=useState<'live'|'demo'>(()=>{try{return localStorage.getItem(MODE_KEY)==='demo'?'demo':'live'}catch{return 'live'}});
  const [health,setHealth]=useState<EngineHealth|null>(null),[state,setState]=useState(EMPTY),[online,setOnline]=useState(false),[error,setError]=useState('正在连接本地引擎…');
  const generation=useRef(0),mounted=useRef(true);
  const refresh=useCallback(async()=>{const turn=++generation.current;try{const [h,s]=await Promise.all([api<EngineHealth>('/health'),api<EngineState>('/state')]);if(!h.profile||!Array.isArray(s.runs)||!Array.isArray(s.tracks))throw new Error('引擎数据格式不正确。');if(!mounted.current||turn!==generation.current)return;setHealth(h);setState(old=>old.eventCursor===s.eventCursor&&JSON.stringify(old)===JSON.stringify(s)?old:s);setOnline(true);setError('')}catch(e){if(!mounted.current||turn!==generation.current)return;setOnline(false);setError(e instanceof Error?e.message:'本地引擎连接中断。')}},[]);
  useEffect(()=>{mounted.current=true;let stopped=false;let timer:ReturnType<typeof setTimeout>;const poll=async()=>{await refresh();if(!stopped)timer=setTimeout(poll,1000)};void poll();return()=>{stopped=true;mounted.current=false;clearTimeout(timer)}},[refresh]);
  const setMode=(value:'live'|'demo')=>{setPreference(value);try{localStorage.setItem(MODE_KEY,value)}catch{/* Session preference still works. */}if(value==='live')void refresh()};
  return {health,state,online,error,refresh,mode:effectiveMode(preference,online),setMode,findAccepted};
}
