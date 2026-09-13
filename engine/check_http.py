"""Read-only service/audio transport verification; starts no generation."""
import argparse,hashlib,json,urllib.request
from pathlib import Path
from .common import ROOT,now,write_json

def check(base):
    def get(path,headers=None,method='GET'):
        return urllib.request.urlopen(urllib.request.Request(base+path,headers=headers or {},method=method),timeout=15)
    health=json.load(get('/api/v1/health')); state=json.load(get('/api/v1/state'))
    assert health['service']=='yue2-studio' and health['apiVersion']==1
    assert state['tracks'],'Expected verified imported track'
    track=next(t for t in state['tracks'] if t['audioKind']=='generated'); path=track['audioUrl']
    full=get(path); data=full.read(); assert full.headers['Content-Type']=='audio/flac' and data[:4]==b'fLaC'
    partial=get(path,{'Range':'bytes=1024-4095'}); assert partial.status==206 and partial.read()==data[1024:4096]
    suffix=get(path,{'Range':'bytes=-128'}); assert suffix.read()==data[-128:]
    head=get(path,method='HEAD'); assert head.read()==b'' and int(head.headers['Content-Length'])==len(data)
    artifacts=json.load(get('/api/v1/runs/'+track['runId']+'/artifacts'))
    expected=next(a['sha256'] for a in artifacts['artifacts'] if a['name']=='audio.flac'); actual=hashlib.sha256(data).hexdigest(); assert actual==expected
    return {'status':'PASS','checkedAt':now(),'baseUrl':base,'health':health,'queuePaused':state['queuePaused'],'trackId':track['id'],'runId':track['runId'],'duration':track['duration'],'flacBytes':len(data),'sha256':actual,'checks':['GET FLAC','Range bytes=1024-4095 exact','suffix Range exact','HEAD length/no body','download SHA256 equals official manifest'],'gpuGenerationStarted':False}
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--base',default='http://127.0.0.1:8767'); a=p.parse_args(); result=check(a.base)
    write_json(ROOT/'runtime/backend-http-verification.json',result); print(json.dumps(result,ensure_ascii=False,indent=2))
