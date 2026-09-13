"""Read-only monitoring and artifact verification for an already submitted UI run."""
import argparse,hashlib,json,sqlite3,time,urllib.request
from pathlib import Path
from .common import ROOT,TERMINAL,now,read_json,write_json,validate_artifacts

def verify(run_id,base):
    report={'runId':run_id,'baseUrl':base,'monitorStartedAt':now(),'gpuTasksStartedByMonitor':0,'samples':[]}
    def get(path): return json.load(urllib.request.urlopen(base+path,timeout=15))
    while True:
        state=get('/api/v1/state'); run=next(r for r in state['runs'] if r['id']==run_id)
        report['samples'].append({'at':now(),'state':run['state'],'elapsed':run['elapsed'],'progress':run['progress']})
        print(json.dumps(report['samples'][-1],ensure_ascii=False),flush=True)
        if run['state'] in TERMINAL: break
        time.sleep(3)
    report['run']=run; report['finishedAt']=now(); report['healthAfter']=get('/api/v1/health')
    database=sqlite3.connect((ROOT/'data/studio.sqlite3').as_uri()+'?mode=ro',uri=True)
    rows=database.execute("SELECT seq,at,data FROM events WHERE type='run.updated' AND json_extract(data,'$.id')=? ORDER BY seq",(run_id,)).fetchall(); database.close()
    report['persistedProgress']=[{'seq':seq,'at':at,'state':(r:=json.loads(raw))['state'],'elapsed':r['elapsed'],'progress':r['progress']} for seq,at,raw in rows]
    if run['state']=='succeeded':
        import numpy as np
        import soundfile as sf
        directory=ROOT/'data/runs'/run_id/'artifacts'; report['artifacts']=validate_artifacts(directory)
        attention=ROOT/'data/runs'/run_id/'attention-audit.json'
        if attention.is_file(): report['attentionAudit']=read_json(attention)
        manifest=read_json(directory/'result.json'); request=read_json(directory/'request.json'); config=read_json(directory/'config.json'); snapshot=run['snapshot']; d=snapshot['draft']; c=d['config']; effective=config['generation']['semantic']
        from .prompting import resolve_prompt
        style,lyrics=resolve_prompt(d)
        assert request['lyrics']==lyrics and request['style']==style and str(request['seed'])==snapshot['seed'] and request['id']==run_id
        assert request['cot']==c['cot'] and config['generation']['ode_steps']==c['odeSteps']
        assert manifest['weights']==snapshot['modelIdentities']
        for k,v in {'temperature':'temperature','topP':'top_p','topK':'top_k','repetitionPenalty':'repetition_penalty'}.items(): assert c[k]==effective[v]
        runtime_path=ROOT/'data/runs'/run_id/'runtime-settings.json'
        runtime=read_json(runtime_path) if runtime_path.is_file() else {}
        assert runtime.get('maxTokens',c['maxTokens'])==effective['max_tokens']
        report['runtimeSettings']=runtime
        audio,rate=sf.read(directory/'audio.flac',dtype='float32',always_2d=True)
        report['audioMetrics']={'sampleRate':rate,'channels':audio.shape[1],'frames':len(audio),'duration':len(audio)/rate,'finite':bool(np.isfinite(audio).all()),'rms':float(np.sqrt(np.mean(audio.astype(np.float64)**2))),'peak':float(np.max(np.abs(audio))),'clipRatio':float(np.mean(np.abs(audio)>=.9999))}
        audio_bytes=(directory/'audio.flac').read_bytes(); report['audioSHA256']=hashlib.sha256(audio_bytes).hexdigest()
        assert report['audioSHA256']==manifest['artifacts']['audio.flac']['sha256']
        audit_path=ROOT/'data/runs'/run_id/'reference-audit.json'
        if audit_path.is_file():
            audit=read_json(audit_path)
            raw=(ROOT/'data/runs'/run_id/'raw-abc.txt').read_text(encoding='utf-8')
            processed=(ROOT/'data/runs'/run_id/'processed-abc.txt').read_text(encoding='utf-8')
            assert audit['sourceAudioSha256']==d['reference']['sha256']
            assert audit['rawSha256']==hashlib.sha256(raw.encode('utf-8')).hexdigest()
            assert audit['processedSha256']==hashlib.sha256(processed.encode('utf-8')).hexdigest()
            report['referenceAudit']=audit
        report['track']=next(t for t in state['tracks'] if t.get('runId')==run_id)
        served=urllib.request.urlopen(base+report['track']['audioUrl'],timeout=15).read(); assert served==audio_bytes
        report['officialTiming']=manifest['timing']; report['truncated']=manifest['truncated']; report['requestSnapshotMatches']=True; report['httpAudioEqualsMaster']=True; report['status']='PASS'
    else: report['status']='FAILED'; report['error']=run.get('error')
    report['listeningReview']='未进行主观听感或歌词准确性验收'
    write_json(ROOT/'runtime/ui-generation-verification.json',report)
    phases=[]
    for item in report['persistedProgress']:
        if item['state'] not in phases: phases.append(item['state'])
    lines=['# 浏览器真实生成链路验证','',f"状态：{report['status']}。只读监测现有请求，未创建其他 GPU 任务。",'',f'- Run：`{run_id}`',f"- 实际 seed：`{run['snapshot']['seed']}`",f"- 服务端运行耗时：{run['elapsed']:.3f} 秒",f"- 持久化阶段：{' → '.join(phases)}",f"- 进度事件：{len(report['persistedProgress'])} 条；SQLite 历史只读补齐，监测脚本读取 state {len(report['samples'])} 次（未终态时每 3 秒）。"]
    if report['status']=='PASS':
        a=report['audioMetrics']; lines += [f"- 实际音频：{a['duration']:.6f} 秒，{a['sampleRate']} Hz，{a['channels']} 声道，PCM24 FLAC。",f"- SHA256：`{report['audioSHA256']}`",f"- 官方 verify_result、全部工件哈希与身份、请求和受理快照一致性：通过。",f"- HTTP 完整音频与磁盘母版字节完全一致：通过。",f"- 截断标记：{json.dumps(report['truncated'])}",f"- 数值：finite={a['finite']}，RMS={a['rms']:.8f}，peak={a['peak']:.8f}，clipRatio={a['clipRatio']:.8f}。"]
    lines += ['',report['listeningReview']+'；数值与结构通过不能推断音质或中文歌词准确性。','', '完整快照、实际阶段计数、官方耗时与检查细节见 `ui-generation-verification.json`。']
    (ROOT/'runtime/ui-generation-verification.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('run_id'); parser.add_argument('--base',default='http://127.0.0.1:4174'); args=parser.parse_args()
    result=verify(args.run_id,args.base); print(json.dumps({'status':result['status'],'state':result['run']['state'],'duration':result.get('audioMetrics',{}).get('duration')},ensure_ascii=False))
