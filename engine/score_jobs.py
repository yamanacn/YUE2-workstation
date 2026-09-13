"""Independent score tasks, scheduled serially with music generation."""
import json,os,re,subprocess,threading,time
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import FileResponse
from .common import ROOT,FileLock,ms,read_json
from .cover import resolve_reference,transcribe_reference
from .runtime_paths import score_python,runtime_environment
ACTIVE={'queued','analyzing','rendering','cancelling'}

class ScoreJobs:
    def __init__(self,store):
        self.store=store;self.lock=threading.RLock();self.current=None
        with store.lock:
            store.db.execute('CREATE TABLE IF NOT EXISTS score_jobs(id TEXT PRIMARY KEY, record TEXT NOT NULL)');store.db.commit()
    def directory(self,id):
        if not isinstance(id,str) or not re.fullmatch(r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',id):raise HTTPException(400,'无效谱曲记录')
        return self.store.data/'scores'/id
    def all(self):
        with self.store.lock:return sorted([json.loads(x[0]) for x in self.store.db.execute('SELECT record FROM score_jobs')],key=lambda r:r['created'],reverse=True)
    def get(self,id):
        self.directory(id)
        with self.store.lock:
            row=self.store.db.execute('SELECT record FROM score_jobs WHERE id=?',(id,)).fetchone()
        if not row:raise HTTPException(404,'谱曲记录不存在')
        return json.loads(row[0])
    def save(self,r):
        with self.store.lock:
            self.store.db.execute('INSERT OR REPLACE INTO score_jobs VALUES(?,?)',(r['id'],json.dumps(r,ensure_ascii=False)));self.store.db.commit()
        return r
    def update(self,id,**values):
        with self.lock:
            r=self.get(id)
            if r['state']=='cancelling':
                if values.get('state') in ('analyzing','rendering','succeeded'):raise InterruptedError('已取消分析')
                if 'state' not in values:return r
            r.update(values,updated=ms());return self.save(r)
    def submit(self,body):
        id=body.get('requestId')
        self.directory(id or '')
        with self.lock:
            try:
                old=self.get(id)
            except HTTPException as exc:
                if exc.status_code!=404:raise
            else:
                if old.get('request')!=body:raise HTTPException(409,'请求编号已用于另一份分析')
                return old
            source=body.get('source',{})
            if not isinstance(source,dict):raise HTTPException(400,'音频来源无效')
            mode=body.get('mode','full')
            if mode not in ('full','melody'):raise HTTPException(400,'转谱模式无效')
            try:source=resolve_reference({**source,'preserve':mode,'strength':'faithful'},self.store.data)
            except (ValueError,KeyError,FileNotFoundError) as exc:raise HTTPException(400,str(exc))
            r={'id':id,'request':body,'source':source,'mode':mode,'title':Path(source['name']).stem,'created':ms(),'updated':ms(),'state':'queued','stage':'等待分析','hasAbc':False,'artifacts':[],'warnings':[],'error':None}
            return self.save(r)
    def cancel(self,id):
        with self.lock:
            r=self.get(id)
            if r['state']=='queued':return self.update(id,state='cancelled',stage='已取消')
            if r['state'] in ACTIVE:return self.update(id,state='cancelling',stage='正在取消')
            return r
    def recover(self):
        for r in self.all():
            if r['state'] in ACTIVE-{'queued'}:self.update(r['id'],state='interrupted',stage='任务已中断',error='服务中断，请重新分析；已有 ABC 仍可查看。')
    def rerender(self,id):
        with self.lock:
            r=self.get(id)
            if r['state'] in ACTIVE:raise HTTPException(409,'当前任务仍在运行')
            if not r['hasAbc']:raise HTTPException(400,'尚未生成 ABC')
            return self.update(id,state='queued',stage='等待排版',renderOnly=True,error=None)
    def run(self,r,stop):
        id=r['id'];directory=self.directory(id);directory.mkdir(parents=True,exist_ok=True)
        gpu=FileLock(self.store.data/'gpu-worker.lock')
        if not gpu.acquire():return
        self.current=id
        def check():
            if stop.is_set() or self.get(id)['state']=='cancelling':raise InterruptedError('已取消分析')
            (self.store.data/'service.heartbeat').touch()
        def progress(text):
            check();self.update(id,stage=text)
        try:
            with self.lock:
                if self.get(id)['state']!='queued':return
                self.update(id,state='analyzing',stage='读取音频')
            if not r.get('renderOnly'):
                abc=transcribe_reference(r['source'],directory,self.store.data,check,progress)
                check()
                temporary=directory/'score.abc.tmp';temporary.write_text(abc,encoding='utf-8');temporary.replace(directory/'score.abc')
                cache=Path(read_json(directory/'reference-score.json')['cache'])
                info=read_json(cache/'transcription-info.json') if (cache/'transcription-info.json').exists() else {}
                self.update(id,hasAbc=True,warnings=info.get('warnings',[]),duration=info.get('duration'),reused=read_json(directory/'reference-score.json')['reused'])
            check();self.update(id,state='rendering',stage='正在排版五线谱')
            with (directory/'render.log').open('w',encoding='utf-8') as log:
                process=subprocess.Popen([str(score_python()),'-X','utf8','-m','engine.score_render',str(directory)],cwd=ROOT,stdout=log,stderr=log,env=runtime_environment(),creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                try:
                    while process.poll() is None:check();time.sleep(.25)
                    check()
                    if process.returncode:raise RuntimeError('五线谱排版失败，ABC 已保留。'+(directory/'render.log').read_text(encoding='utf-8')[-1000:])
                finally:
                    if process.poll() is None:process.terminate();process.wait(timeout=15)
            names=['score.abc']+sorted(p.name for p in (directory/'rendered').iterdir() if p.suffix in ('.svg','.png','.pdf'))
            with self.lock:
                check();self.update(id,state='succeeded',stage='分析完成',artifacts=names,error=None)
        except InterruptedError:self.update(id,state='cancelled',stage='已取消')
        except Exception as exc:self.update(id,state='failed',stage='排版失败' if self.get(id)['hasAbc'] else '分析失败',error=str(exc))
        finally:gpu.close();self.current=None

def install_score_routes(app,jobs):
    @app.get('/api/v1/scores')
    def listing():return jobs.all()
    @app.post('/api/v1/scores')
    def submit(body:dict):return jobs.submit(body)
    @app.post('/api/v1/scores/{id}/cancel')
    def cancel(id:str):return jobs.cancel(id)
    @app.post('/api/v1/scores/{id}/render')
    def render(id:str):return jobs.rerender(id)
    @app.get('/api/v1/scores/{id}/abc')
    def abc(id:str):
        jobs.get(id);p=jobs.directory(id)/'score.abc'
        if not p.is_file():raise HTTPException(404,'ABC 尚未就绪')
        return {'abc':p.read_text(encoding='utf-8')}
    @app.get('/api/v1/scores/{id}/artifacts/{name}')
    def artifact(id:str,name:str):
        r=jobs.get(id)
        if name!='score.abc' and name not in r['artifacts']:raise HTTPException(404,'产物尚未就绪')
        if name!='score.abc' and not re.fullmatch(r'score(?:_\d+)?\.(svg|png|pdf)',name):raise HTTPException(400,'产物名称无效')
        p=jobs.directory(id)/('' if name=='score.abc' else 'rendered')/name
        if not p.is_file():raise HTTPException(404,'产物文件不存在')
        return FileResponse(p,headers={'Content-Security-Policy':"default-src 'none'; style-src 'unsafe-inline'"})
