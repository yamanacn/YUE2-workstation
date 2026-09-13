import {useSyncExternalStore} from 'react';
import type {Track} from './domain';
type Playback={trackId:string|null;playing:boolean;loading:boolean;current:number;duration:number;volume:number;error:string|null};
let state:Playback={trackId:null,playing:false,loading:false,current:0,duration:203.52,volume:.7,error:null};
const listeners=new Set<()=>void>();
let audio:HTMLAudioElement|null=null;
let token=0;
function publish(patch:Partial<Playback>){state={...state,...patch};listeners.forEach(fn=>fn())}
function getAudio(){
  if(audio)return audio;
  audio=new Audio();audio.preload='metadata';audio.volume=.7;
  audio.addEventListener('timeupdate',()=>publish({current:audio?.currentTime??0}));
  audio.addEventListener('loadedmetadata',()=>publish({duration:audio?.duration??0,loading:false}));
  audio.addEventListener('playing',()=>publish({playing:true,loading:false,error:null}));
  audio.addEventListener('pause',()=>publish({playing:false}));
  audio.addEventListener('waiting',()=>{if(!audio?.paused)publish({loading:true})});
  audio.addEventListener('ended',()=>publish({playing:false,loading:false}));
  audio.addEventListener('error',()=>publish({playing:false,loading:false,error:'音频暂时无法读取，请重试或重新定位文件。'}));
  return audio;
}
export const playback={
  subscribe(fn:()=>void){listeners.add(fn);return()=>{listeners.delete(fn)}},getState:()=>state,
  async play(track:Track){
    if(track.missing){publish({error:'音频文件不可用，请重新定位。'});return}
    const a=getAudio(),turn=++token;
    if(state.trackId===track.id&&!a.paused){a.pause();return}
    if(state.trackId!==track.id||a.getAttribute('src')!==track.audioUrl){a.pause();a.src=track.audioUrl;publish({trackId:track.id,current:0,duration:track.duration,loading:true,error:null})}
    try{await a.play();if(turn!==token)return}catch(e){if(turn!==token)return;publish({playing:false,loading:false,error:e instanceof Error&&e.name==='NotAllowedError'?'请再次点击播放，以开始试听。':'音频读取失败，请检查文件。'})}
  },
  pause(){getAudio().pause()},
  stop(){token++;getAudio().pause();getAudio().removeAttribute('src');getAudio().load();publish({trackId:null,current:0,playing:false,loading:false,error:null})},
  seek(time:number){const a=getAudio();if(Number.isFinite(a.duration))a.currentTime=Math.max(0,Math.min(a.duration,time));publish({current:Math.max(0,time)})},
  volume(volume:number){getAudio().volume=volume;publish({volume})},
  clearError(){publish({error:null})}
};
export function usePlayback(){return useSyncExternalStore(playback.subscribe,playback.getState,playback.getState)}
const peakCache=new Map<string,Promise<number[]>>();
export function getPeaks(url:string):Promise<number[]>{
  let pending=peakCache.get(url);if(pending)return pending;
  pending=(async()=>{const response=await fetch(url);if(!response.ok)throw new Error('Audio fetch failed');const bytes=await response.arrayBuffer();const ctx=new AudioContext({sampleRate:48000});try{const buffer=await ctx.decodeAudioData(bytes);const channel=buffer.getChannelData(0),size=260,step=Math.ceil(channel.length/size);const peaks=Array.from({length:size},(_,i)=>{let sum=0,count=0;for(let j=i*step;j<Math.min(channel.length,(i+1)*step);j+=24){sum+=channel[j]*channel[j];count++}return Math.sqrt(sum/Math.max(1,count))});const max=Math.max(...peaks,.01);return peaks.map(n=>n/max)}finally{await ctx.close()}})();
  peakCache.set(url,pending);pending.catch(()=>peakCache.delete(url));return pending;
}
export async function exportWav(url:string):Promise<Blob>{
  const response=await fetch(url);if(!response.ok)throw new Error('无法读取原始音频');
  const ctx=new AudioContext({sampleRate:48000});
  try{const buffer=await ctx.decodeAudioData(await response.arrayBuffer()),channels=buffer.numberOfChannels,frames=buffer.length;
    const array=new ArrayBuffer(44+frames*channels*2),v=new DataView(array);const ascii=(offset:number,s:string)=>{for(let i=0;i<s.length;i++)v.setUint8(offset+i,s.charCodeAt(i))};
    ascii(0,'RIFF');v.setUint32(4,array.byteLength-8,true);ascii(8,'WAVE');ascii(12,'fmt ');v.setUint32(16,16,true);v.setUint16(20,1,true);v.setUint16(22,channels,true);v.setUint32(24,buffer.sampleRate,true);v.setUint32(28,buffer.sampleRate*channels*2,true);v.setUint16(32,channels*2,true);v.setUint16(34,16,true);ascii(36,'data');v.setUint32(40,frames*channels*2,true);
    const planes=Array.from({length:channels},(_,i)=>buffer.getChannelData(i));let offset=44;
    for(let i=0;i<frames;i++)for(let c=0;c<channels;c++){const n=Math.max(-1,Math.min(1,planes[c][i]));v.setInt16(offset,n<0?n*32768:n*32767,true);offset+=2}
    return new Blob([array],{type:'audio/wav'});
  }finally{await ctx.close()}
}
