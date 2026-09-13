"""Path-resolved cover requests and deterministic transcription cache."""
import hashlib,math,subprocess,os,time
from pathlib import Path
from .common import ROOT,read_json,write_json,digest
from .runtime_paths import score_python,runtime_environment
SHEET_REV='eab522a8168e8b8b8c4856bf8609cd86198f01fe'
MERT_REV='d8ba1c745e733b3908ce6ad16ebeb17ac7600a42'
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def resolve_reference(source,data):
    if not isinstance(source,dict) or not isinstance(source.get('id'),str):raise ValueError('参考音频记录无效')
    records=read_json(Path(data)/'reference-paths.json')
    record=records.get(source['id'])
    if not record or not Path(record['path']).is_file():raise ValueError('参考音频不存在或已移动，请重新选择')
    region=source.get('range');preserve=source.get('preserve','melody');strength=source.get('strength','balanced')
    if preserve not in ('melody','full'):raise ValueError('翻唱保留内容无效')
    if not isinstance(strength,str):raise ValueError('参考强度无效')
    if strength=='loose': strength='free'
    if strength not in ('free','balanced','faithful'):raise ValueError('参考强度无效')
    if region is not None and (not isinstance(region,list) or len(region)!=2 or any(type(n) not in (int,float) or not math.isfinite(n) for n in region) or region[0]<0 or region[1]-region[0]<.1):raise ValueError('音频选区无效')
    result={'id':record['id'],'path':record['path'],'name':record['name'],'range':region,'preserve':preserve,
            'strength':strength,'sha256':sha(record['path'])}
    return result
def transcribe_reference(source,run_dir,data,check,progress):
    if not Path(source['path']).is_file() or sha(source['path'])!=source['sha256']:raise ValueError('参考音频已移动或发生变化，请重新选择后生成')
    identity={'audio':source['sha256'],'range':source['range'],'preserve':source['preserve'],'sheet':SHEET_REV,'mert':MERT_REV,'adapter':1}
    cache=Path(data)/'transcriptions'/digest(identity);score=cache/'score.abc';manifest=cache/'manifest.json'
    if score.exists() and manifest.exists() and read_json(manifest).get('scoreSha256')==sha(score):
        progress('复用已提取的旋律');write_json(run_dir/'reference-score.json',{'cache':str(cache),'identity':identity,'reused':True});return score.read_text(encoding='utf-8')
    cache.mkdir(parents=True,exist_ok=True);request=run_dir/'transcribe-request.json';write_json(request,source)
    try: python=score_python()
    except RuntimeError as exc: raise ValueError(str(exc)) from exc
    progress('正在提取旋律与和弦' if source['preserve']=='full' else '正在提取旋律')
    with (run_dir/'transcription.log').open('w',encoding='utf-8') as log:
        env=runtime_environment(); env['HF_HUB_OFFLINE']='1'
        process=subprocess.Popen([str(python),'-X','utf8','-u','-m','engine.transcribe_worker',str(request),str(cache)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=env,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            while process.poll() is None:check();time.sleep(.25)
            check()
            if process.returncode:raise RuntimeError('音频转谱失败：'+(run_dir/'transcription.log').read_text(encoding='utf-8')[-1600:])
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=15)
    if not score.is_file() or not score.read_text(encoding='utf-8').strip():raise ValueError('转谱未产生可用旋律')
    write_json(manifest,{'identity':identity,'scoreSha256':sha(score)})
    write_json(run_dir/'reference-score.json',{'cache':str(cache),'identity':identity,'reused':False})
    return score.read_text(encoding='utf-8')
