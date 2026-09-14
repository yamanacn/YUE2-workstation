"""One isolated GPU job. stdout is exclusively protocol NDJSON."""
from __future__ import annotations
from contextlib import contextmanager,redirect_stdout
import argparse,json,os,sys,time,traceback
import hashlib
from pathlib import Path
from .common import ROOT,CODE,FileLock,read_json,write_json,validate_artifacts

def reference_audit(reference,raw_abc,processed_abc,stats):
    def text_sha(value): return hashlib.sha256(value.encode('utf-8')).hexdigest()
    return {'strength':stats.get('strength',reference.get('strength','balanced')),
            'preserve':reference.get('preserve','melody'),
            'sourceAudioSha256':reference['sha256'],
            'rawSha256':text_sha(raw_abc),'processedSha256':text_sha(processed_abc),
            'rawBytes':len(raw_abc.encode('utf-8')),'processedBytes':len(processed_abc.encode('utf-8')),
            'stats':stats}

def execute(run_dir,data_dir):
    protocol=sys.stdout
    start=time.monotonic(); phase='checking'; loaded=False
    def emit(kind,**values):
        protocol.write(json.dumps({'kind':kind,**values},ensure_ascii=False,allow_nan=False)+'\n'); protocol.flush()
    def cancelled():
        heartbeat=data_dir/'service.heartbeat'
        return (run_dir/'cancel.request').exists() or not heartbeat.exists() or time.time()-heartbeat.stat().st_mtime>15
    def check():
        if cancelled(): raise InterruptedError('取消请求已在计算边界确认')
    def progress(detail,completed=None,total=None,unit=None):
        emit('progress',state=phase,modelLoaded=loaded,progress={'phase':phase,'detail':detail,'completed':completed,'total':total,'unit':unit,'elapsedSeconds':round(time.monotonic()-start,3)})
    lock=FileLock(data_dir/'gpu-worker.lock'); pipe=None; outcome={}
    with redirect_stdout(sys.stderr):
        try:
            if not lock.acquire(): raise RuntimeError('Another GPU worker still owns the execution lock')
            from .runtime_integrity import verify_runtime
            write_json(run_dir/'runtime-integrity.json', verify_runtime())
            check()
            snapshot=read_json(run_dir/'snapshot.json'); d=snapshot['draft']; c=d['config']
            from .performance import settings, token_budget, fp8_unavailable_reason
            runtime=settings(c)
            abc=d.get('abc') or None
            if d.get('reference'):
                from .cover import transcribe_reference
                from .abc_processor import ABCReferenceProcessor
                phase='planning'
                raw_abc=transcribe_reference(d['reference'],run_dir,data_dir,check,progress)
                strength=d['reference'].get('strength','balanced')
                processor=ABCReferenceProcessor()
                abc=processor.process(raw_abc,strength)
                (run_dir/'raw-abc.txt').write_text(raw_abc,encoding='utf-8')
                (run_dir/'processed-abc.txt').write_text(abc,encoding='utf-8')
                audit=reference_audit(d['reference'],raw_abc,abc,processor.last_stats)
                write_json(run_dir/'reference-audit.json',audit)
                progress(f"参考强度: {audit['strength']} · 保留 {audit['stats'].get('outputNotes',0)}/{audit['stats'].get('inputNotes',0)} 个音符")
                check()
            from yue2 import YuE2Pipeline
            import torch
            total_gib=torch.cuda.get_device_properties(0).total_memory/2**30
            memory_budget=runtime['memoryBudgetGiB'] or total_gib
            quantization=runtime['quantization']
            quantization_fallback=None
            if quantization=='fp8':
                quantization_fallback=fp8_unavailable_reason()
                if quantization_fallback:
                    quantization='none'
                    progress('FP8 不可用，回退 BF16')
            flash_available=torch.backends.cuda.is_flash_attention_available()
            reference_seconds=None
            if d.get('reference'):
                selection=d['reference'].get('range')
                if selection:
                    reference_seconds=selection[1]-selection[0]
                else:
                    import soundfile as sf
                    reference_seconds=sf.info(d['reference']['path']).duration
            effective_tokens=token_budget(c,reference_seconds)
            runtime_audit={'requested':runtime,'memoryBudgetGiB':memory_budget,'quantization':quantization,
                           'quantizationFallback':quantization_fallback,'maxTokens':effective_tokens,
                           'cfg':c['cfg'],'flashAvailable':flash_available}
            write_json(run_dir/'runtime-settings.json',runtime_audit)
            from .attention import install_nar_policy, is_flash_capability_error, external_capability_error
            from .ar_attention import install_ar_policy, external_flash_installed
            read_ar_attention=install_ar_policy(runtime['attention'], fp8_cuda_graph=runtime['fp8CudaGraph'])
            read_attention=install_nar_policy(runtime['attention'],runtime['queryChunkSize'])
            from yue2.protocol import GenerationConfig
            class ObservedPipeline(YuE2Pipeline):
                def effective_config(self,request,abc_sampling=None,semantic_sampling=None):
                    config=super().effective_config(request,abc_sampling,semantic_sampling)
                    adapters=getattr(self,'_adapter_config',None)
                    if adapters: config['adapters']=adapters
                    return config
                @contextmanager
                def _status(self,label,*,total=None,unit=None):
                    nonlocal phase,loaded
                    check()
                    mapped={'Verifying model files':'checking','Planning score':'planning','Generating song':'generating_tokens','Synthesizing audio':'synthesizing','Loading audio decoder':'decoding','Decoding audio':'decoding'}
                    phase=mapped.get(label,phase)
                    if label=='Loading audio decoder': loaded=False
                    progress(label,0 if unit else None,total,unit)
                    class Stage:
                        completed=0; last=0.; denominator=total
                        def advance(self,count=1): self.update(self.completed+count)
                        def update(self,completed,total=None):
                            check(); self.completed=completed
                            if total is not None: self.denominator=total
                            if time.monotonic()-self.last>=.25 or completed==self.denominator:
                                progress(label,completed,self.denominator,unit); self.last=time.monotonic()
                        def finish(self,status='completed'): progress(label+' ('+status+')',self.completed,self.denominator,unit)
                    stage=Stage()
                    try:
                        yield stage
                    finally:
                        if label in {'Planning score', 'Generating song', 'Synthesizing audio'}:
                            write_json(run_dir/'attention-audit.json', {**read_attention(), 'arBackend': ar_backend, 'ar': read_ar_attention()})
                    if label=='Loading model': loaded=True
                    progress(label,stage.completed if unit else None,stage.denominator,unit)
                    check()
            def build_pipe(backend):
                return ObservedPipeline.from_pretrained(model=str(ROOT/'models/YuE2-3B'),vae=str(ROOT/'models/YuE2-Vae'),local_files_only=True,
                    device='cuda',backend=backend,memory_budget_gib=memory_budget,quantization=quantization,offload_ar=runtime['offloadAr'],vae_core_frames=runtime['vaeCoreFrames'],
                    generation_config=GenerationConfig(ode_steps=c['odeSteps']),progress=True)
            def apply_adapters(target_pipe):
                base_weights={k:v for k,v in (snapshot.get('modelIdentities') or {}).items() if k in ('mot','vae')}
                if target_pipe.weights!=base_weights: raise ValueError('Model identities changed since this request was accepted')
                from .adapters import normalize_request, adapter_identity, prepare_pipeline_adapters
                request=normalize_request(d.get('config',{}).get('adapters'))
                audit=prepare_pipeline_adapters(target_pipe,request,(snapshot.get('modelIdentities') or {}).get('adapters'),quantization,progress)
                if audit:
                    target_pipe.weights={**target_pipe.weights,'adapters':adapter_identity(request)}
                    write_json(run_dir/'adapter-audit.json',audit)
                write_json(run_dir/'weights-identity.json',target_pipe.weights)
                return audit
            ar_backend='torch'
            runtime_audit['arBackend']=ar_backend
            runtime_audit['nativeFlashAvailable']=flash_available
            runtime_audit['externalFlashAvailable']=external_flash_installed()
            write_json(run_dir/'runtime-settings.json',runtime_audit)
            pipe=build_pipe(ar_backend)
            apply_adapters(pipe)
            check()
            from .prompting import resolve_prompt
            style,lyrics=resolve_prompt(d)
            request_kwargs={'abc':abc,'style':style,'lyrics':lyrics,'id':run_dir.name,'cot':c['cot'],'seed':int(snapshot['seed']),
                'cfg_scale':None if c['cfg']=='auto' else c['cfg'],
                'semantic_sampling':{'temperature':c['temperature'],'top_p':c['topP'],'top_k':c['topK'],'repetition_penalty':c['repetitionPenalty'],'max_tokens':effective_tokens},'cancelled':cancelled}
            from .instrumental import generate as generate_with_instrumental
            try:
                song=generate_with_instrumental(pipe,request_kwargs,d.get('vocalMode'),run_dir,check,progress)
            except (RuntimeError, NotImplementedError) as error:
                if ar_backend!='torch' or not is_flash_capability_error(error) or not external_capability_error(error):
                    raise
                pipe.close(); pipe=None
                ar_backend='torch-eager-fallback'
                runtime_audit['arBackend']=ar_backend
                runtime_audit['attentionFallback']=str(error)
                write_json(run_dir/'runtime-settings.json',runtime_audit)
                progress('FlashAttention 不可用，回退到 SDPA')
                pipe=build_pipe('torch-eager')
                apply_adapters(pipe)
                song=generate_with_instrumental(pipe,request_kwargs,d.get('vocalMode'),run_dir,check,progress)
            attention=read_attention()
            attention['arBackend']=ar_backend
            attention['ar']=read_ar_attention()
            write_json(run_dir/'attention-audit.json',attention)
            check(); phase='finalizing'; progress(f"注意力后端: {attention['selected']}")
            staging=run_dir/'artifacts.partial'; song.save_artifacts(staging)
            metadata=validate_artifacts(staging,song.request_identity); check()
            # Intent is durable before rename; controller reconciles this on restart.
            write_json(run_dir/'commit.json',{'runId':run_dir.name,'snapshotHash':__import__('engine.common',fromlist=['digest']).digest(snapshot),'identity':metadata['identity'],'metadata':metadata})
            check(); os.rename(staging,run_dir/'artifacts')
            outcome={'status':'succeeded','metadata':metadata}
        except InterruptedError as exc: outcome={'status':'cancelled','error':str(exc)}
        except BaseException as exc:
            traceback.print_exc(); outcome={'status':'failed','error':f'{type(exc).__name__}: {exc}'}
        finally:
            if pipe is not None:
                try: pipe.close()
                except BaseException as exc: outcome={'status':'failed','error':f'GPU cleanup failed: {exc}'}
            lock.close()
    emit('outcome',**outcome)
    return 0 if outcome.get('status') in {'succeeded','cancelled'} else 1

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('run_dir',type=Path); p.add_argument('data_dir',type=Path); a=p.parse_args()
    sys.exit(execute(a.run_dir.resolve(),a.data_dir.resolve()))
