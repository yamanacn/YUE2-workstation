import {ScoreWorkspace} from './score-workspace';
import {MusicNotesIcon,SparkleIcon} from './icons';
import {EditorResizeHandle} from './editor-resize-handle';
import {motionTransition} from './motion-system';
import {GeneratingTrack} from './generating-track';
import type {ReferenceSource} from './domain';
import {WorkspaceDivider} from './workspace-divider';
import {ReferenceAudioCard,type ReferenceAudio,type TranscriptionState} from './reference-audio';
import {AdvancedSettings,CreativePreferences} from './advanced-settings';
import {StyleChat,type ChatProvider} from './style-chat';
import {useCallback,useEffect,useMemo,useRef,useState,type ChangeEvent,type WheelEvent} from 'react';
import {AnimatePresence,MotionConfig,motion} from 'motion/react';
import * as Menu from '@radix-ui/react-dropdown-menu';
import {ThemeContext,readTheme,THEME_KEY,type Theme} from './theme';
import {Button,IconButton,PlaybackError,Player,Sheet,Toast,TrackMenu,type Notice} from './components';
import {DetailPanel,type DetailTarget,type RunActions,type TrackActions} from './track-detail';
import {originalExtension,sourceLabel,runProgress,activeStates,cloneDraft,configChanges,createBatch,defaultConfig,draftForCreationMode,formatDate,formatTime,initialDraft,makeSamples,recoverState,safeFilename,stageLabels,terminalStates,trackFromRun,transitionRun,uid,validateDraft,type Config,type CreationMode,type Draft,type Run,type SavedState,type Stage,type Track} from './domain';
import {exportWav,playback,usePlayback} from './audio';
import {useEngine} from './use-engine';
import {api,ApiError,readPending,sendPending,PENDING_KEY,type PendingRequest} from './engine-api';
import {CaretDownIcon,CaretRightIcon,SunIcon,MoonIcon,CheckIcon,ClockIcon,CodeIcon,CopyIcon,DownloadIcon,ExpandIcon,FadersIcon,FileAudioIcon,FolderIcon,MoreIcon,PauseIcon,PencilIcon,PlayIcon,QueueIcon,RetryIcon,SearchIcon,SettingsIcon,SortIcon,SpinnerIcon,StarIcon,TrashIcon,UndoIcon,WarningIcon,WaveformIcon,XIcon} from './icons';
const STORAGE_KEY='yue2-silver-mist-v1';
const CHAT_PROVIDER_KEY='yue2-chat-provider-v1';
function readState(){
  try{
    const state=recoverState(JSON.parse(localStorage.getItem(STORAGE_KEY)??'null'));
    const migration='yue2-official-budget-9000-v1';
    if(localStorage.getItem(migration)!=='done'){
      if(state){state.draft.config.maxTokens=defaultConfig.maxTokens;localStorage.setItem(STORAGE_KEY,JSON.stringify(state))}
      localStorage.setItem(migration,'done');
    }
    return state;
  }catch{return null}
}
function referenceSignature(source?:ReferenceSource){return source?JSON.stringify([source.id,source.range??null,source.preserve,source.strength??'balanced']):''}
type Confirmation={title:string;description:string;label:string;danger?:boolean;action:()=>void};
type Panel='queue'|'settings'|'advanced'|'details'|'style-chat'|'lyrics-chat'|'abc-chat'|null;
export function App(){
  const [module,setModule]=useState<'create'|'score'>(()=>localStorage.getItem('yue2-module')==='score'?'score':'create');
  const [scoreActive,setScoreActive]=useState(0);
  useEffect(()=>{localStorage.setItem('yue2-module',module)},[module]);
  const playbackState=usePlayback();
  const [referenceVersion,setReferenceVersion]=useState(0);
  const [missingReference,setMissingReference]=useState<ReferenceSource|null>(null);
  const [reference,setReference]=useState<ReferenceAudio|null>(null);
  const [referenceBusy,setReferenceBusy]=useState(false);
  const [referenceAdding,setReferenceAdding]=useState(false);
  const [detailOpen,setDetailOpen]=useState(false);
  const [advancedTranscription,setAdvancedTranscription]=useState<TranscriptionState>({status:'idle'});
  const [saved]=useState(readState);
  const [theme,setTheme]=useState<Theme>(readTheme);
  const [lyricsCollapsed,setLyricsCollapsed]=useState(false),[styleCollapsed,setStyleCollapsed]=useState(false);
  const [creationMode,setCreationMode]=useState<'quick'|'advanced'>('quick');
  const [chatProvider,setChatProvider]=useState<ChatProvider>(()=>localStorage.getItem(CHAT_PROVIDER_KEY)==='deepseek'?'deepseek':'qwen');
  useEffect(()=>{localStorage.setItem(CHAT_PROVIDER_KEY,chatProvider)},[chatProvider]);
  useEffect(()=>{document.documentElement.dataset.theme=theme;document.querySelector('meta[name="theme-color"]')?.setAttribute('content',theme==='dark'?'#101012':'#f1f0ef');try{localStorage.setItem(THEME_KEY,theme)}catch{/* Theme remains usable for this session. */}},[theme]);
  const [draft,setDraft]=useState<Draft>(saved?.draft??cloneDraft(initialDraft));
  const [demoTracks,setTracks]=useState<Track[]>(saved?.tracks??makeSamples());
  const [demoRuns,setRuns]=useState<Run[]>(saved?.runs??[]);
  const [demoPaused,setPaused]=useState(saved?.paused??false);
  const [playerTrack,setPlayerTrack]=useState<Track>((saved?.tracks??makeSamples()).find(t=>!t.removed)??makeSamples()[0]);
  const [panel,setPanel]=useState<Panel>(null),[detailRecord,setDetailTrack]=useState<Track|null>(null),[detailRunRecord,setDetailRunRecord]=useState<Run|null>(null);
  const [query,setQuery]=useState(''),[filter,setFilter]=useState<'all'|'favorite'|'removed'>('all'),[sort,setSort]=useState<'latest'|'oldest'|'name'>('latest'),[manage,setManage]=useState(false),[batch,setBatch]=useState<string[]>([]);
  const [mobilePanel,setMobilePanel]=useState<'composer'|'library'>('library');
  const [notice,setNotice]=useState<Notice|null>(null),[confirmation,setConfirmation]=useState<Confirmation|null>(null);
  const engine=useEngine();
  const {mode,setMode}=engine;
  const tracks=mode==='demo'?demoTracks:engine.state.tracks,runs=mode==='demo'?demoRuns:engine.state.runs,paused=mode==='demo'?demoPaused:engine.state.queuePaused;
  const [pending,setPending]=useState<PendingRequest|null>(readPending);
  const pendingRef=useRef(pending);
  const [settingsTab,setSettingsTab]=useState<'engine'|'appearance'|'storage'|'demo'|'about'>('engine');
  const detailTrack=tracks.find(t=>t.id===detailRecord?.id)??detailRecord;
  const detailRun=runs.find(r=>r.id===detailRunRecord?.id)??detailRunRecord;
  const [reduced,setReduced]=useState(false),[solid,setSolid]=useState(false),[nextOutcome,setNextOutcome]=useState<'success'|'fail'|'warning'>('success');
  useEffect(()=>{document.documentElement.dataset.reducedMotion=String(reduced);return()=>{delete document.documentElement.dataset.reducedMotion}},[reduced]);
  const [saveState,setSaveState]=useState<'saved'|'saving'|'failed'>('saved'),[showRecovery,setShowRecovery]=useState(Boolean(saved?.paused));
  const [errors,setErrors]=useState<{field:string;message:string}[]>([]),[submitting,setSubmitting]=useState(false);
  const [rename,setRename]=useState<Track|null>(null),[newName,setNewName]=useState('');
  const [exportTrack,setExportTrack]=useState<Track|null>(null),[exportFormat,setExportFormat]=useState<'original'|'wav'>('original'),[exportName,setExportName]=useState(''),[exportState,setExportState]=useState<'idle'|'exporting'|'done'|'failed'>('idle'),[exportError,setExportError]=useState('');
  const [newResults,setNewResults]=useState(0),[activeRunDetail,setActiveRunDetail]=useState<Run|null>(null);
  const fileInput=useRef<HTMLInputElement>(null),audioInput=useRef<HTMLInputElement>(null),abcInput=useRef<HTMLInputElement>(null),locateTarget=useRef<Track|null>(null),lyricsRef=useRef<HTMLTextAreaElement>(null),abcFieldRef=useRef<HTMLElement>(null),libraryScroll=useRef<HTMLDivElement>(null),submitLock=useRef(false),submitted=useRef(new Set<string>()),advancedTranscriptionRef=useRef<TranscriptionState>({status:'idle'}),advancedTranscriptionRequest=useRef(0),current=useRef({runs,tracks,draft,paused}),noticeCount=useRef(0),heardDemo=useRef(false);
  current.current={runs:demoRuns,tracks:demoTracks,draft,paused:demoPaused};
  const active=runs.find(r=>activeStates.includes(r.state));
  const queued=useMemo(()=>runs.filter(r=>r.state==='queued'),[runs]);
  const inflight=queued.length+(active?1:0);
  const changed=configChanges(draft.config);
  const selected=detailTrack??tracks.find(t=>!t.removed);
  const toast=useCallback((text:string,action?:()=>void,actionLabel?:string)=>setNotice({id:++noticeCount.current,text,action,actionLabel}),[]);
  useEffect(()=>{if(!notice)return;const timer=setTimeout(()=>setNotice(null),notice.action?7000:4700);return()=>clearTimeout(timer)},[notice]);
  useEffect(()=>{setSaveState('saving');const timer=setTimeout(()=>{try{const data:SavedState={version:1,draft,tracks:demoTracks.map(t=>({...t,audioUrl:t.audioKind==='local'?'':t.audioUrl})),runs:demoRuns,paused:demoPaused};localStorage.setItem(STORAGE_KEY,JSON.stringify(data));setSaveState('saved')}catch{setSaveState('failed')}},800);return()=>clearTimeout(timer)},[draft,demoTracks,demoRuns,demoPaused]);
  useEffect(()=>{const save=()=>{try{localStorage.setItem(STORAGE_KEY,JSON.stringify({version:1,...current.current}))}catch{/* visible persistent failure is handled by autosave */}};window.addEventListener('beforeunload',save);return()=>window.removeEventListener('beforeunload',save)},[]);
  // The demo queue exercises real UI state transitions. It never calls model inference.
  useEffect(()=>{
    if(mode!=='demo'||active?.snapshot.runtime==='local-yue2')return;
    if(!active){if(paused||!queued.length)return;const id=queued[0].id;const timer=setTimeout(()=>setRuns(old=>old.map(r=>r.id===id&&r.state==='queued'?transitionRun(r,'checking'):r)),280);return()=>clearTimeout(timer)}
    const run=active;const path:Stage[]=run.snapshot.draft.config.cot==='off'?['checking','generating_tokens','synthesizing','decoding','finalizing','succeeded']:['checking','planning','generating_tokens','synthesizing','decoding','finalizing','succeeded'];
    const timer=setTimeout(()=>{
      const live=current.current.runs.find(r=>r.id===run.id);if(!live||live.state!==run.state)return;
      let next:Stage=run.state==='cancelling'?'cancelled':path[path.indexOf(run.state)+1]??'failed';
      if(run.state==='synthesizing'&&run.demoOutcome==='fail')next='failed';
      if(next==='succeeded'){
        const result=trackFromRun(run);result.version='V'+String(current.current.tracks.filter(t=>t.title===result.title).length+1).padStart(2,'0');
        if(run.demoOutcome==='warning')result.warning='演示：音乐序列达到预算，结尾可能提前结束。';
        setTracks(old=>old.some(t=>t.runId===run.id)?old:[result,...old]);
        setNewResults(n=>n+1);
        toast('演示流程完成，已新增一个界面样例。');
      }
      setRuns(old=>old.map(r=>r.id===run.id&&r.state===run.state?{...transitionRun(r,next),error:next==='failed'?'演示：当前设备可用显存不足。请查看配置后重试。':r.error}:r));
    },run.state==='cancelling'?850:run.state==='generating_tokens'?3500:run.state==='checking'?650:1600);
    return()=>clearTimeout(timer);
  },[active,queued,paused,mode,toast]);
  const updateDraft=(patch:Partial<Draft>)=>{setDraft(old=>({...old,...patch}));setErrors([])};
  const setAdvancedTranscriptionState=(next:TranscriptionState)=>{advancedTranscriptionRef.current=next;setAdvancedTranscription(next)};
  const transcribeAdvanced=useCallback(async(value:ReferenceAudio|null)=>{
    const source=value?.source;if(!source)return;
    const requestSource={...source,range:value.range,preserve:value.preserve,strength:value.strength};
    const signature=referenceSignature(requestSource),request=++advancedTranscriptionRequest.current;
    setAdvancedTranscriptionState({status:'transcribing',sourceId:source.id,signature});
    try{
      // SheetSage2 loads a local model before transcribing; allow the full
      // worker window instead of the short 10s UI request timeout.
      const result=await api<{abc:string;recommendedCot:'full'|'melody'}>(`/references/${encodeURIComponent(source.id)}/transcribe`,'POST',{range:requestSource.range,preserve:requestSource.preserve,strength:requestSource.strength},{timeoutMs:15*60*1000});
      if(request!==advancedTranscriptionRequest.current)return;
      updateDraft({abc:result.abc,config:{...current.current.draft.config,cot:result.recommendedCot}});
      setAdvancedTranscriptionState({status:'ready',sourceId:source.id,signature});
      requestAnimationFrame(()=>{
        if(request!==advancedTranscriptionRequest.current||advancedTranscriptionRef.current.signature!==signature)return;
        abcFieldRef.current?.scrollIntoView({behavior:reduced?'auto':'smooth',block:'center'});
      });
    }catch(error){
      if(request!==advancedTranscriptionRequest.current)return;
      const rawMessage=error instanceof Error?error.message:'';
      const message=/timed out|timeout/i.test(rawMessage)?'转谱超时，请缩短音频片段或稍后重试。':rawMessage||'ABC 转谱失败，请点击上方「转谱」重试。';
      setAdvancedTranscriptionState({status:'error',sourceId:source.id,signature,message});
    }
  },[reduced]);
  const handleReferenceChange=(value:ReferenceAudio|null)=>{
    setReference(value);
    setDraft(d=>({...d,reference:value?.source?{...value.source,range:value.range,preserve:value.preserve,strength:value.strength}:undefined}));
    if(!value){advancedTranscriptionRequest.current++;setAdvancedTranscriptionState({status:'idle'});return}
    if(creationMode!=='advanced'||!value.source)return;
    const source={...value.source,range:value.range,preserve:value.preserve,strength:value.strength};
    const signature=referenceSignature(source),previous=advancedTranscriptionRef.current;
    if(previous.sourceId!==source.id||previous.signature!==signature){
      advancedTranscriptionRequest.current++;
      setAdvancedTranscriptionState({status:previous.sourceId===source.id&&previous.status==='ready'?'stale':'idle',sourceId:source.id,signature});
    }
  };
  useEffect(()=>{
    if(creationMode==='advanced')return;
    advancedTranscriptionRequest.current++;
    if(advancedTranscriptionRef.current.status!=='idle')setAdvancedTranscriptionState({status:'idle'});
  },[creationMode]);
  const submitLive=useCallback(async(request:PendingRequest)=>{
    if(submitLock.current)return;
    submitLock.current=true;setSubmitting(true);
    // Persist before sending so a page reload can reconcile the same acceptance.
    try{localStorage.setItem(PENDING_KEY,JSON.stringify(request))}catch{toast('无法保存提交编号，请检查浏览器存储后再试。');submitLock.current=false;setSubmitting(false);return}
    pendingRef.current=request;setPending(request);
    try{const batch=await sendPending(request);localStorage.removeItem(PENDING_KEY);pendingRef.current=null;setPending(null);toast(`已加入本机队列 · ${batch.runs.length} 首`);await engine.refresh()}
    catch(error){if(error instanceof ApiError&&error.status>=400&&error.status<500){localStorage.removeItem(PENDING_KEY);pendingRef.current=null;setPending(null);toast(error.message)}else toast('提交结果尚未确认。保留了原请求，可查询并继续提交。')}
    finally{submitLock.current=false;setSubmitting(false)}
  },[engine.refresh,toast]);
  useEffect(()=>{if(!pending||!engine.online||submitting)return;let cancelled=false;void engine.findAccepted(pending.body.requestId).then(result=>{if(result&&!cancelled&&pendingRef.current?.body.requestId===result.requestId){localStorage.removeItem(PENDING_KEY);pendingRef.current=null;setPending(null);toast('已确认上次提交，任务保留在本机队列。');void engine.refresh()}}).catch(()=>{});return()=>{cancelled=true}},[pending,engine.online,engine.state.eventCursor,submitting,engine.refresh,toast]);
  const submit=useCallback((input?:Draft,seeds?:string[],parentId?:string,modeOverride?:CreationMode)=>{
    if(submitLock.current)return;
    if(!input&&referenceBusy){toast('参考音频正在读取，请稍候。');return}
    if(mode==='offline'){setSettingsTab('engine');setPanel('settings');return}
    if(mode==='live'&&pendingRef.current){toast('上一份提交结果尚未确认，请先查询原请求。');return}
    const submissionMode=modeOverride??creationMode;
    if(!input&&submissionMode==='advanced'&&reference&&(advancedTranscription.status==='transcribing'||advancedTranscription.status==='stale')){toast(advancedTranscription.status==='transcribing'?'参考音频正在提取 ABC，请稍候。':'参考音频设置已变化，请先重新提取 ABC。');return}
    if(!input&&submissionMode==='advanced'&&reference&&advancedTranscription.status==='error'&&!current.current.draft.abc?.trim()){toast('参考音频提取 ABC 失败，请重试或移除参考音频。');return}
    const d={...draftForCreationMode(input??current.current.draft,submissionMode),count:1 as const},problems=validateDraft(d);
    if(problems.length){setErrors(problems);setLyricsCollapsed(false);setStyleCollapsed(false);if(problems[0].field==='config')setPanel('advanced');else{setMobilePanel('composer');requestAnimationFrame(()=>document.getElementById('field-'+problems[0].field)?.focus())}return}
    const requestId=uid();
    if(mode==='live'){void submitLive({path:'/batches',body:{requestId,draft:d,creationMode:submissionMode,...(seeds?{resolvedSeeds:seeds}:{}),...(parentId?{parentTrackId:parentId}:{})}});return}
    submitLock.current=true;setSubmitting(true);
    setTimeout(()=>{if(!submitted.current.has(requestId)){submitted.current.add(requestId);const batch=createBatch(d,requestId,seeds,parentId).map((r,i)=>({...r,demoOutcome:i===0?nextOutcome:'success' as const}));setNextOutcome('success');setRuns(old=>[...old,...batch]);toast(`已加入演示队列 · 依次运行 ${batch.length} 首`)}submitLock.current=false;setSubmitting(false)},240);
  },[mode,creationMode,toast,nextOutcome,submitLive,reference,referenceBusy,advancedTranscription]);
  useEffect(()=>{const onKey=(e:KeyboardEvent)=>{const target=e.target as HTMLElement;if(e.isComposing||panel||confirmation||rename||exportTrack)return;if(e.ctrlKey&&e.key==='Enter'&&target.closest('.composer')){e.preventDefault();submit()}if(e.code==='Space'&&!target.closest('input,textarea,select,button,[contenteditable]')){e.preventDefault();if(!playerTrack.missing)void playback.play(playerTrack)}};window.addEventListener('keydown',onKey);return()=>window.removeEventListener('keydown',onKey)},[submit,panel,confirmation,rename,exportTrack,playerTrack]);
  const visibleTracks=useMemo(()=>{const text=query.toLocaleLowerCase();const filtered=tracks.filter(t=>(filter==='removed'?t.removed:!t.removed)&&(filter!=='favorite'||t.favorite)&&`${t.title} ${t.style} ${t.lyrics}`.toLocaleLowerCase().includes(text));return filtered.sort((a,b)=>sort==='name'?a.title.localeCompare(b.title,'zh-CN'):sort==='oldest'?Date.parse(a.created)-Date.parse(b.created):Date.parse(b.created)-Date.parse(a.created))},[tracks,query,filter,sort]);
  const mutate=async(path:string,method:string,body?:unknown)=>{try{await api(path,method,body);await engine.refresh();return true}catch(error){toast(error instanceof Error?error.message:'操作未完成，请重试。');return false}};
  const patchTrack=async(id:string,patch:Partial<Track>)=>{
    const target=engine.state.tracks.find(t=>t.id===id);
    if(target){if(!await mutate(`/tracks/${encodeURIComponent(id)}`,'PATCH',patch))return false}
    else setTracks(old=>old.map(t=>t.id===id?{...t,...patch}:t));
    setPlayerTrack(t=>t.id===id?{...t,...patch}:t);return true;
  };
  const favorite=(t:Track)=>{void patchTrack(t.id,{favorite:!t.favorite})};
  const play=(t:Track)=>{if(t.missing){locate(t);return}setPlayerTrack(t);void playback.play(t);if(t.audioKind==='official-demo'&&!heardDemo.current){heardDemo.current=true;toast('试听音频为 YuE2 官方示例《今晚不眠》；页面标题与歌词用于界面展示。')}};
  const reuse=(t:Track)=>{const next={...cloneDraft(t.snapshot.draft),title:t.title,lyrics:t.lyrics,style:t.style};const apply=()=>{const before=cloneDraft(current.current.draft);setReference(null);setReferenceVersion(v=>v+1);setDraft(next);setPanel(null);setMobilePanel('composer');toast('已将作品参数放入创作区。',()=>setDraft(before),'撤销')};if(draft.lyrics.trim()||draft.style.trim())setConfirmation({title:'将这首作品放入创作区？',description:'当前歌词、风格与参数将被替换。替换后可以撤销。',label:'替换草稿',action:apply});else apply()};
  const regenerate=(t:Track)=>{if(t.audioKind==='generated'&&mode==='demo'){toast('请先切换到本机生成工作区。');setSettingsTab('engine');setPanel('settings');return}const source=cloneDraft(t.snapshot.draft);submit({...source,title:t.title,count:1,seedMode:'random'},undefined,t.id,source.abc?.trim()?'advanced':'quick');setPanel(null)};
  const remove=async(t:Track)=>{setConfirmation({title:'永久删除作品？',description:`将删除「${t.title}」及本地音频、参数和日志，无法恢复。`,label:'永久删除',action:async()=>{await mutate(`/tracks/${encodeURIComponent(t.id)}`,'DELETE');toast('作品已永久删除。')}})};
  const restore=async(t:Track)=>{if(!await patchTrack(t.id,{removed:false}))return;toast('作品记录已恢复。')};
  const toggleBatch=(id:string)=>setBatch(old=>old.includes(id)?old.filter(x=>x!==id):[...old,id]);
  const downloadBatch=()=>{tracks.filter(t=>batch.includes(t.id)&&!t.missing).forEach((t,i)=>setTimeout(()=>{const a=document.createElement('a');a.href=t.audioUrl;a.download=safeFilename(t.title||'音乐')+'.'+originalExtension(t);a.click()},i*180));toast(`已开始下载 ${batch.length} 首音乐。`)};
  const removeBatch=()=>{if(!batch.length)return;setConfirmation({title:'永久删除所选作品？',description:`将永久删除 ${batch.length} 个作品及其本地文件，无法恢复。`,label:'永久删除',action:()=>{batch.forEach(id=>void mutate(`/tracks/${encodeURIComponent(id)}`,'DELETE'));setBatch([]);setManage(false);toast('已永久删除所选作品。')}})};
  const locate=(t:Track)=>{if(t.audioKind==='generated'){toast('本机生成文件暂时不可用，请检查引擎与作品记录。');setSettingsTab('engine');setPanel('settings');return}locateTarget.current=t;audioInput.current?.click()};
  const openDetail=(t:Track)=>{setDetailRunRecord(null);setDetailTrack(t);if(!detailOpen)requestAnimationFrame(()=>setDetailOpen(true))};
  const openRunDetail=(r:Run)=>{setDetailTrack(null);setDetailRunRecord(r);if(!detailOpen)requestAnimationFrame(()=>setDetailOpen(true))};
  const closeDetail=()=>setDetailOpen(false);
  const details=openDetail;
  const copyText=(text:string,label:string)=>{void navigator.clipboard.writeText(text).then(()=>toast(`${label}已复制。`)).catch(()=>toast('复制失败，请检查浏览器权限。'))};
  const addReferenceFromTrack=(t:Track)=>{
    const apply=async()=>{
      setReferenceAdding(true);
      try{
        const saved=await api<ReferenceSource>('/references/from-track','POST',{trackId:t.id});
        const advanced=creationMode==='advanced';
        setDraft(d=>({...d,reference:{...saved,range:null,preserve:advanced?'full':'melody',strength:advanced?'faithful':'balanced'}}));
        setReferenceVersion(v=>v+1);
        toast('已添加到参考音频。',()=>{setMobilePanel('composer')},'去创作区');
      }catch(error){toast(error instanceof Error&&error.message?error.message:'添加到参考音频失败，请重试。')}
      finally{setReferenceAdding(false)}
    };
    if(draft.reference)setConfirmation({title:'替换当前参考音频？',description:'已经有一份参考音频，替换后需要重新转谱。',label:'替换',action:()=>void apply()});
    else void apply();
  };
  const openExport=(t:Track)=>{if(t.missing){locate(t);return}setExportTrack(t);setExportName(t.audioKind==='official-demo'?'YuE2官方示例_今晚不眠':t.title);setExportFormat('original');setExportState('idle');setExportError('');setPanel(null)};
  useEffect(()=>{if(detailTrack&&!tracks.some(t=>t.id===detailTrack.id)){setDetailTrack(null);setDetailOpen(false)}},[tracks,detailTrack]);
  // A finished run hands the panel over to the work it produced; a run that disappears closes it.
  useEffect(()=>{
    if(!detailRun)return;
    if(!runs.some(r=>r.id===detailRun.id)){setDetailRunRecord(null);setDetailOpen(false);return}
    if(!terminalStates.includes(detailRun.state))return;
    const produced=tracks.find(t=>t.runId===detailRun.id);
    if(produced){setDetailTrack(produced);setDetailRunRecord(null)}
  },[runs,tracks,detailRun]);
  // Retrying from the panel keeps the panel on the same work: follow the new attempt instead of stranding it on the failed run.
  useEffect(()=>{
    if(!detailRun||detailRun.state!=='failed')return;
    const attempt=runs.filter(r=>r.parentId===detailRun.id).sort((a,b)=>b.created-a.created)[0];
    if(attempt)setDetailRunRecord(attempt);
  },[runs,detailRun]);
  const inspectTrack=(t:Track)=>openDetail(t);
  const actions={onFavorite:favorite,onReuse:reuse,onRegenerate:regenerate,onExport:openExport,onRename:(t:Track)=>{setRename(t);setNewName(t.title)},onRemove:remove,onRestore:restore,onLocate:locate,onDetails:details};
  const cancel=(run:Run)=>{if(run.snapshot.runtime==='local-yue2'){void mutate(`/runs/${encodeURIComponent(run.id)}/cancel`,'POST');return}setRuns(old=>old.map(r=>r.id===run.id&&!terminalStates.includes(r.state)?transitionRun(r,r.state==='queued'?'cancelled':'cancelling'):r))};
  const retry=(run:Run)=>{if(run.snapshot.runtime==='local-yue2'){if(pendingRef.current){toast('请先确认上一份提交。');return}void submitLive({path:`/runs/${encodeURIComponent(run.id)}/retry`,body:{requestId:uid()}});return}const source=cloneDraft(run.snapshot.draft);submit({...source,count:1},[run.snapshot.seed],run.id,source.abc?.trim()?'advanced':'quick');setActiveRunDetail(null)};
  const detailTarget:DetailTarget|null=detailTrack?{kind:'track',track:detailTrack}:detailRun?{kind:'run',run:detailRun}:null;
  const trackActions:TrackActions|null=detailTrack?{play:()=>play(detailTrack),locate:()=>locate(detailTrack),reuse:()=>reuse(detailTrack),regenerate:()=>regenerate(detailTrack),export:()=>openExport(detailTrack),addReference:()=>addReferenceFromTrack(detailTrack)}:null;
  const runActions:RunActions|null=detailRun?{cancel:()=>cancel(detailRun),retry:()=>retry(detailRun),queue:()=>setPanel('queue')}:null;
  const importLyrics=async(e:ChangeEvent<HTMLInputElement>)=>{const file=e.target.files?.[0];if(!file)return;e.target.value='';try{const content=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());const before=cloneDraft(draft);const apply=()=>{updateDraft({lyrics:content});toast('歌词已导入。',()=>setDraft(before),'撤销')};if(draft.lyrics.trim())setConfirmation({title:'替换当前歌词？',description:`将导入「${file.name}」，原歌词可以在替换后撤销恢复。`,label:'替换歌词',action:apply});else apply()}catch{toast('无法按 UTF-8 读取文本，请检查文件编码。')}};
  const importAudio=async(e:ChangeEvent<HTMLInputElement>)=>{const file=e.target.files?.[0],target=locateTarget.current;e.target.value='';if(!file||!target)return;const url=URL.createObjectURL(file),a=new Audio(url);try{const duration=await new Promise<number>((resolve,reject)=>{a.onloadedmetadata=()=>resolve(a.duration);a.onerror=()=>reject(new Error('无法解码'))});if(!Number.isFinite(duration)||duration<=0)throw new Error('音频无效');setConfirmation({title:'关联这份音频？',description:`「${file.name}」· ${formatTime(duration)}。请确认它是要关联的音频。浏览器重新打开后需再次选择本地文件。`,label:'确认关联',action:()=>{patchTrack(target.id,{audioUrl:url,audioKind:'local',duration,missing:false,sourceTitle:file.name});toast('本地音频已关联。')}})}catch{URL.revokeObjectURL(url);toast('这份文件无法读取为音频，请选择其他文件。')}};
  const doExport=async()=>{if(!exportTrack||exportState==='exporting')return;if(!exportName.trim()){setExportError('请填写文件名称。');document.getElementById('export-file-name')?.focus();return}setExportState('exporting');setExportError('');try{let blob:Blob;if(exportFormat==='wav')blob=await exportWav(exportTrack.audioUrl);else{const response=await fetch(exportTrack.audioUrl);if(!response.ok)throw new Error('音频文件无法读取');blob=await response.blob()}const url=URL.createObjectURL(blob),anchor=document.createElement('a');anchor.href=url;anchor.download=`${safeFilename(exportName)}.${exportFormat==='wav'?'wav':originalExtension(exportTrack)}`;anchor.click();setTimeout(()=>URL.revokeObjectURL(url),30000);setExportState('done')}catch(e){setExportError(e instanceof Error?e.message:'导出未完成，请重试。');setExportState('failed')}};
  const clearDraft=()=>setConfirmation({title:'开始新的创作？',description:'当前歌词、标题与风格将清空。你可以撤销这次操作。',label:'新建创作',action:()=>{const before=cloneDraft(draft);setReference(null);setReferenceVersion(v=>v+1);setDraft({...cloneDraft(initialDraft),title:'',lyrics:'',style:''});toast('已开始新创作。',()=>setDraft(before),'撤销')}});
  const toggleQueue=()=>{if(mode==='demo')setPaused(p=>!p);else void mutate('/queue','PATCH',{paused:!paused})};
  const engineLabel=mode==='demo'?'演示模式':mode==='offline'?'引擎未连接':engine.health?.status==='resource_wait'?'等待显存':engine.health?.workerActive?'本机运行中':engine.health?.status==='unavailable'?'引擎待就绪':'本机引擎';
  const advancedReferenceBlocked=creationMode==='advanced'&&Boolean(reference)&&(advancedTranscription.status==='transcribing'||advancedTranscription.status==='stale'||(advancedTranscription.status==='error'&&!draft.abc?.trim()));
  const mainCaption=referenceBusy?'正在读取参考音频…':creationMode==='advanced'&&reference?(advancedTranscription.status==='transcribing'?'正在提取 ABC…':advancedTranscription.status==='stale'?'参考设置已变化，请重新提取 ABC':advancedTranscription.status==='error'?'ABC 提取失败，请重试或移除参考音频':'使用当前 ABC 生成'):reference?'自动提取旋律后生成 · 相同选区复用乐谱':mode==='offline'?'连接推理引擎后即可生成':submitting?'正在确认提交…':`生成 1 首 · ${draft.seedMode==='fixed'?'固定种子可能得到重复结果':draft.seedMode==='increment'?'每首种子依次递增':'每首使用随机种子'}`;
  const openChat=(target:'style-chat'|'lyrics-chat'|'abc-chat')=>requestAnimationFrame(()=>setPanel(target));
  const chatPanel=panel==='style-chat'||panel==='lyrics-chat'||panel==='abc-chat'?panel:null;
  const chatTitle=chatPanel==='lyrics-chat'?'AI 歌词助手':chatPanel==='abc-chat'?'AI ABC 乐谱助手':'AI 风格助手';
  const chatSubtitle=chatPanel==='lyrics-chat'?'按 YuE2 官方段落结构整理和修改歌词。关闭窗口不会中断任务，点击“停止”才会取消。':chatPanel==='abc-chat'?'改写旋律、保留节奏，或按这段乐谱生成歌词。关闭窗口不会中断任务，点击“停止”才会取消。':'把想法整理成可直接生成的风格描述。关闭窗口不会中断任务，点击“停止”才会取消。';
  const handleWorkspaceWheel=(event:WheelEvent<HTMLDivElement>)=>{
    const deltaY=event.deltaY;
    if(!deltaY||Math.abs(deltaY)<Math.abs(event.deltaX))return;
    let node=event.target instanceof HTMLElement?event.target:event.target instanceof Element?event.target.parentElement:null;
    while(node&&node!==event.currentTarget){
      const style=getComputedStyle(node),max=node.scrollHeight-node.clientHeight;
      if(max>0&&(style.overflowY==='auto'||style.overflowY==='scroll')){
        const next=Math.max(0,Math.min(max,node.scrollTop+deltaY));
        if(next!==node.scrollTop){node.scrollTop=next;event.preventDefault();return}
      }
      node=node.parentElement;
    }
  };
  return <ThemeContext.Provider value={theme}><MotionConfig reducedMotion={reduced?'always':'user'} transition={reduced?{duration:0}:motionTransition}><div data-module={module} onWheelCapture={handleWorkspaceWheel} className={`studio-app ${solid?'solid-surfaces':''} ${reduced?'reduced-motion':''}`}>
    <header className="app-header"><div className="brand"><WaveformIcon size={34} weight="duotone"/><strong>YuE2</strong><span>音乐工作室</span></div><span className="brand-separator"/><p className="environment-caption">本地 AI 音乐引擎 · YuE2-3B</p><div className="header-right"><button className="engine-status" onClick={()=>{setSettingsTab('engine');setPanel('settings')}}><span className={`status-dot ${mode==='offline'?'offline':''}`}/>{engineLabel}</button><span className="header-separator"/><Button className="header-button" onClick={()=>setPanel('queue')}><QueueIcon/>队列<span className="count-badge">{inflight}</span></Button><IconButton label={theme==='dark'?'切换到浅色主题':'切换到黑色主题'} className="theme-toggle" onClick={()=>setTheme(theme==='dark'?'light':'dark')}>{theme==='dark'?<SunIcon/>:<MoonIcon/>}</IconButton><Button className="header-button" onClick={()=>setPanel('settings')}><SettingsIcon/>设置</Button><span className="header-separator optional"/><IconButton label="切换全屏" className="fullscreen-button" onClick={()=>{if(document.fullscreenElement)void document.exitFullscreen();else void document.documentElement.requestFullscreen().catch(()=>toast('当前浏览器不支持全屏。'))}}><ExpandIcon size={19}/></IconButton></div></header>
    <nav style={module==='score'?{display:'none'}:undefined} className="mobile-switch" aria-label="工作台面板"><button aria-current={mobilePanel==='composer'?'page':undefined} onClick={()=>setMobilePanel('composer')}>创作</button><button aria-current={mobilePanel==='library'?'page':undefined} onClick={()=>setMobilePanel('library')}>我的作品{inflight?<span className="count-badge">{inflight}</span>:null}</button></nav>
    <div className="workspace-shell"><nav className="workspace-navigation" aria-label="工作模块"><button aria-current={module==='create'?'page':undefined} onClick={()=>setModule('create')}><WaveformIcon size={23}/>创作</button><button aria-current={module==='score'?'page':undefined} onClick={()=>setModule('score')}><MusicNotesIcon size={23}/>谱曲{scoreActive>0&&<span>{scoreActive}</span>}</button></nav><div className="workspace-pages"><main className="workbench" data-panel={mobilePanel} data-active={module==='create'} inert={module!=='create'} aria-hidden={module!=='create'}>
      <section className="composer glass" aria-label="创作区"><div className="creation-tabs" role="tablist" aria-label="创作模式"><button role="tab" aria-selected={creationMode==='quick'} onClick={()=>setCreationMode('quick')}>快速创作</button><button role="tab" aria-selected={creationMode==='advanced'} onClick={()=>setCreationMode('advanced')}>高级创作</button></div><div className="composer-scroll"><div className="composer-topline"><span>创作</span><span className={`save-status ${saveState==='failed'?'error':''}`}>{saveState==='saving'?'保存中…':saveState==='failed'?'草稿未保存':<><CheckIcon size={13}/>草稿已保存</>}</span><Menu.Root><Menu.Trigger asChild><IconButton label="创作选项"><MoreIcon/></IconButton></Menu.Trigger><Menu.Portal><Menu.Content className="dropdown" align="end"><Menu.Item onSelect={clearDraft}><PencilIcon/>新建创作</Menu.Item><Menu.Item onSelect={()=>{const url=URL.createObjectURL(new Blob([draft.lyrics],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=safeFilename(draft.title||'歌词')+'.txt';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}}><DownloadIcon/>保存歌词文本</Menu.Item></Menu.Content></Menu.Portal></Menu.Root></div>
        <label className="title-field"><span className="sr-only">歌曲标题</span><input id="field-title" value={draft.title} onChange={e=>updateDraft({title:e.target.value})} placeholder="未命名作品" aria-label="歌曲标题"/></label>
        <ReferenceAudioCard key={referenceVersion} active={module==='create'} purpose={creationMode==='advanced'?'advanced':'cover'} value={reference} source={draft.reference} transcription={creationMode==='advanced'?advancedTranscription:undefined} onTranscribe={creationMode==='advanced'&&reference?()=>void transcribeAdvanced(reference):undefined} onMissing={missing=>{setReference(null);setMissingReference(missing)}} onChange={handleReferenceChange} onBusyChange={setReferenceBusy}/>
        {saveState==='failed'?<p className="field-error" role="alert">草稿未能保存。请先从创作选项保存歌词文本。</p>:null}
        <div className="vocal-mode-field field"><div className="vocal-mode-row"><div className="vocal-mode-label"><label>人声</label></div><div className="option-group" role="group" aria-label="人声模式">{([['auto','自动'],['male','男声'],['female','女声'],['instrumental','纯音乐']] as const).map(([value,label])=><button type="button" aria-pressed={draft.vocalMode===value} key={value} onClick={()=>updateDraft({vocalMode:value})}>{label}</button>)}</div></div></div>
<div className={`lyrics-field field ${theme==='dark'&&lyricsCollapsed?'field-collapsed':''}`}><div className="field-heading">{theme==='dark'?<><button className="field-collapse" aria-expanded={!lyricsCollapsed} aria-controls="lyrics-input-region" onClick={()=>setLyricsCollapsed(v=>!v)}><CaretDownIcon className={lyricsCollapsed?'collapsed-arrow':''}/>歌词</button><label className="sr-only" htmlFor="field-lyrics">歌词</label></>:<label htmlFor="field-lyrics">歌词</label>}</div><div id="lyrics-input-region" inert={theme==='dark'&&lyricsCollapsed} aria-hidden={theme==='dark'&&lyricsCollapsed} data-collapsed={theme==='dark'&&lyricsCollapsed} className={`textarea-shell ${errors.some(e=>e.field==='lyrics')?'invalid':''}`}><textarea ref={lyricsRef} id="field-lyrics" value={draft.lyrics} onChange={e=>updateDraft({lyrics:e.target.value})} spellCheck={false} aria-invalid={errors.some(e=>e.field==='lyrics')} aria-describedby="lyrics-error" placeholder={'留空生成纯音乐，或写下你想唱的话…\n[Verse]'}/><span className="style-count">{Array.from(draft.lyrics).length} 字</span></div><p id="lyrics-error" className="field-error">{errors.find(e=>e.field==='lyrics')?.message}</p><button className="style-chat-trigger" aria-label="AI 辅助编辑歌词" onClick={()=>openChat('lyrics-chat')}><SparkleIcon size={22}/></button></div>
<div className={`style-field field ${theme==='dark'&&styleCollapsed?'field-collapsed':''}`}><div className="field-heading">{theme==='dark'?<><button className="field-collapse" aria-expanded={!styleCollapsed} aria-controls="style-input-region" onClick={()=>setStyleCollapsed(v=>!v)}><CaretDownIcon className={styleCollapsed?'collapsed-arrow':''}/>风格描述</button><label className="sr-only" htmlFor="field-style">风格描述</label></>:<label htmlFor="field-style">风格描述</label>}</div><div id="style-input-region" inert={theme==='dark'&&styleCollapsed} aria-hidden={theme==='dark'&&styleCollapsed} data-collapsed={theme==='dark'&&styleCollapsed} className={`textarea-shell ${errors.some(e=>e.field==='style')?'invalid':''}`}><textarea id="field-style" value={draft.style} onChange={e=>updateDraft({style:e.target.value})} aria-invalid={errors.some(e=>e.field==='style')} placeholder="曲风、人声、乐器与氛围…"/><span className="style-count">{Array.from(draft.style).length} 字</span></div>{errors.some(e=>e.field==='style')?<p className="field-error">{errors.find(e=>e.field==='style')?.message}</p>:null}<EditorResizeHandle label="风格描述"/><button className="style-chat-trigger" aria-label="AI 辅助优化风格" onClick={()=>openChat('style-chat')}><SparkleIcon size={22}/></button></div>
        {creationMode==='advanced'?<section ref={abcFieldRef} className="abc-field creative-card field" aria-labelledby="abc-heading"><div className="creative-heading field-heading"><CodeIcon size={19}/><label id="abc-heading" htmlFor="field-abc">ABC 乐谱 <small className="abc-optional">可选</small></label><button type="button" onClick={()=>abcInput.current?.click()}>导入 .abc</button></div><textarea id="field-abc" value={draft.abc??''} onChange={e=>updateDraft({abc:e.target.value})} placeholder={'粘贴或导入 ABC 乐谱…\nX:1\nM:4/4\nK:C'}/><p className="arrangement-help">可选。填入后按 ABC 中的旋律与和声生成；留空则按歌词与风格自动规划。</p><button className="style-chat-trigger" aria-label="AI 辅助编辑 ABC 乐谱" onClick={()=>openChat('abc-chat')}><SparkleIcon size={22}/></button></section>:null}
        
        <div className="arrangement-field field"><div className="field-heading"><FadersIcon size={19}/><label>编曲方式</label></div><div className="arrangement-options" role="group" aria-label="编曲方式">{(creationMode==='advanced'&&draft.abc?[['full','按完整乐谱生成','使用 ABC 旋律与和声'],['melody','保留旋律','按 ABC 旋律重新设计伴奏']]:[['full','完整规划','旋律与和弦'],['melody','旋律优先','翻唱推荐'],['off','直接生成','跳过乐谱规划']]).map(([value,label,desc])=><button type="button" key={value} aria-pressed={draft.config.cot===value} disabled={!!reference&&value==='off'} onClick={()=>updateDraft({config:{...draft.config,cot:value as Config['cot']}})}><strong>{label}</strong><small>{desc}</small></button>)}</div><p className="arrangement-help">{draft.abc?(draft.config.cot==='full'?'按 ABC 中的旋律与和声生成，不重新谱曲。':'保留 ABC 旋律，重新设计伴奏。'):reference?'使用参考旋律需要乐谱规划；旋律优先更适合翻唱。':draft.config.cot==='full'?'先规划旋律与和弦，再生成音乐。':draft.config.cot==='melody'?'先规划旋律，伴奏自由发挥。':'跳过乐谱规划，直接根据风格与歌词生成。'}</p></div>
        <CreativePreferences draft={draft} onChange={updateDraft}/>
      </div><div className="composer-footer"><div className="generation-options"><button className="advanced-trigger" onClick={()=>setPanel('advanced')}>高级设置{changed?<span className="modification-count">{changed}</span>:null}<CaretDownIcon size={16}/></button></div>
        <Button className="generate-button" disabled={submitting||referenceBusy||advancedReferenceBlocked} onClick={()=>submit()}>{submitting?<SpinnerIcon className="spin"/>:<WaveformIcon size={28}/>}<span>{reference&&creationMode==='advanced'?'使用 ABC 生成':reference?'生成翻唱':mode==='offline'?'配置生成引擎':submitting?'正在加入…':active?'加入队列':'生成音乐'}</span><span className="shortcut">Ctrl ↵</span></Button><p className={`generate-caption ${draft.seedMode==='fixed'&&draft.count>1?'warning':''}`}>{mainCaption}</p>
      </div></section>
      <WorkspaceDivider/><section className="library glass" aria-label="我的作品"><div className="library-header">{manage?<div className="batch-toolbar"><span>已选择 {batch.length} 项</span><button onClick={()=>setBatch(visibleTracks.map(t=>t.id))}>全选</button><button onClick={downloadBatch} disabled={!batch.length}>批量下载</button><button className="batch-danger" onClick={removeBatch} disabled={!batch.length}>永久删除</button><button onClick={()=>{setManage(false);setBatch([])}}>完成</button></div>:null}<div className="library-title-row"><h1>{theme==='dark'?<span className="workspace-crumb">本地工作区<CaretRightIcon size={15}/></span>:null}我的作品</h1><div className="search-field"><SearchIcon/><input placeholder="搜索标题、歌词或风格…" aria-label="搜索作品" value={query} onChange={e=>setQuery(e.target.value)}/>{query?<IconButton label="清空搜索" onClick={()=>setQuery('')}><XIcon size={16}/></IconButton>:null}</div></div><div className="library-filters">{!manage?<button className="manage-trigger" onClick={()=>{setManage(true);setBatch([])}}>管理</button>:null}<div role="tablist" aria-label="作品筛选">{([['all','全部'],['favorite','收藏']] as const).map(([id,text])=><button role="tab" aria-selected={filter===id} key={id} onClick={()=>setFilter(id)}>{text}</button>)}{filter==='removed'?<button role="tab" aria-selected>已移除</button>:null}</div><Menu.Root><Menu.Trigger asChild><button className="sort-trigger">{sort==='latest'?'最新创建':sort==='oldest'?'最早创建':'按标题'}<SortIcon size={15}/></button></Menu.Trigger><Menu.Portal><Menu.Content className="dropdown" align="end">{([['latest','最新创建'],['oldest','最早创建'],['name','按标题']] as const).map(([value,name])=><Menu.Item key={value} onSelect={()=>setSort(value)}>{name}{sort===value?<CheckIcon/>:null}</Menu.Item>)}<Menu.Separator/><Menu.Item onSelect={()=>setFilter(filter==='removed'?'all':'removed')}><TrashIcon/>{filter==='removed'?'返回全部作品':'查看已移除记录'}</Menu.Item></Menu.Content></Menu.Portal></Menu.Root></div></div>
      <div className="library-scroll" ref={libraryScroll}>
        {mode==='demo'&&showRecovery?<div className="recovery-notice"><WarningIcon/><div><strong>发现上次未完成的任务</strong><p>草稿与等待队列已恢复，中断任务可以重新提交。</p></div><button onClick={()=>{setShowRecovery(false);setPanel('queue')}}>查看队列</button><IconButton label="关闭恢复提示" onClick={()=>setShowRecovery(false)}><XIcon size={16}/></IconButton></div>:null}
        {pending&&mode!=='demo'?<div className="recovery-notice"><WarningIcon/><div><strong>有一份提交等待确认</strong><p>继续使用原请求编号查询，不会重复生成。</p></div><Button disabled={submitting||!engine.online} onClick={()=>void submitLive(pending)}>查询并继续提交</Button></div>:null}
        {mode==='offline'?<div className="inline-warning"><WarningIcon/><span>引擎连接中断，已显示的状态可能已变化。后台任务不会因页面断线取消。</span><Button onClick={()=>void engine.refresh()}>重新连接</Button></div>:null}
        <AnimatePresence initial={false}>{newResults?<motion.button key="new-results" className="new-results" initial={{opacity:0,y:5}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-3}} transition={{duration:.18,ease:[.22,1,.36,1]}} onClick={()=>{setFilter('all');setQuery('');setSort('latest');setNewResults(0);libraryScroll.current?.scrollTo({top:0,behavior:reduced?'instant':'smooth'})}}>有 {newResults} 首新作品 · 点击查看</motion.button>:null}</AnimatePresence>
        <AnimatePresence initial={false}>{active&&!tracks.some(t=>t.runId===active.id)?<GeneratingTrack key={active.id} run={active} selected={detailOpen&&detailRun?.id===active.id} onDetails={()=>openRunDetail(active)} onQueue={()=>setPanel('queue')} onCancel={()=>cancel(active)}/>:null}</AnimatePresence>
        {!active&&queued.length?<div className="queued-notice"><ClockIcon size={18}/><span>{paused?'后续任务已暂停':'任务等待中'} · {queued.length} 首</span><button onClick={()=>{if(paused)toggleQueue();else setPanel('settings')}}>{paused?'恢复队列':'查看引擎'}</button></div>:null}
        {visibleTracks.length?<div className="track-list"><AnimatePresence initial={false} mode="popLayout">{visibleTracks.map(t=><motion.article layout="position" initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} exit={{opacity:0,y:-6}} className={`track ${detailOpen&&detailTrack?.id===t.id?'selected':''} ${t.removed?'removed':''} ${playbackState.trackId===t.id&&playbackState.playing?'is-playing':''} ${playbackState.trackId===t.id&&playbackState.loading?'is-buffering':''}`} key={t.id}><div className="track-summary" onClick={event=>{if(manage||(event.target as HTMLElement).closest('button,input,a'))return;openDetail(t)}}>{manage?<input className="batch-check" type="checkbox" checked={batch.includes(t.id)} onChange={()=>toggleBatch(t.id)} aria-label={`选择 ${t.title}`}/>:null}<span className="playing-edge" aria-hidden="true"><span/></span><button className="track-artwork" onClick={()=>play(t)} aria-label={`${t.missing?(t.audioKind==='generated'?'检查文件':'重新定位'):playbackState.trackId===t.id&&playbackState.playing?'暂停':'播放'} ${t.title}`}><img src={t.artwork} alt=""/><span className="thumbnail-duration">{formatTime(t.duration)}</span><span className="track-play-icon">{t.missing?<WarningIcon/>:playbackState.trackId===t.id&&playbackState.playing?<PauseIcon weight="fill"/>:<PlayIcon weight="fill"/>}</span></button><div className="track-copy"><div className="title-version"><button onClick={()=>inspectTrack(t)} aria-expanded={detailTrack?.id===t.id} aria-haspopup="dialog">{t.title}</button>{playbackState.trackId===t.id&&playbackState.playing?<span className="now-playing-badge"><span className="playing-meter" aria-hidden="true"><i/><i/><i/><i/></span>{playbackState.loading?'缓冲中':'正在播放'}</span>:null}<span className="version">{t.version} · {sourceLabel(t)}</span>{t.warning?<span className="warning-mark" title={t.warning}><WarningIcon size={17}/></span>:null}</div><p>{t.missing?'音频文件不可用':t.style}</p><time>{formatDate(t.created)}</time>{theme==='dark'?<div className="track-inline-actions"><IconButton label={`${t.favorite?'取消收藏':'收藏'} ${t.title}`} className={`favorite ${t.favorite?'on':''}`} aria-pressed={t.favorite} onClick={()=>favorite(t)}><StarIcon size={17} weight={t.favorite?'fill':'regular'}/></IconButton><IconButton label={`复用 ${t.title} 的参数`} onClick={()=>reuse(t)}><CopyIcon size={17}/></IconButton><IconButton label={`导出 ${t.title}`} disabled={t.missing} onClick={()=>openExport(t)}><DownloadIcon size={17}/></IconButton>{t.missing?<button className="missing-action" onClick={()=>locate(t)}>{t.audioKind==='generated'?'检查引擎':'重新定位'}</button>:null}</div>:null}</div><span className="track-duration">{formatTime(t.duration)}</span><IconButton label={`${t.favorite?'取消收藏':'收藏'} ${t.title}`} className={`favorite ${t.favorite?'on':''}`} aria-pressed={t.favorite} onClick={()=>favorite(t)}><StarIcon size={23} weight={t.favorite?'fill':'regular'}/></IconButton><TrackMenu track={t} actions={actions}/></div></motion.article>)}</AnimatePresence></div>:active?null:<div className="empty-state"><FileAudioIcon size={42} weight="thin"/><h2>{query?'没有找到匹配的作品':filter==='favorite'?'把喜欢的声音留在这里':filter==='removed'?'暂无已移除记录':'从一句歌词开始'}</h2><p>{query?'换一个关键词，或清空搜索看看。':filter==='favorite'?'点击作品旁的星标，方便下一次找到它。':filter==='removed'?'移除的作品记录可以从这里恢复。':'写下歌词和风格，让灵感成为一首歌。'}</p><Button onClick={()=>{if(query)setQuery('');else if(filter!=='all')setFilter('all');else{setMobilePanel('composer');lyricsRef.current?.focus()}}}>{query?'清空搜索':filter!=='all'?'查看全部作品':'开始创作'}</Button></div>}
      </div></section>
      {detailTarget?<DetailPanel target={detailTarget} open={detailOpen} referenceBusy={referenceAdding} trackActions={trackActions} runActions={runActions} onClose={closeDetail} onClosed={()=>{setDetailTrack(null);setDetailRunRecord(null)}} onCopy={copyText}/>:null}
    </main><div className="score-module" data-active={module==='score'} inert={module!=='score'} aria-hidden={module!=='score'}><ScoreWorkspace active={module==='score'} onStatus={setScoreActive}/></div></div></div>
    <PlaybackError onLocate={()=>locate(playerTrack)}/><Player track={tracks.find(t=>t.id===playerTrack.id)??playerTrack} onPlay={()=>play(tracks.find(t=>t.id===playerTrack.id)??playerTrack)} onDetails={()=>details(tracks.find(t=>t.id===playerTrack.id)??playerTrack)} onQueue={()=>setPanel('queue')}/>
    <AdvancedSettings open={panel==='advanced'} onClose={()=>setPanel(null)} draft={draft} onChange={updateDraft}/>
