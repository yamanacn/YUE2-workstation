import {SelectControl} from './select-control';
import {useState, type CSSProperties} from 'react';
import {Button,Sheet} from './components';
import {defaultConfig,validateDraft,type Draft,type Config} from './domain';
import {CaretDownIcon,ClockIcon,FadersIcon,WaveformIcon} from './icons';
import './advanced-settings.css';
import {PerformanceSettings} from './performance-settings';

const parameters=[
  {key:'temperature',label:'Temperature',min:0,max:5,step:.05},
  {key:'topP',label:'Top P',min:.01,max:1,step:.01},
  {key:'topK',label:'Top K',min:1,step:1},
  {key:'repetitionPenalty',label:'Repetition Penalty',min:.01,step:.05},
  {key:'odeSteps',label:'ODE Steps',min:1,step:1},
] as const;
const precision=[{value:16,title:'快速试听',detail:'16 步'},{value:32,title:'平衡',detail:'32 步 · 默认'},{value:64,title:'精细合成',detail:'64 步'}];
export function CreativePreferences({draft,onChange}:{draft:Draft;onChange:(patch:Partial<Draft>)=>void}){
  const temperature=draft.config.temperature;
  const custom=!Number.isFinite(temperature)||temperature<.5||temperature>1.5;
  return <div className="creative-settings composer-preferences"><section className="creative-card" aria-labelledby="creative-heading">
    <div className="creative-heading"><WaveformIcon size={19}/><h3 id="creative-heading">创作偏好</h3></div>
    <div className="creative-label"><label htmlFor="creative-variation">创意变化</label><output htmlFor="creative-variation">{custom?'自定义':temperature<.85?'偏稳定':temperature>1.15?'更丰富':'均衡'}<span>{Number.isFinite(temperature)?temperature.toFixed(2):'—'}</span></output></div>
    <input id="creative-variation" className="creative-range" type="range" min="0.5" max="1.5" step="0.05" value={Number.isFinite(temperature)?Math.min(1.5,Math.max(.5,temperature)):1} aria-valuetext={custom?'自定义值，请在开发者选项中调整':String(temperature)} style={{'--range-fill':`${((Number.isFinite(temperature)?Math.min(1.5,Math.max(.5,temperature)):1)-.5)*100}%`} as CSSProperties} onChange={e=>onChange({config:{...draft.config,temperature:Number(e.target.value)}})}/>
    <div className="range-captions"><span>稳定</span><span>丰富</span></div>
    <p className="setting-help">调整音乐生成的随机程度。默认值适合先试听，再探索变化。{custom?' 当前数值超出常用范围；拖动滑块会回到常用范围。':''}</p>
  </section><section className="creative-card sequence-budget-card" aria-labelledby="sequence-budget-heading">
    <div className="creative-heading"><ClockIcon size={19}/><h3 id="sequence-budget-heading">生成长度倾向</h3></div>
    <div className="creative-label"><label htmlFor="composer-sequence-budget">音乐序列预算</label><output><span>{draft.config.maxTokens.toLocaleString()} tokens</span></output></div>
    <input id="composer-sequence-budget" className="creative-range" type="range" min="200" max="24575" step="100" value={Number.isFinite(draft.config.maxTokens)?draft.config.maxTokens:9000} aria-label="音乐序列预算" style={{'--range-fill':`${((draft.config.maxTokens-200)/24375)*100}%`} as CSSProperties} onChange={e=>onChange({config:{...draft.config,maxTokens:Number(e.target.value)}})}/>
    <div className="range-captions"><span>短</span><span>长</span></div>
    <p className="setting-help">用于粗略影响成品时长。官方默认值为 9,000 tokens，实际时长会因节奏和结构变化。</p>
  </section></div>;
}
export function AdvancedSettings({open,onClose,draft,onChange}:{open:boolean;onClose:()=>void;draft:Draft;onChange:(patch:Partial<Draft>)=>void}){
  const [developer,setDeveloper]=useState(false);
  const [tab,setTab]=useState<'generation'|'performance'>('performance');
  const config=draft.config;
  const update=(patch:Partial<Config>)=>onChange({config:{...config,...patch}});
  const errors=validateDraft(draft).filter(e=>e.field==='config'||e.field==='seed');
  return <Sheet open={open} onClose={onClose} title="高级设置" subtitle="给下一首歌，留一点自己的偏好。" footer={<><Button onClick={()=>onChange({config:{...defaultConfig},seedMode:'random',seed:'831001'})}>恢复默认参数</Button><Button className="primary" disabled={errors.length>0} onClick={onClose}>完成</Button></>}>
    <div className="creative-settings">
      <p className="advanced-scope">自动保存到草稿 · 下次生成时生效</p>
      <div className="settings-tabs" role="tablist" aria-label="高级设置分类"><button type="button" role="tab" aria-selected={tab==='generation'} onClick={()=>setTab('generation')}>生成参数</button><button type="button" role="tab" aria-selected={tab==='performance'} onClick={()=>setTab('performance')}>性能与显存</button></div>
      {tab==='performance'?<PerformanceSettings config={config} onChange={update}/>:<>
      <section className="creative-card" aria-labelledby="precision-heading">
        <div className="creative-heading"><h3 id="precision-heading">合成精度</h3>{!precision.some(p=>p.value===config.odeSteps)&&<span className="creative-badge">自定义 · {Number.isFinite(config.odeSteps)?config.odeSteps:'—'} 步</span>}</div>
        <div className="precision-options" role="group" aria-label="合成精度">{precision.map(p=><button type="button" key={p.value} aria-pressed={config.odeSteps===p.value} onClick={()=>update({odeSteps:p.value})}><strong>{p.title}</strong><span>{p.detail}</span></button>)}</div>
        <p className="setting-help">步数越多，声学合成通常越慢；更多步数不保证听感更好。</p>
      </section>
      <div className="advanced-note"><span>关于时长与参考音频</span><p>歌曲时长随歌词与生成结果决定。使用参考音频时，先提取旋律再生成。</p></div>
      <section className="developer-section">
        <button type="button" className="developer-toggle" aria-expanded={developer} aria-controls="developer-parameters" onClick={()=>setDeveloper(!developer)}><FadersIcon size={18}/><span>开发者选项<small>随机种子、采样与生成预算</small></span><CaretDownIcon size={17} className={developer?'rotated':''}/></button>
        <div id="developer-parameters" data-collapsed={!developer} inert={!developer} aria-hidden={!developer} className="developer-content">
          <h3>随机种子</h3><div className="option-group">{([['random','每首随机'],['fixed','固定'],['increment','依次递增']] as const).map(([value,label])=><button type="button" aria-pressed={draft.seedMode===value} key={value} onClick={()=>onChange({seedMode:value})}>{label}</button>)}</div>
          {draft.seedMode!=='random'&&<label className="setting-field">{draft.seedMode==='fixed'?'固定种子':'起始种子'}<input id="field-seed" inputMode="numeric" value={draft.seed} onChange={e=>onChange({seed:e.target.value})}/></label>}
          <p className="setting-help">每首记录实际种子。固定种子可能生成相似或重复结果。</p>
          <label className="setting-field">乐谱规划<SelectControl value={config.cot} onChange={e=>update({cot:e.target.value as Config['cot']})}><option value="full">旋律与和弦</option><option value="melody">仅旋律</option><option value="off">关闭规划</option></SelectControl></label>
          <div className="parameter-grid">{parameters.map(f=><label className="setting-field" key={f.key}>{f.label}<input type="number" value={Number.isFinite(config[f.key])?config[f.key]:''} min={f.min} max={'max'in f?f.max:undefined} step={f.step} onChange={e=>update({[f.key]:e.target.value===''?NaN:Number(e.target.value)})}/></label>)}</div>
          <p className="setting-help">音乐序列预算官方默认值为 9000 tokens，范围为 200–24575。过低可能截断歌曲，不能用它精确指定时长。</p>
          <label className="setting-field">风格引导 · CFG<SelectControl value={config.cfg==='auto'?'auto':'custom'} onChange={e=>update({cfg:e.target.value==='auto'?'auto':1.5})}><option value="auto">自动</option><option value="custom">自定义</option></SelectControl></label>
          {config.cfg!=='auto'&&<label className="setting-field">CFG Scale<input type="number" min={0} max={20} step={.1} value={Number.isFinite(config.cfg)?config.cfg:''} onChange={e=>update({cfg:e.target.value===''?NaN:Number(e.target.value)})}/></label>}
        </div>
      </section>
      </>}
      {errors.length>0&&<div className="field-error" role="alert">{errors.map((e,i)=><p key={i}>{e.message}</p>)}</div>}
    </div>
  </Sheet>;
}
