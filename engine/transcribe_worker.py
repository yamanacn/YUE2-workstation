"""Isolated SheetSage2 inference; source audio stays in memory."""
import sys,subprocess,json
from pathlib import Path
from .common import ROOT,read_json,write_json

def main(request,output):
    import numpy as np
    import torch
    import imageio_ffmpeg
    from transformers import AutoModel
    source=read_json(request)
    command=[imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-nostdin','-i',source['path']]
    if source['range']:
        start,end=source['range'];command+=['-ss',str(start),'-t',str(end-start)]
    command+=['-vn','-ac','1','-ar','24000','-f','f32le','pipe:1']
    decoded=subprocess.run(command,capture_output=True,timeout=600)
    if decoded.returncode:raise ValueError(decoded.stderr.decode(errors='replace'))
    audio=np.frombuffer(decoded.stdout,dtype='<f4').copy()
    if len(audio)<2400:raise ValueError('所选音频片段过短或已超出文件长度')
    if source['range'] and abs(len(audio)/24000-(source['range'][1]-source['range'][0]))>.1:raise ValueError('所选范围已超出音频长度，请重新选取')
    torch.set_num_threads(8)
    print('Loading SheetSage2',flush=True)
    model=AutoModel.from_pretrained(str(ROOT/'models/SheetSage2'),trust_remote_code=True,local_files_only=True,base_model_path=str(ROOT/'models/MERT-v2-FullSong')).eval().to('cuda')
    print('Transcribing',len(audio)/24000,'seconds',flush=True)
    # Ask SheetSage2 to persist its lossless timed exports alongside the ABC.
    # The engine still consumes ABC for compatibility, while events/LAB/MIDI
    # remain available for diagnostics and future instrument-only rebuilding.
    result=model.transcribe(audio,output_dir=str(output),sampling_rate=24000,
                            melody_only=source['preserve']=='melody',dtype='bf16')
    if not result.get('abc') or result.get('abc_error'):raise ValueError(result.get('abc_error') or '空乐谱')
    Path(output).mkdir(parents=True,exist_ok=True)
    (Path(output)/'score.abc').write_text(result['abc'],encoding='utf-8')
    payload=result.get('payload',{})
    # Some revisions return exports in-memory even when output_dir is ignored.
    if payload.get('events') is not None:
        write_json(Path(output)/'events.json',payload['events'])
    for name,content in payload.get('labs',{}).items():
        (Path(output)/(name if name.endswith('.lab') else name+'.lab')).write_text(content,encoding='utf-8')
    write_json(Path(output)/'transcription-info.json',{'warnings':result.get('warnings',[]),'source':source,
        'duration':len(audio)/24000,'events':result.get('events',0),'vocalNotes':result.get('vocal_notes',0),
        'instrumentalNotes':result.get('instrumental_notes',0)})
    print('Transcription complete',flush=True)
if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