<Sheet keepMounted open={Boolean(chatPanel)} onClose={()=>setPanel(null)} title={chatTitle} subtitle={chatSubtitle} wide center>
      <div hidden={chatPanel!=='style-chat'}><StyleChat active={chatPanel==='style-chat'} provider={chatProvider} onProviderChange={setChatProvider} currentStyle={draft.style} referenceTexts={{lyrics:draft.lyrics}} onApply={text=>updateDraft({style:text})}/></div>
      <div hidden={chatPanel!=='lyrics-chat'}><StyleChat active={chatPanel==='lyrics-chat'} provider={chatProvider} onProviderChange={setChatProvider} kind="lyrics" creationMode={creationMode} currentStyle={draft.lyrics} referenceTexts={{abc:draft.abc}} onApply={text=>updateDraft({lyrics:text})}/></div>
      <div hidden={chatPanel!=='abc-chat'}><StyleChat active={chatPanel==='abc-chat'} provider={chatProvider} onProviderChange={setChatProvider} kind="abc" creationMode={creationMode} currentStyle={draft.abc??''} referenceTexts={{lyrics:draft.lyrics,style:draft.style}} onApply={(text,target)=>updateDraft(target==='lyrics'?{lyrics:text}:target==='style'?{style:text}:{abc:text})}/></div>
    </Sheet>
    <Sheet open={panel==='queue'} onClose={()=>setPanel(null)} title="生成队列" subtitle={`${mode==='demo'?'当前为界面演示，任务不会调用模型。':mode==='live'?'任务在本机运行，关闭页面后继续。':'连接中断，显示上次已确认状态。'} 同一时间运行一首。`} footer={<><span className="footer-note">{queued.length} 首等待</span><Button onClick={toggleQueue}>{paused?<PlayIcon/>:<PauseIcon/>}{paused?'恢复后续任务':'暂停启动后续任务'}</Button></>}>
      {paused?<div className="inline-warning"><PauseIcon/><span>后续任务已暂停，当前任务继续。</span></div>:null}
      {runs.length?<div className="queue-list">{[...runs].sort((a,b)=>{const rank=(r:Run)=>activeStates.includes(r.state)?0:r.state==='queued'?1:2;return rank(a)-rank(b)||(rank(a)===2?b.created-a.created:a.created-b.created)}).map((r)=><div className={`queue-row ${r.state==='failed'||r.state==='interrupted'?'error':''}`} key={r.id}><div className="queue-stage-icon">{r.state==='succeeded'?<CheckIcon/>:r.state==='failed'||r.state==='interrupted'?<WarningIcon/>:activeStates.includes(r.state)?<SpinnerIcon className="spin"/>:<ClockIcon/>}</div><div className="queue-row-copy"><button onClick={()=>setActiveRunDetail(r)}>{r.snapshot.draft.title||'未命名作品'}</button><p>{stageLabels[r.state]} · {r.snapshot.runtime==='local-yue2'?'本机':'演示'}</p>{r.progress?<p>{runProgress(r)}</p>:null}{r.error?<p className="queue-error">{r.error.replace(/^[A-Za-z]+Error:\s*/,'')}</p>:null}<span className="seed-value">种子 {r.snapshot.seed}</span></div>{!terminalStates.includes(r.state)?<IconButton label={`取消任务 ${r.snapshot.draft.title}`} disabled={r.state==='cancelling'} onClick={()=>cancel(r)}><XIcon/></IconButton>:r.state!=='succeeded'?<Button onClick={()=>retry(r)}><RetryIcon/>重试</Button>:null}</div>)}</div>:<div className="empty-state"><QueueIcon size={44} weight="thin"/><h2>队列是空的</h2><p>从创作区提交后，运行与等待任务会显示在这里。</p><Button onClick={()=>{setPanel(null);setMobilePanel('composer')}}>返回创作</Button></div>}
    </Sheet>
    <Sheet open={panel==='settings'} onClose={()=>setPanel(null)} title="设置" subtitle="工作区、播放与界面偏好。" wide footer={<Button className="primary" onClick={()=>setPanel(null)}>完成</Button>}>
      <div className="settings-tabs">{([['engine','模型与引擎'],['appearance','界面偏好'],['storage','本地存储'],['demo','演示状态'],['about','关于']] as const).map(([id,name])=><button aria-pressed={settingsTab===id} key={id} onClick={()=>setSettingsTab(id)}>{name}</button>)}</div>
{settingsTab==='engine'?<><div className="environment-card"><WaveformIcon size={36} weight="light"/><div><h3>YuE2 本地生成引擎</h3><p>{engine.online?(engine.health?.reason||'服务已连接，任务由本机引擎执行。'):engine.error}</p></div><span className="small-tag">{engineLabel}</span></div><div className="settings-section"><h3>运行状态</h3>{[['控制服务',engine.online?'已连接':'未连接'],['运行依赖',engine.online?(engine.health?.dependenciesReady?'已就绪':'未就绪'):'未知'],['模型文件',engine.online?(engine.health?.modelsReady?'已就绪':'未就绪'):'未知'],['GPU 工作进程',engine.online?(engine.health?.workerActive?'运行中':'空闲'):'未知'],['模型加载',engine.online?(engine.health?.modelLoaded?'已加载':'未驻留，任务启动时加载'):'未知']].map(([label,value])=><div className="model-row" key={label}><strong>{label}</strong><span>{value}</span></div>)}{engine.online&&engine.health?.device?<p className="setting-help">{engine.health.device.name} · 可用 {(engine.health.device.freeMiB/1024).toFixed(1)} / {(engine.health.device.totalMiB/1024).toFixed(1)} GiB</p>:null}{engine.online&&engine.health?.profile?<p className="setting-help">{engine.health.profile.modelName} · {engine.health.profile.backend} · {engine.health.profile.memoryBudgetGiB} GiB</p>:null}<Button onClick={()=>void engine.refresh()}>刷新连接状态</Button></div><div className="settings-section"><h3>当前工作区</h3><div className="option-group"><button aria-pressed={mode!=='demo'} onClick={()=>setMode('live')}>本机生成</button><button aria-pressed={mode==='demo'} onClick={()=>setMode('demo')}>演示模式</button></div><p className="setting-help">本机作品与任务保存在本地服务。演示作品继续保存在浏览器，两种模式共用当前歌词草稿。</p></div></>:null}
      {settingsTab==='demo'&&mode!=='demo'?<div className="settings-section"><p>演示状态只影响演示工作区。</p><Button onClick={()=>setMode('demo')}>切换到演示模式</Button></div>:null}
      {settingsTab==='storage'?<section className="settings-section storage-center"><h3>本地存储</h3><p className="setting-help">作品和谱曲缓存保存在本机。移入回收站后仍可恢复。</p><div className="storage-meter"><span style={{width:'42%'}}/></div><div className="storage-total"><strong>本地作品</strong><span>{tracks.length} 个作品</span></div><div className="storage-list"><div><span>音乐文件</span><strong>按作品目录保存</strong></div><div><span>谱曲与 ABC</span><strong>随作品保留</strong></div><div><span>回收站</span><strong>{tracks.filter(t=>t.removed).length} 个作品</strong></div></div><div className="storage-actions"><Button disabled={!tracks.some(t=>t.removed)} onClick={()=>tracks.filter(t=>t.removed).forEach(t=>void patchTrack(t.id,{removed:false}))}>恢复回收站</Button><Button disabled={!tracks.some(t=>t.removed)} onClick={()=>setConfirmation({title:'清空回收站？',description:'回收站中的作品记录将被永久移除，无法恢复。',label:'永久删除',action:()=>{tracks.filter(t=>t.removed).forEach(t=>void patchTrack(t.id,{removed:true}));toast('已清理回收站。')}})}>清空回收站</Button></div></section>:null}
      {settingsTab==='appearance'?<><section className="settings-section theme-preference"><h3>界面主题</h3><div className="option-group"><button aria-pressed={theme==='light'} onClick={()=>setTheme('light')}><SunIcon size={18}/>银白</button><button aria-pressed={theme==='dark'} onClick={()=>setTheme('dark')}><MoonIcon size={18}/>沉浸黑</button></div><p className="setting-help">主题选择会自动记住。</p></section><div className="preference-row"><div><h3>减少动态效果</h3><p>减少面板过渡、状态呼吸与内容位移。</p></div><input type="checkbox" role="switch" aria-label="减少动态效果" checked={reduced} onChange={e=>setReduced(e.target.checked)}/></div><div className="preference-row"><div><h3>减少透明效果</h3><p>使用更实的表面，让文字和边界更清楚。</p></div><input type="checkbox" role="switch" aria-label="减少透明效果" checked={solid} onChange={e=>setSolid(e.target.checked)}/></div><div className="settings-section"><h3>键盘操作</h3><div className="key-row"><span>提交当前创作</span><kbd>Ctrl + Enter</kbd></div><div className="key-row"><span>非编辑区播放 / 暂停</span><kbd>Space</kbd></div><div className="key-row"><span>关闭菜单或面板</span><kbd>Esc</kbd></div></div></>:null}
      {settingsTab==='demo'&&mode==='demo'?<><div className="settings-section"><h3>下一次演示运行</h3><p className="setting-help">这些选项只控制演示任务，用来检查反馈与恢复流程。</p><div className="demo-options">{([['success','正常完成','形成可试听的界面样例。'],['fail','合成阶段失败','保留请求与种子，并显示重试。'],['warning','完成并带提醒','保留试听，提示结果可能提前结束。']] as const).map(([id,title,desc])=><button key={id} aria-pressed={nextOutcome===id} onClick={()=>setNextOutcome(id)}><strong>{title}</strong><span>{desc}</span>{nextOutcome===id?<CheckIcon/>:null}</button>)}</div></div><div className="settings-section"><h3>其他状态</h3><div className="demo-actions"><Button onClick={()=>{const t=selected??tracks.find(t=>!t.removed);if(t){patchTrack(t.id,{missing:true});if(playerTrack.id===t.id)playback.stop();setPanel(null);toast('已展示音频文件丢失状态。')}}}><FileAudioIcon/>展示文件丢失</Button><Button onClick={()=>{setRuns(old=>old.map(r=>activeStates.includes(r.state)?{...transitionRun(r,'interrupted'),error:'演示：引擎意外停止。'}:r));setPaused(true);setShowRecovery(true);setMode('demo');setPanel(null)}}><WarningIcon/>展示引擎中断</Button><Button onClick={()=>setConfirmation({title:'恢复演示工作区？',description:'当前界面样例和任务将重置，歌词草稿继续保留。',label:'恢复样例',action:()=>{playback.stop();setTracks(makeSamples());setRuns([]);setPaused(false);setMode('demo');setDetailOpen(false);setDetailTrack(null);setPlayerTrack(makeSamples()[0]);setFilter('all');setQuery('');setShowRecovery(false);setNewResults(0);setPanel(null);toast('演示样例已恢复。')}})}><RetryIcon/>恢复演示作品</Button></div></div></>:null}
      {settingsTab==='about'?<><div className="about-brand"><WaveformIcon size={40} weight="duotone"/><h2>YuE2 音乐工作室</h2><p>{theme==='dark'?'沉浸黑':'Silver Mist'} · 本地交互原型</p></div><div className="settings-section"><h3>试听音频来源</h3><p className="setting-help">《今晚不眠》是 YuE2 官方发布的早期检查点试听示例。这里的作品标题、歌词与封面用于界面设计，试听不代表本机生成结果。</p><a href="https://huggingface.co/m-a-p/YuE2-3B/blob/main/assets/audio/examples.json" target="_blank" rel="noreferrer">查看官方示例说明 <ExpandIcon size={14}/></a></div><div className="settings-section"><h3>本地数据</h3><p className="setting-help">真实作品、收藏与队列保存在本地服务；草稿和演示记录保存在当前浏览器。选择的本地音频由浏览器临时访问，页面重新打开后可重新定位。</p></div></>:null}
    </Sheet>
    
    <Sheet open={Boolean(activeRunDetail)} onClose={()=>setActiveRunDetail(null)} title="任务记录" subtitle="本次提交的歌词、参数与种子不会随创作区编辑改变。" center footer={activeRunDetail?<Button onClick={()=>{void navigator.clipboard.writeText(JSON.stringify(activeRunDetail.snapshot,null,2)).then(()=>toast('任务快照已复制。')).catch(()=>toast('复制失败，请检查浏览器权限。'))}}>复制任务快照</Button>:null}>{activeRunDetail?<><div className="record-state">{stageLabels[(runs.find(r=>r.id===activeRunDetail.id)??activeRunDetail).state]} · {activeRunDetail.snapshot.runtime==='local-yue2'?'本机':'演示'}<p>{runProgress(runs.find(r=>r.id===activeRunDetail.id)??activeRunDetail)}</p></div><h3>{activeRunDetail.snapshot.draft.title}</h3><p className="detail-lyrics">{activeRunDetail.snapshot.draft.lyrics}</p><div className="seed-value">种子 {activeRunDetail.snapshot.seed}</div>{(runs.find(r=>r.id===activeRunDetail.id)??activeRunDetail).error?<p className="field-error">{(runs.find(r=>r.id===activeRunDetail.id)??activeRunDetail).error}</p>:null}</>:null}</Sheet>
    <Sheet open={Boolean(exportTrack)} onClose={()=>{if(exportState!=='exporting')setExportTrack(null)}} title="导出音频" subtitle={exportTrack?.audioKind==='official-demo'?'当前导出的是 YuE2 官方试听《今晚不眠》。':'另存为音频副本。'} center footer={<><Button onClick={()=>setExportTrack(null)} disabled={exportState==='exporting'}>关闭</Button><Button className="primary" disabled={exportState==='exporting'} onClick={()=>void doExport()}>{exportState==='exporting'?<SpinnerIcon className="spin"/>:<DownloadIcon/>}{exportState==='exporting'?'正在导出…':exportState==='done'?'再次下载':'导出副本'}</Button></>}><div className="option-group export-format"><button aria-pressed={exportFormat==='original'} disabled={exportState==='exporting'} onClick={()=>setExportFormat('original')}>原始音频<span>{exportTrack?originalExtension(exportTrack).toUpperCase():''} · 保留原文件格式</span></button><button aria-pressed={exportFormat==='wav'} disabled={exportState==='exporting'} onClick={()=>setExportFormat('wav')}>WAV<span>48 kHz · 16-bit PCM</span></button></div><label className="setting-field">文件名称<input id="export-file-name" value={exportName} disabled={exportState==='exporting'} onChange={e=>{setExportName(e.target.value);setExportError('');setExportState('idle')}}/></label><p className="setting-help">由浏览器选择保存位置和处理重名文件。原音频保持可用。</p>{exportError?<p className="field-error" role="alert">{exportError}</p>:null}{exportState==='done'?<div className="success-notice"><CheckIcon/>下载已交给浏览器，请在下载列表中查看。</div>:null}</Sheet>
    <Sheet open={Boolean(rename)} onClose={()=>setRename(null)} title="重命名作品" subtitle="修改作品的显示名称。" center footer={<><Button onClick={()=>setRename(null)}>取消</Button><Button className="primary" disabled={!newName.trim()} onClick={async()=>{if(rename&&await patchTrack(rename.id,{title:newName.trim()})){setRename(null);toast('作品名称已更新。')}}}>保存名称</Button></>}><label className="setting-field">作品名称<input value={newName} onChange={e=>setNewName(e.target.value)} onKeyDown={async e=>{if(e.key==='Enter'&&!e.nativeEvent.isComposing&&rename&&newName.trim()){if(await patchTrack(rename.id,{title:newName.trim()}))setRename(null)}}}/></label></Sheet>
    <Sheet open={Boolean(missingReference)} onClose={()=>{setMissingReference(null);setDraft(d=>({...d,reference:undefined}))}} title="参考音频无法读取" center footer={<><Button onClick={()=>{setMissingReference(null);setReference(null);setDraft(d=>({...d,reference:undefined}));requestAnimationFrame(()=>document.querySelector<HTMLButtonElement>('.add-reference')?.click())}}>重新选择</Button><Button onClick={()=>{setMissingReference(null);setReference(null);setDraft(d=>({...d,reference:undefined}))}}>放弃添加</Button></>}><p>原音频可能已移动、删除或暂时无法访问。歌词和其他参数已填充。</p><p style={{overflowWrap:'anywhere'}}>{missingReference?.path}</p></Sheet>
    <Sheet open={Boolean(confirmation)} onClose={()=>setConfirmation(null)} title={confirmation?.title??'确认操作'} subtitle={confirmation?.description} center footer={<><Button onClick={()=>setConfirmation(null)}>取消</Button><Button className={confirmation?.danger?'danger':'primary'} onClick={()=>{const next=confirmation;setConfirmation(null);next?.action()}}>{confirmation?.label??'确认'}</Button></>}><p className="confirmation-note">{confirmation?.description}</p></Sheet>
    <Toast notice={notice} onClose={()=>setNotice(null)}/><input ref={fileInput} type="file" accept=".txt,text/plain" onChange={e=>void importLyrics(e)} hidden/><input ref={abcInput} type="file" accept=".abc,text/plain" onChange={e=>{const f=e.target.files?.[0];if(!f)return;void f.text().then(text=>updateDraft({abc:text}));e.target.value=''}} hidden/><input ref={audioInput} type="file" accept="audio/*" onChange={e=>void importAudio(e)} hidden/>
  </div></MotionConfig></ThemeContext.Provider>
}


















