import {useEffect,useRef,useState,type WheelEvent} from 'react';
import {AnimatePresence,motion} from 'motion/react';
import {SelectControl} from './select-control';
import {CopyIcon,RetryIcon,SettingsIcon,SparkleIcon,CheckIcon,SpinnerIcon} from './icons';
import './style-chat.css';

type ChatKind='style'|'lyrics'|'abc';
export type ChatProvider='qwen'|'deepseek';
type Message={id:string;role:'user'|'assistant';text:string;reasoning?:string;state?:'pending'|'done'|'stopped'|'error';error?:string;outputKind?:ChatKind};
type ApplyRequest={text:string;target:ChatKind};
type ReferenceTexts={style?:string;lyrics?:string;abc?:string};
const PROVIDER_META={
 qwen:{model:'qwen3.8-flash',label:'Qwen3.8-Flash',provider:'阿里云百炼',docsUrl:'https://help.aliyun.com/zh/model-studio/quickstart'},
 deepseek:{model:'deepseek-flash',label:'DeepSeek-Flash',provider:'DeepSeek',docsUrl:'https://api-docs.deepseek.com/zh-cn/'}
} as const;
async function apiError(r:Response){
 if(r.status===404)return '聊天接口尚未加载，请先安全停止并重新启动 YuE2 服务。';
 try{const b=await r.json();return typeof b.detail==='string'?b.detail:'服务暂时不可用，请稍后重试。'}catch{return '服务返回异常（'+r.status+'）'}
}
export function StyleChat({onApply,currentStyle,kind='style',creationMode='quick',referenceTexts={},provider='qwen',onProviderChange=()=>{},active=true}:{onApply:(text:string,target?:ChatKind,append?:boolean)=>void;currentStyle:string;kind?:ChatKind;creationMode?:'quick'|'advanced';referenceTexts?:ReferenceTexts;provider?:ChatProvider;onProviderChange?:(provider:ChatProvider)=>void;active?:boolean}){
 const [messages,setMessages]=useState<Message[]>([]),[input,setInput]=useState(''),[sending,setSending]=useState(false);
 const [configured,setConfigured]=useState(false),[checking,setChecking]=useState(true),[settings,setSettings]=useState(false),[key,setKey]=useState(''),[showKey,setShowKey]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [context,setContext]=useState(true),[apply,setApply]=useState<ApplyRequest|null>(null);
 const abort=useRef<AbortController|null>(null),lock=useRef(false),scroll=useRef<HTMLDivElement>(null),inputRef=useRef<HTMLTextAreaElement>(null),follow=useRef(true);
 const providerMeta=PROVIDER_META[provider];
 const outputLabel=(target:ChatKind)=>target==='lyrics'?'歌词':target==='abc'?'ABC 乐谱':'风格描述';
 const contextLabel=kind==='lyrics'?'当前歌词':kind==='abc'?'当前 ABC 乐谱':'当前风格描述';
 const abcSuggestions=[
  currentStyle.trim()?'保留节奏，重写旋律线':'按歌词生成一段 ABC 旋律',
  currentStyle.trim()?'保留拍号，重做和声进行':'创建主歌与副歌 ABC',
  currentStyle.trim()?'按这段 ABC 节奏写歌词':'生成可直接编辑的 ABC 乐谱',
  '自动检查并修复 ABC 乐谱','调整到适合演唱的人声音域','转调或调整速度并保持旋律关系',
  '扩写前奏、间奏和尾奏','生成更抓耳的 Hook 变体','让现有歌词贴合音符与重音',
  '简化或丰富旋律细节','根据 Vocal 生成 Ins 伴奏声部'
 ];
 const lyricsSuggestions=currentStyle.trim()?[
  '生成押韵的韩语 K-pop 歌词','写一个抓耳的中文流行副歌','生成中韩双语的流行歌词',
  '按主歌、预副歌、副歌重组结构','保留主题，强化押韵与画面感','按当前节奏重新分句并标注重音',
  '加入 Bridge 转折与情绪推进','压缩成短句密集、容易演唱的版本','强化重复钩子，让副歌更容易记住',
  '改成更自然、更口语化的表达','保留主题，写一版克制的叙事歌词','让每段字数更均衡，方便演唱'
 ]:[
  '生成押韵的韩语 K-pop 歌词','写一个抓耳的中文流行副歌','生成中韩双语的流行歌词',
  '按主歌、预副歌、副歌写完整结构','写一版有画面感的中文叙事歌词','写成押韵更密的短句',
  '加入 Bridge 转折与情绪推进','压缩成短句密集、容易演唱的版本','强化重复钩子，让副歌更容易记住',
  '改成更自然、更口语化的表达','先写抓耳副歌，再补主歌','设计一个适合舞曲编排的流行歌词'
 ];
 const styleSuggestions=currentStyle.trim()?[
  '强化当前风格的节奏与动态','保留风格方向，重做配器层次','把情绪和空间感写得更明确',
  '压缩成一条可直接生成的提示','提取核心乐器与音色关键词','重排能量曲线，让段落更有起伏',
  '增加电影化空间与混音画面','改成更适合短视频开场的版本','生成更克制的低配器版本',
  '生成更大胆的实验版本','保留主旨，做成纯音乐 BGM','保留配器，改成适合人声演唱'
 ]:[
  '设计一段电影感战斗 BGM','做成温暖的原声流行','写一条纯音乐生成描述',
  '设计有明确起伏的情绪曲线','做成适合短视频开场的音乐','设计一版极简留白的编曲',
  '做成有记忆点的副歌风格','生成适合人声演唱的风格描述','融合中式乐器与现代节奏',
  '设计夜晚或雨天的氛围音乐','写一个可循环的背景音乐版本','做一版更电影化的空间混音'
 ];
 const suggestions=kind==='lyrics'?lyricsSuggestions:kind==='abc'?abcSuggestions:styleSuggestions;
 const textAdditions=kind==='style'?[{label:'添加歌词',sourceLabel:'当前歌词',text:referenceTexts.lyrics}]:kind==='lyrics'&&creationMode==='advanced'?[{label:'添加 ABC 乐谱',sourceLabel:'当前 ABC 乐谱',text:referenceTexts.abc}]:kind==='abc'?[{label:'添加歌词',sourceLabel:'当前歌词',text:referenceTexts.lyrics},{label:'添加风格',sourceLabel:'当前风格',text:referenceTexts.style}]:[];
 useEffect(()=>{if(!active)return;let alive=true;setChecking(true);setError('');setNotice('');setKey('');setShowKey(false);void fetch('/api/v1/chat/config?provider='+provider).then(async r=>{if(!r.ok)throw Error(await apiError(r));return r.json()}).then(x=>{if(alive){setConfigured(x.configured);setSettings(!x.configured)}}).catch(e=>{if(alive){setError(e.message);setSettings(true)}}).finally(()=>{if(alive)setChecking(false)});return()=>{alive=false}},[provider,active]);
 useEffect(()=>{if(follow.current&&scroll.current)scroll.current.scrollTop=scroll.current.scrollHeight},[messages]);
 async function saveKey(){if(!key.trim()||saving)return;setSaving(true);setError('');try{const r=await fetch('/api/v1/chat/config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider,apiKey:key.trim()})});if(!r.ok)throw Error(await apiError(r));setKey('');setConfigured(true);setSettings(false);setNotice(`${providerMeta.provider} API Key 已保存到本机。`)}catch(e){setError((e as Error).message)}finally{setSaving(false)}}
 async function clearKey(){setSaving(true);setError('');try{const r=await fetch('/api/v1/chat/config',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({provider})});if(!r.ok)throw Error(await apiError(r));const x=await r.json();setConfigured(x.configured);setNotice(x.configured?`${providerMeta.provider} 的本机密钥已清除，环境变量仍提供密钥。`:`${providerMeta.provider} 本机密钥已清除。`)}catch(e){setError((e as Error).message)}finally{setSaving(false)}}
 async function send(history=messages,text=input.trim()){
  if(!text||lock.current||!configured)return;lock.current=true;follow.current=true;setSending(true);setInput('');setError('');setNotice('');
  const user:Message={id:crypto.randomUUID(),role:'user',text},reply:Message={id:crypto.randomUUID(),role:'assistant',text:'',reasoning:'',state:'pending'};
  setMessages([...history,user,reply]);const controller=new AbortController();abort.current=controller;
  const update=(patch:Partial<Message>)=>setMessages(old=>old.map(m=>m.id===reply.id?{...m,...patch}:m));
  let answer='',reasoning='',complete=false;
  try{
   const clean=history.filter(m=>m.role==='user'||m.state==='done').slice(-20).map(m=>({role:m.role,content:m.text}));
   const r=await fetch('/api/v1/chat/completions',{method:'POST',headers:{'Content-Type':'application/json'},signal:controller.signal,body:JSON.stringify({provider,model:providerMeta.model,messages:[...clean,{role:'user',content:text}],style:kind==='style'&&context?currentStyle:'',context:context?currentStyle:'',kind})});
   if(!r.ok){const message=await apiError(r);if(r.status===412){setConfigured(false);setSettings(true)}throw Error(message)}if(!r.body)throw Error('没有收到回复流。');
   const reader=r.body.getReader(),decoder=new TextDecoder();let buffer='';
   try{while(true){const part=await reader.read();buffer+=decoder.decode(part.value??new Uint8Array(),{stream:!part.done});let end;
    while((end=buffer.indexOf('\n\n'))>=0){const frame=buffer.slice(0,end);buffer=buffer.slice(end+2);for(const line of frame.split('\n')){if(!line.startsWith('data: '))continue;const event=JSON.parse(line.slice(6));if(event.type==='error')throw Error(event.message);if(event.type==='done')complete=true;if(event.type==='reasoning'){reasoning+=event.text;update({reasoning})}if(event.type==='content'){answer+=event.text;update({text:answer})}}}
    if(part.done)break;
   }}finally{await reader.cancel().catch(()=>{});reader.releaseLock()}
   if(!complete)throw Error('连接中断，已保留收到的内容。');
   let normalized=answer.trim(),outputKind:ChatKind=kind;
   try{
    const parsed=JSON.parse(normalized.replace(/^```(?:json)?\s*|\s*```$/g,''));
    const wantsLyrics=kind==='abc'&&/歌词|填词|作词/.test(text);
    const candidates:ChatKind[]=kind==='abc'?(wantsLyrics?['lyrics','abc']:['abc','lyrics']):[kind];
    for(const candidate of candidates){const value=parsed[candidate];if(typeof value==='string'&&value.trim()){normalized=value.trim();outputKind=candidate;break}}
   }catch{}
   if(!normalized)throw Error('模型没有返回正文，请重试。');update({text:normalized,state:'done',outputKind});
  }catch(e){update(controller.signal.aborted?{state:'stopped'}:{state:'error',error:(e as Error).message})}finally{lock.current=false;setSending(false);abort.current=null}
 }
 function retry(index:number){const previous=messages.slice(0,index);let user=-1;for(let i=previous.length-1;i>=0;i--){if(previous[i].role==='user'){user=i;break}}if(user>=0)void send(previous.slice(0,user),previous[user].text)}
 function applyText(text:string,append=false,target:ChatKind=kind){const existing=target===kind?currentStyle.trim():'';onApply(append&&existing?existing+'\n'+text:text,target,append);setApply(null);setNotice(`已应用到${outputLabel(target)}。`)}
 function addReference(sourceLabel:string,text?:string){const value=text?.trim();if(!value){setNotice(`${sourceLabel}暂无可添加内容。`);return}const block=`【${sourceLabel}】\n${value}`;setInput(previous=>{const separator=previous.trim()?'\n\n':'';return `${previous.trimEnd()}${separator}${block}`});setNotice(`已将${sourceLabel}添加到输入框。`);requestAnimationFrame(()=>inputRef.current?.focus())}
 function scrollSuggestions(event:WheelEvent<HTMLDivElement>){
  const area=event.currentTarget;if(area.scrollWidth<=area.clientWidth)return;
  const delta=Math.abs(event.deltaX)>Math.abs(event.deltaY)?event.deltaX:event.deltaY;if(!delta)return;
  const next=Math.max(0,Math.min(area.scrollWidth-area.clientWidth,area.scrollLeft+delta));
  if(next===area.scrollLeft)return;event.preventDefault();area.scrollLeft=next;
 }
 return <div className="style-chat live-chat">
  <div className="chat-controls"><label><span className="chat-field-label">模型</span><SelectControl value={provider} onChange={e=>onProviderChange(e.target.value as ChatProvider)} disabled={sending}><option value="qwen">Qwen3.8-Flash · 阿里云百炼</option><option value="deepseek">DeepSeek-Flash · DeepSeek</option></SelectControl></label><span className={`chat-status ${configured?'ready':''}`}>{checking?'检查配置…':configured?'已配置':'待配置'}</span><button onClick={()=>setSettings(v=>!v)} disabled={sending}><SettingsIcon size={16}/>{configured?'配置密钥':'设置 API Key'}</button><button disabled={sending||!messages.length} onClick={()=>{setMessages([]);setNotice('已清空本次对话')}}>清空对话</button></div>
  {sending&&<div className="chat-running-note" role="status"><SpinnerIcon size={15} className="spin"/>正在生成中，收起窗口后任务会继续；重新打开即可查看。</div>}
  <AnimatePresence initial={false}>{settings&&<motion.section key="config" initial={{height:0,opacity:0}} animate={{height:'auto',opacity:1}} exit={{height:0,opacity:0}} className="chat-config-wrap"><div className="style-chat-config"><strong>{configured?`更换${providerMeta.provider} API Key`:`连接${providerMeta.provider}`}</strong><p>密钥只保存在本机。发送消息时，内容会传给{providerMeta.provider}的 {providerMeta.label}。</p><div><input aria-label={`${providerMeta.provider} API Key`} type={showKey?'text':'password'} autoComplete="off" value={key} onChange={e=>setKey(e.target.value)} placeholder={configured?'输入新密钥以替换':'粘贴 API Key'}/><button onClick={()=>setShowKey(v=>!v)}>{showKey?'隐藏':'显示'}</button><button disabled={saving||!key.trim()} onClick={()=>void saveKey()}>{saving?'保存中…':'保存密钥'}</button></div><div className="chat-config-actions"><a href={providerMeta.docsUrl} target="_blank" rel="noreferrer">打开{providerMeta.provider}文档</a>{configured&&<button disabled={saving} onClick={()=>void clearKey()}>清除本机密钥</button>}</div></div></motion.section>}</AnimatePresence>
  {error&&<div role="alert" className="chat-error">{error}</div>}{notice&&<div role="status" className="chat-notice">{notice}</div>}
  <div className="chat-messages" ref={scroll} onScroll={e=>{const el=e.currentTarget;follow.current=el.scrollHeight-el.scrollTop-el.clientHeight<60}} aria-live="polite">
   {!messages.length&&<div className="chat-welcome"><span className="chat-eyebrow">{kind==='lyrics'?'歌词结构工作台':kind==='abc'?'ABC 乐谱工作台':'风格描述工作台'}</span><h3>{kind==='lyrics'?'从一句歌词开始':kind==='abc'?'从一段乐谱开始':'从一句想法开始'}</h3><p>{kind==='lyrics'?'描述要保留、删除或改写的歌词，我会按 YuE2 官方段落结构整理。':kind==='abc'?'告诉我保留节奏、改写旋律，或按这段节奏写歌词。':'描述场景、情绪、速度和乐器，我会把它整理成可直接生成的风格描述。'}</p>{currentStyle.trim()&&<div className="chat-context-card"><span>{kind==='lyrics'?'正在参考当前歌词':kind==='abc'?'正在参考当前 ABC 乐谱':'正在参考当前风格'}</span><p>{currentStyle}</p></div>}</div>}
   {messages.map((m,i)=><motion.article initial={{opacity:0,y:5}} animate={{opacity:1,y:0}} className={'chat-message '+m.role} key={m.id}>
    {m.role==='assistant'&&(m.reasoning||m.state==='pending')&&<details className="chat-reasoning"><summary>{m.state==='pending'&&!m.text?'正在思考…':'思考过程'}</summary><p>{m.reasoning||'正在连接模型…'}</p></details>}
    {m.text&&<p>{m.text}</p>}{m.state==='error'&&<p className="chat-error" role="alert">{m.error}</p>}{m.state==='stopped'&&<small>已停止，收到的内容已保留。</small>}
    {m.role==='assistant'&&m.state!=='pending'&&<div className="chat-message-actions">{m.text&&<button onClick={()=>void navigator.clipboard.writeText(m.text).then(()=>setNotice('已复制')).catch(()=>setNotice('复制失败，请手动选择文本'))}><CopyIcon size={15}/>复制</button>}{m.state==='done'&&<button onClick={()=>{const target=m.outputKind??kind;if(target===kind&&currentStyle.trim())setApply({text:m.text,target});else applyText(m.text,false,target)}}><CheckIcon size={15}/>应用到{outputLabel(m.outputKind??kind)}</button>}<button disabled={sending} onClick={()=>retry(i)}><RetryIcon size={15}/>重试</button></div>}
   </motion.article>)}
  </div>
  {apply!==null&&<div className="chat-apply" role="group" aria-label="应用方式"><span>你已有{outputLabel(apply.target)}，选择如何处理这条结果</span><button onClick={()=>applyText(apply.text,false,apply.target)}>替换</button><button onClick={()=>applyText(apply.text,true,apply.target)}>追加</button><button onClick={()=>setApply(null)}>取消</button></div>}
  {!messages.length&&<section className="style-chat-suggestions" aria-label="快速开始"><span className="suggestions-label">快速开始</span><div onWheel={scrollSuggestions} aria-label="快速开始建议，滚轮可横向浏览">{suggestions.map(s=><button key={s} title={s} onClick={()=>setInput(s)}>{s}</button>)}</div></section>}
  <div className="chat-input"><textarea ref={inputRef} aria-label="聊天消息" value={input} maxLength={12000} onChange={e=>setInput(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();void send()}}} placeholder={currentStyle.trim()?'告诉我想保留、删除或改变什么…':kind==='lyrics'?'描述要写什么歌词或如何整理…':kind==='abc'?'告诉我如何改写乐谱，或按这段节奏写歌词…':'描述场景、情绪、速度或乐器…'}/><div><label><input type="checkbox" checked={context&&Boolean(currentStyle.trim())} disabled={sending||!currentStyle.trim()} onChange={e=>setContext(e.target.checked)}/>{kind==='lyrics'?'参考当前歌词':kind==='abc'?'参考当前 ABC 乐谱':'参考当前风格'}</label><div className="chat-input-additions" aria-label="添加相关文本">{textAdditions.map(action=><button type="button" key={action.label} disabled={sending||!action.text?.trim()} title={action.text?.trim()?`添加${action.sourceLabel}`:`${action.sourceLabel}暂无内容`} onClick={()=>addReference(action.sourceLabel,action.text)}>{action.label}</button>)}</div><span>{context&&currentStyle.trim()?`会在当前${kind==='lyrics'?'歌词':kind==='abc'?'ABC 乐谱':'描述'}上调整`:'从空白开始'} · Enter 发送 · Shift+Enter 换行</span><button disabled={!sending&&(!input.trim()||!configured||checking)} onClick={()=>sending?abort.current?.abort():void send()}>{sending?<><SpinnerIcon size={16}/>停止</>: '发送'}</button></div></div>
 </div>
}
