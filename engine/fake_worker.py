"""Explicit CPU subprocess fixture, never selectable through the production HTTP API."""
import json,os,sys,time
from pathlib import Path
from .common import ROOT,read_json,write_json,digest,validate_artifacts

def make_artifacts(directory):
    import numpy as np
    import soundfile as sf
    from yue2.storage import collect_hashes,identity
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=False)
    request={'id':'cpu-test','style':'CPU TEST','lyrics':'CPU TEST','seed':1,'cot':'off','cfg_scale':None}; config={}; weights={}
    write_json(directory/'request.json',request); write_json(directory/'config.json',config)
    for name in ('prefix','semantic','latent'): np.save(directory/(name+'.npy'),np.zeros((4,2),dtype=np.float32))
    audio=np.column_stack([np.sin(np.arange(12000)*.02)*.1]*2)
    sf.write(directory/'audio.flac',audio,48000,subtype='PCM_24')
    write_json(directory/'result.json',{'status':'complete','identity':identity({'request':request,'config':config,'weights':weights}),'weights':weights,'truncated':{'abc':False,'semantic':False},'artifacts':collect_hashes(directory)})

def main():
    directory,data=map(lambda x:Path(x).resolve(),sys.argv[1:])
    if os.environ.get('YUE2_TEST_WORKER')!='1' or data==ROOT/'data': raise RuntimeError('Explicit isolated CPU test mode required')
    for phase in ('checking','planning','generating_tokens','synthesizing','decoding','finalizing'):
        for i in range(5):
            if (directory/'cancel.request').exists():
                print(json.dumps({'kind':'outcome','status':'cancelled'}),flush=True); return
            print(json.dumps({'kind':'progress','state':phase,'modelLoaded':False,'progress':{'phase':phase,'detail':'CPU TEST','completed':i,'total':5,'unit':'steps','elapsedSeconds':0}}),flush=True); time.sleep(.04)
    make_artifacts(directory/'artifacts.partial'); metadata=validate_artifacts(directory/'artifacts.partial')
    write_json(directory/'commit.json',{'runId':directory.name,'snapshotHash':digest(read_json(directory/'snapshot.json')),'identity':metadata['identity'],'metadata':metadata})
    os.rename(directory/'artifacts.partial',directory/'artifacts')
    print(json.dumps({'kind':'outcome','status':'succeeded','metadata':metadata}),flush=True)
if __name__=='__main__': main()
