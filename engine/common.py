from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
CODE = 'a621dcc003143844927ae7d2a1295d05f356336c'
PROFILE = {'backend':'torch','attention':'auto','memoryBudgetGiB':'auto','quantization':'none','offloadAr':True,
 'modelName':'m-a-p/YuE2-3B','decoderName':'m-a-p/YuE2-Vae',
 'modelRevision':'1a96eca688d6ae5d7f0feb88573fec89920fcd19','vaeRevision':'95535e72a97bc0f09b8ada125d26b4009428c0e8','codeRevision':CODE}
TERMINAL = {'succeeded','failed','cancelled','interrupted'}
ORDER = ['queued','checking','planning','generating_tokens','synthesizing','decoding','finalizing']

def now(): return datetime.now(timezone.utc).isoformat()
def ms(): return int(time.time()*1000)
def read_json(path): return json.loads(Path(path).read_text(encoding='utf-8'))
def canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def digest(value): return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()
def write_json(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    with temporary.open('w',encoding='utf-8') as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary,path)

def expected_weights():
    identities={}
    for key,name in (('mot','YuE2-3B'),('vae','YuE2-Vae')):
        directory=ROOT/'models'/name
        identities[key]={'files':read_json(directory/'weights_manifest.json')['files'],
                         'config_sha256':hashlib.sha256((directory/'config.json').read_bytes()).hexdigest()}
    return identities

class FileLock:
    def __init__(self,path): self.path=Path(path); self.file=None
    def acquire(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.file=self.path.open('a+b'); self.file.seek(0)
        if self.path.stat().st_size == 0: self.file.write(b'0'); self.file.flush()
        self.file.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close(); self.file=None; return False
        return True
    def close(self):
        if self.file: self.file.close(); self.file=None

def validate_artifacts(directory,expected_identity=None):
    """Official manifest verification plus streamed FLAC sample validation; no torch."""
    import numpy as np
    import soundfile as sf
    from yue2.storage import verify_result, identity
    directory=Path(directory).resolve()
    manifest=read_json(directory/'result.json')
    allowed={'audio.flac','prefix.npy','semantic.npy','latent.npy','request.json','config.json','plan.json','plan_manifest.json','abc_tokens.npy','score.abc'}
    if set(manifest.get('artifacts',{}))-allowed: raise ValueError('Unexpected artifact names')
    for name in manifest.get('artifacts',{}):
        path=directory/name
        if path.is_symlink() or not path.resolve().is_relative_to(directory): raise ValueError('Unsafe artifact path')
    result=verify_result(directory,expected_identity=expected_identity)
    request=read_json(directory/'request.json'); config=read_json(directory/'config.json')
    if identity({'request':request,'config':config,'weights':result['weights']}) != result['identity']:
        raise ValueError('Result identity does not match request/config/weights')
    info=sf.info(directory/'audio.flac')
    if info.frames<=0 or info.samplerate!=48000 or info.channels!=2 or info.format!='FLAC' or info.subtype!='PCM_24':
        raise ValueError('Expected nonempty 48 kHz stereo PCM24 FLAC')
    with sf.SoundFile(directory/'audio.flac') as audio:
        while len(block:=audio.read(65536,dtype='float32',always_2d=True)):
            if not np.isfinite(block).all(): raise ValueError('Nonfinite audio samples')
    return {'identity':result['identity'],'duration':info.duration,'sampleRate':info.samplerate,'channels':info.channels,
            'subtype':info.subtype,'truncated':result.get('truncated',{}),'artifacts':result['artifacts']}
