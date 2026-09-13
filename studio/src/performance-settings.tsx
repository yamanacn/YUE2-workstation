import {SelectControl} from './select-control';
import {performancePresets,type Config,type PerformanceConfig} from './domain';
import {FadersIcon} from './icons';
import './performance-settings.css';

const presets=[['performance','性能优先','BF16 · 较大分块'],['balanced','显存优化','BF16 · AR 卸载 · 默认'],['extreme','极限显存','FP8 AR · 实验']] as const;
export function PerformanceSettings({config,onChange}:{config:Config;onChange:(patch:Partial<Config>)=>void}){
  const p={...performancePresets.balanced,...config.performance};
  const update=(patch:Partial<PerformanceConfig>)=>onChange({performance:{...p,...patch}});
  const selected=presets.find(([key])=>Object.entries(performancePresets[key]).every(([k,v])=>p[k as keyof PerformanceConfig]===v)&&config.cfg===1)?.[0];
  return <div className="performance-settings">
    <div className="creative-heading"><FadersIcon size={19}/><h3>运行方案</h3><span className="creative-badge">{selected?'':'自定义'}</span></div>
    <div className="performance-presets" role="group" aria-label="显存预设">{presets.map(([key,title,description])=><button type="button" key={key} aria-pressed={selected===key} onClick={()=>onChange({performance:{...performancePresets[key]},cfg:1})}><strong>{title}</strong><span>{description}</span></button>)}</div>
    <section className="performance-section"><h3>模型与注意力</h3>
      <label className="setting-field">AR 权重精度<SelectControl value={p.quantization} onChange={e=>update({quantization:e.target.value as PerformanceConfig['quantization']})}><option value="none">BF16</option><option value="fp8">FP8（实验）</option></SelectControl></label>
      {p.quantization==='fp8'&&<p className="setting-help">FP8 仅用于 AR。可启用实验图加速；本机验证通过才生效，否则使用兼容路径。与兼容模式可能生成不同结果；硬件不支持 FP8 时回退 BF16。</p>}
      {p.quantization==='fp8'&&<label className="performance-toggle"><span>FP8 CUDA Graph（实验）</span><input type="checkbox" role="switch" checked={p.fp8CudaGraph??false} onChange={e=>update({fp8CudaGraph:e.target.checked})}/></label>}
      <label className="performance-toggle"><span>NAR 阶段卸载 AR 权重</span><input type="checkbox" role="switch" checked={p.offloadAr} onChange={e=>update({offloadAr:e.target.checked})}/></label>
      <label className="setting-field">注意力后端<SelectControl value={p.attention} onChange={e=>update({attention:e.target.value as PerformanceConfig['attention']})}><option value="auto">优先 FlashAttention · 自动回退</option><option value="sdpa">PyTorch SDPA</option></SelectControl></label>
      <label className="setting-field">SDPA 查询分块<SelectControl value={p.queryChunkSize} onChange={e=>update({queryChunkSize:Number(e.target.value) as PerformanceConfig['queryChunkSize']})}>{[64,128,256].map(v=><option key={v} value={v}>{v}</option>)}</SelectControl></label>
    </section>
    <section className="performance-section"><h3>显存与解码</h3><div className="parameter-grid">
      <label className="setting-field">显存预算（GiB）<input type="number" min="0" step="0.5" value={p.memoryBudgetGiB} onChange={e=>update({memoryBudgetGiB:e.target.value===''?NaN:Number(e.target.value)})}/></label>
      <label className="setting-field">VAE 解码分块<SelectControl value={p.vaeCoreFrames} onChange={e=>update({vaeCoreFrames:Number(e.target.value) as PerformanceConfig['vaeCoreFrames']})}>{[256,512,1024].map(v=><option key={v} value={v}>{v} frames{v===256?' · 实验':''}</option>)}</SelectControl></label>
    </div><p className="setting-help">0 为自动读取总显存，官方运行时预留 2 GiB。预算不代表模型一定能装入；分块越小，解码峰值通常越低。</p></section>
    <section className="performance-section"><h3>序列与引导</h3>
      <label className="performance-toggle"><span>动态序列预算</span><input type="checkbox" role="switch" checked={p.dynamicTokens} onChange={e=>update({dynamicTokens:e.target.checked})}/></label>
      <div className="parameter-grid"><label className="setting-field">目标时长（秒）<input type="number" min="0" max="960" disabled={!p.dynamicTokens} value={p.targetSeconds} onChange={e=>update({targetSeconds:e.target.value===''?NaN:Number(e.target.value)})}/></label>
      <label className="setting-field">序列预算上限<input type="number" min="200" max="24575" value={config.maxTokens} onChange={e=>onChange({maxTokens:Number(e.target.value)})}/></label></div>
      <p className="setting-help">目标为 0 时采用参考片段时长；没有参考时保留预算上限。按 25 tokens/秒加 10% 和 128 tokens 余量估算，可能提前结束或截断，不保证精确时长。</p>
      <label className="performance-toggle"><span>CFG 单分支（1.0）</span><input type="checkbox" role="switch" checked={config.cfg===1} onChange={e=>onChange({cfg:e.target.checked?1:'auto'})}/></label>
      <p className="setting-help">三档预设均设置 CFG 为 1，减少 AR 缓存与计算。会改变风格引导效果；其他 CFG 值可在生成参数中调整。</p>
    </section>
  </div>;
}
