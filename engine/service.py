"""Loopback API, SQLite persistence and serial subprocess scheduling."""
from __future__ import annotations
import argparse,copy,hashlib,importlib.util,json,math,os,re,secrets,shutil,sqlite3,subprocess,sys,threading,time,uuid
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import FastAPI,Request,HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse,JSONResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from .common import ROOT,PROFILE,TERMINAL,ORDER,FileLock,now,ms,read_json,write_json,canonical,digest,validate_artifacts,expected_weights
from .runtime_paths import main_python,runtime_environment

def failure(detail,code='invalid_request',status=400): raise HTTPException(status,detail={'detail':detail,'code':code})
def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,179}',value): failure('无效的请求标识')
    return value
def validate_draft(d):
    from yue2.protocol import Sampling,SongRequest,GenerationConfig
    if not isinstance(d,dict): failure('draft 必须为对象')
    d=copy.deepcopy(d)
    if isinstance(d.get('abc'),str) and not d['abc'].strip(): d.pop('abc',None)
    try:
        for key in ('title','style','lyrics','seed'):
            if not isinstance(d[key],str): raise ValueError(key+' 必须是字符串')
        if not d['style'].strip(): raise ValueError('风格不能为空')
        if d.get('abc') is not None and (not isinstance(d['abc'],str) or len(d['abc'])>120000 or not d['abc'].strip()): raise ValueError('ABC 乐谱格式无效')
        if d.get('abc') and d.get('config',{}).get('cot')=='off': raise ValueError('输入 ABC 时不能关闭乐谱规划')
        from .prompting import resolve_prompt
        style,lyrics=resolve_prompt(d)
        if len(d['title'])>240 or len(d['lyrics'])+len(d['style'])>60000: raise ValueError('输入正文过长')
        if type(d['count']) is not int or d['count'] not in (1,2,4): raise ValueError('count 必须为 1、2 或 4')
        if d['seedMode'] not in ('random','fixed','increment'): raise ValueError('seedMode 无效')
        c=d['config']
        from .performance import settings
        settings(c)
        for key in ('temperature','topP','topK','repetitionPenalty','maxTokens','odeSteps'):
            if type(c[key]) not in (float,int) or not math.isfinite(c[key]): raise ValueError('数值无效: '+key)
        if c['cfg']!='auto' and (type(c['cfg']) not in (float,int) or not math.isfinite(c['cfg'])): raise ValueError('cfg 无效')
        if c['maxTokens']<200 or c['maxTokens']>=24576: raise ValueError('maxTokens 必须在 200 到 24575 之间')
        Sampling(temperature=c['temperature'],top_p=c['topP'],top_k=c['topK'],repetition_penalty=c['repetitionPenalty'],max_tokens=c['maxTokens'])
        GenerationConfig(ode_steps=c['odeSteps'])
        SongRequest(style,lyrics,cot=c['cot'],cfg_scale=None if c['cfg']=='auto' else c['cfg'])
        if d['seedMode']!='random':
            seed_value(d['seed'])
            if d['seedMode']=='increment': seed_value(str(int(d['seed'])+d['count']-1))
    except (KeyError,ValueError,TypeError) as exc: failure(str(exc))
    return copy.deepcopy(d)
def seed_value(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9]{1,19}',value) or not 0<=int(value)<2**63: failure('seed 超出非负 63 位十进制整数范围')
    return value

class Store:
    def __init__(self,data):
        self.data=Path(data).resolve(); self.data.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock(); self.db=sqlite3.connect(self.data/'studio.sqlite3',check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS batches(request_id TEXT PRIMARY KEY,body_hash TEXT NOT NULL,batch_id TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tracks(id TEXT PRIMARY KEY,run_id TEXT UNIQUE NOT NULL,record TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,type TEXT NOT NULL,at TEXT NOT NULL,data TEXT NOT NULL);
        INSERT OR IGNORE INTO meta VALUES('paused','false');'''); self.db.commit()
    def event(self,kind,value): self.db.execute('INSERT INTO events(type,at,data) VALUES(?,?,?)',(kind,now(),canonical(value)))
    def save_run(self,r):
        self.db.execute('INSERT OR REPLACE INTO runs VALUES(?,?)',(r['id'],canonical(r))); self.event('run.updated',r)
    def get_run(self,id):
        with self.lock:
            row=self.db.execute('SELECT record FROM runs WHERE id=?',(id,)).fetchone()
            if not row: failure('任务不存在','not_found',404)
            return json.loads(row[0])
    def run_dir(self,id):
        identifier(id); path=(self.data/'runs'/id).resolve()
        if not path.is_relative_to((self.data/'runs').resolve()): failure('无效任务目录')
        return path
    def state(self):
        with self.lock:
            runs=[json.loads(x[0]) for x in self.db.execute('SELECT record FROM runs')]
            tracks=[json.loads(x[0]) for x in self.db.execute('SELECT record FROM tracks')]
            for t in tracks: t['missing']=not (self.run_dir(t['runId'])/'artifacts/audio.flac').is_file()
            return {'runs':sorted(runs,key=lambda r:r['created'],reverse=True),'tracks':sorted(tracks,key=lambda t:t['created'],reverse=True),
                'queuePaused':json.loads(self.db.execute("SELECT value FROM meta WHERE key='paused'").fetchone()[0]),'eventCursor':self.db.execute('SELECT coalesce(max(seq),0) FROM events').fetchone()[0]}
    def batch_result(self,request_id,replayed=True):
        with self.lock:
            row=self.db.execute('SELECT batch_id FROM batches WHERE request_id=?',(request_id,)).fetchone()
            if not row: failure('此请求尚未受理','not_found',404)
            return {'requestId':request_id,'batchId':row[0],'runs':[r for r in self.state()['runs'] if r['batchId']==row[0]],'replayed':replayed}
    def batch(self,body):
        body=copy.deepcopy(body)
        creation_mode=body.get('creationMode')
        if creation_mode not in (None,'quick','advanced'): failure('creationMode 无效')
        if isinstance(body.get('draft'),dict):
            draft_abc=body['draft'].get('abc')
            if creation_mode=='quick' or (isinstance(draft_abc,str) and not draft_abc.strip()): body['draft'].pop('abc',None)
            if creation_mode=='advanced': body['draft'].pop('reference',None)
        request_id=identifier(body.get('requestId'))
        try: body_hash=digest(body)
        except (ValueError,TypeError): failure('请求包含无效数值或类型')
        with self.lock,self.db:
            old=self.db.execute('SELECT body_hash FROM batches WHERE request_id=?',(request_id,)).fetchone()
            if old:
                if old[0]!=body_hash: failure('同一 requestId 已用于不同请求','idempotency_conflict',409)
                return self.batch_result(request_id)
            d=validate_draft(body.get('draft')); seeds=body.get('resolvedSeeds')
            if d.get('reference'):
                from .cover import resolve_reference
                try: d['reference']=resolve_reference(d['reference'],self.data)
                except (ValueError,OSError,KeyError) as exc: failure(str(exc),'reference_unavailable',422)
                # A cover always consumes the extracted melody prefix.  The
                # preserve toggle controls transcription detail, while COT
                # remains melody so the new arrangement can follow the user
                # style around that prefix.
                d['config']['cot']='melody'
            if seeds is not None:
                if not isinstance(seeds,list) or len(seeds)!=d['count']: failure('resolvedSeeds 数量须等于 count')
                seeds=[seed_value(s) for s in seeds]
                if d['seedMode']!='random' and seeds != [str(int(d['seed'])+(i if d['seedMode']=='increment' else 0)) for i in range(d['count'])]: failure('resolvedSeeds 与固定种子设置不一致')
            else: seeds=[str(secrets.randbelow(2**63)) if d['seedMode']=='random' else str(int(d['seed'])+(i if d['seedMode']=='increment' else 0)) for i in range(d['count'])]
            try: identities=expected_weights()
            except (OSError,ValueError,KeyError): failure('模型身份文件尚未就绪','models_unavailable',503)
            batch_id=str(uuid.uuid4()); self.db.execute('INSERT INTO batches VALUES(?,?,?)',(request_id,body_hash,batch_id))
            from .performance import settings
            runtime_settings=settings(d['config'])
            d['config']['performance']=runtime_settings
            profile={**PROFILE,**runtime_settings,'memoryBudgetGiB':runtime_settings['memoryBudgetGiB'] or 'auto'}
            for i,seed in enumerate(seeds):
                r={'id':str(uuid.uuid4()),'batchId':batch_id,'snapshot':{'draft':copy.deepcopy(d),'seed':seed,'submittedAt':now(),'runtime':'local-yue2','requestId':request_id,'profile':profile,'modelIdentities':identities},
                   'state':'queued','stageStarted':ms(),'created':ms()+i,'elapsed':0,'progress':{'phase':'queued','detail':'等待调度','completed':None,'total':None,'unit':None,'elapsedSeconds':0}}
                for key in ('parentRunId','parentTrackId','attemptOf'):
                    if body.get(key): r[key]=identifier(body[key])
                if body.get('parentTrackId') or body.get('parentRunId'): r['parentId']=body.get('parentTrackId') or body.get('parentRunId')
                self.save_run(r)
            return self.batch_result(request_id,False)
    def update(self,id,state,progress=None,error=None):
        with self.lock,self.db:
            r=self.get_run(id); old=r['state']
            if old in TERMINAL or old=='cancelling' and state not in TERMINAL|{'cancelling'}: return r
            if state not in TERMINAL|{'cancelling'} and (state not in ORDER or ORDER.index(state)<ORDER.index(old)): return r
            if old!=state: r['stageStarted']=ms()
            r['state']=state; r['elapsed']=max(0,(ms()-r.get('started',r['created']))/1000)
            if state=='checking' and 'started' not in r: r['started']=ms()
            if progress: r['progress']=progress
            if error: r['error']=error
            self.save_run(r); return r
    def cancel(self,id):
        with self.lock:
            r=self.get_run(id)
            if r['state'] in TERMINAL: return r
            directory=self.run_dir(id); directory.mkdir(parents=True,exist_ok=True); (directory/'cancel.request').touch()
            return self.update(id,'cancelled' if r['state']=='queued' else 'cancelling')
    def pause(self,paused):
        if type(paused) is not bool: failure('paused 必须是布尔值')
        with self.lock,self.db:
            self.db.execute("UPDATE meta SET value=? WHERE key='paused'",(canonical(paused),)); self.event('queue.updated',{'queuePaused':paused})
        return {'paused':paused,'queuePaused':paused}
    def commit(self,id,metadata=None):
        with self.lock:
            r=self.get_run(id)
            if r['state'] in TERMINAL: return r
            directory=self.run_dir(id); intent=read_json(directory/'commit.json')
            if intent['runId']!=id or intent['snapshotHash']!=digest(r['snapshot']): raise ValueError('Commit snapshot identity mismatch')
            metadata=validate_artifacts(directory/'artifacts',intent['identity'])
            if (directory/'cancel.request').exists() or r['state']=='cancelling': return self.update(id,'cancelled')
            # Verified files + succeeded + track become visible together in one transaction.
            with self.db:
                r['state']='succeeded'; r['stageStarted']=ms(); r['elapsed']=max(0,(ms()-r.get('started',r['created']))/1000)
                r['progress']={'phase':'succeeded','detail':'音频已验证并保存','completed':None,'total':None,'unit':None,'elapsedSeconds':r['elapsed']}
                d=r['snapshot']['draft']; tid=str(uuid.uuid4())
                t={'id':tid,'runId':id,'title':d['title'].strip() or '未命名作品','version':'V01','style':d['style'],'lyrics':d['lyrics'],'artwork':'/assets/opal-glass.webp',
                    'duration':metadata['duration'],'created':now(),'favorite':False,'removed':False,'snapshot':r['snapshot'],'audioUrl':f'/api/v1/tracks/{tid}/audio','audioKind':'generated',
                    'audioFormat':'flac','sampleRate':metadata['sampleRate'],'channels':metadata['channels'],'subtype':metadata['subtype'],'missing':False,'sourceTitle':'本机 YuE2 生成'}
                if any(metadata['truncated'].values()): t['warning']='生成达到 token 预算上限，音频可能未自然结束。'
                recovery_path=directory/'score-recovery.json'
                if recovery_path.exists():
                    warning=read_json(recovery_path).get('warning')
                    if warning: t['warning']=' '.join(filter(None,[warning,t.get('warning')]))
                self.save_run(r); self.db.execute('INSERT INTO tracks VALUES(?,?,?)',(tid,id,canonical(t))); self.event('track.created',t)
            return r
    def recover(self):
        pending=False
        for r in self.state()['runs']:
            if r['state'] in TERMINAL: continue
            pending=True; directory=self.run_dir(r['id'])
            if r['state']=='queued': continue
            # Signal an orphan worker; its global file lock prevents overlap until exit.
            directory.mkdir(parents=True,exist_ok=True)
            if (directory/'commit.json').exists() and (directory/'artifacts').exists() and r['state']!='cancelling':
                try: self.commit(r['id']); continue
                except Exception: pass
            (directory/'cancel.request').touch(); self.update(r['id'],'interrupted',error='服务重启，上次任务未确认完成；后续队列已暂停。')
        if pending: self.pause(True)
    def track(self,id):
        with self.lock:
            row=self.db.execute('SELECT record FROM tracks WHERE id=?',(id,)).fetchone()
            if not row: failure('作品不存在','not_found',404)
            return json.loads(row[0])
    def patch_track(self,id,patch):
        if not patch or set(patch)-{'title','favorite','removed'}: failure('只允许修改标题、收藏和移除状态')
        if 'title' in patch and (not isinstance(patch['title'],str) or not patch['title'].strip() or len(patch['title'])>240): failure('标题不能为空或过长')
        if any(type(patch[k]) is not bool for k in ('favorite','removed') if k in patch): failure('作品状态必须是布尔值')
        with self.lock,self.db:
            t=self.track(id); t.update(patch); self.db.execute('UPDATE tracks SET record=? WHERE id=?',(canonical(t),id)); self.event('track.updated',t); return t
    def delete_track(self,id):
        with self.lock,self.db:
            t=self.track(id)
            if self.get_run(t['runId']).get('state') in {'queued','planning','generating_tokens','synthesizing','decoding','finalizing'}: failure('正在生成的作品不能删除','run_active',409)
            self.db.execute('DELETE FROM tracks WHERE id=?',(id,)); self.event('track.deleted',{'id':id})
            shutil.rmtree(self.run_dir(t['runId']),ignore_errors=True)
            return {'id':id,'deleted':True}

class Controller:
    def __init__(self,store,test_mode=False):
        self.store=store; self.test_mode=test_mode; self.stop=threading.Event(); self.thread=None; self.process=None; self.current=None; self.loaded=False; self.health_cache={}; self.last_health=0
        from .score_jobs import ScoreJobs
        self.scores=ScoreJobs(store)
    def health(self):
        if self.test_mode:
            return {'ok':True,'service':'yue2-studio','apiVersion':1,'testMode':True,'status':'busy' if self.process else 'ready','dependenciesReady':True,'modelsReady':False,'modelLoaded':False,'workerActive':bool(self.process),'profile':PROFILE,'device':None}
        if time.monotonic()-self.last_health<2:
            if self.process: return {**self.health_cache,'status':'busy','workerActive':True,'modelLoaded':self.loaded,'reason':None}
            return self.health_cache
        dependencies=all(importlib.util.find_spec(x) is not None for x in ('torch','yue2','soundfile'))
        models=all((ROOT/'models'/n/'model.safetensors').is_file() and (ROOT/'models'/n/'config.json').is_file() for n in ('YuE2-3B','YuE2-Vae'))
        # Do not shell out to nvidia-smi from the control plane. GPU details
        # are established by the internal Torch worker when a job starts.
        device=None; reason=None
        if self.process or self.scores.current: status='busy'
        elif not dependencies or not models: status='unavailable'; reason=reason or '依赖或模型文件不齐备'
        elif not device: status='ready'
        else: status='ready'
        orphan=False
        if self.process is None and not self.scores.current:
            probe=FileLock(self.store.data/'gpu-worker.lock'); orphan=not probe.acquire(); probe.close()
            if orphan: status='resource_wait'; reason='等待上次工作进程退出并释放资源'
        self.health_cache={'ok':True,'service':'yue2-studio','apiVersion':1,'projectRoot':str(ROOT),'pid':os.getpid(),'status':status,'dependenciesReady':dependencies,'modelsReady':models,'workerActive':bool(self.process) or bool(self.scores.current) or orphan,'modelLoaded':None if orphan else self.loaded,'profile':PROFILE,'device':device,'reason':reason}
        self.last_health=time.monotonic(); return self.health_cache
    def start(self):
        self.instance=FileLock(self.store.data/'service.lock')
        if not self.instance.acquire(): raise RuntimeError('此数据目录已有控制服务')
        self.store.recover(); self.scores.recover(); self.thread=threading.Thread(target=self.loop,daemon=True); self.thread.start()
    def close(self):
        self.stop.set()
        if self.current: self.store.cancel(self.current)
        if self.scores.current:self.scores.cancel(self.scores.current)
        if self.thread: self.thread.join(timeout=25)
        if self.process and self.process.poll() is None: self.process.terminate(); self.process.wait(timeout=10)
        if self.thread: self.thread.join(timeout=5)
        self.instance.close()
    def loop(self):
        while not self.stop.is_set():
            (self.store.data/'service.heartbeat').touch()
            state=self.store.state(); queued=sorted((r for r in state['runs'] if r['state']=='queued'),key=lambda r:r['created'])
            score_queue=sorted((r for r in self.scores.all() if r['state']=='queued'),key=lambda r:r['created'])
            if not state['queuePaused'] and score_queue and (not queued or score_queue[0]['created']<queued[0]['created']):
                self.scores.run(score_queue[0],self.stop)
            elif not state['queuePaused'] and queued and self.health()['status']=='ready':
                probe=FileLock(self.store.data/'gpu-worker.lock')
                if probe.acquire():
                    probe.close(); self.run_worker(queued[0])
            self.stop.wait(.5)
    def run_worker(self,run):
        id=run['id']; directory=self.store.run_dir(id); directory.mkdir(parents=True,exist_ok=True)
        with self.store.lock:
            if self.store.get_run(id)['state']!='queued': return
            write_json(directory/'snapshot.json',run['snapshot']); self.store.update(id,'checking')
        self.current=id; outcome=None; self.loaded=False
        try:
            env=runtime_environment(); env['HF_HUB_OFFLINE']='1'
            if self.test_mode: env['YUE2_TEST_WORKER']='1'
            with (directory/'worker.log').open('a',encoding='utf-8') as log:
                module='engine.fake_worker' if self.test_mode else 'engine.worker'
                self.process=subprocess.Popen([str(main_python()),'-X','utf8','-u','-m',module,str(directory),str(self.store.data)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                write_json(directory/'worker-process.json',{'pid':self.process.pid,'startedAt':now()})
                def heartbeat():
                    while self.process is not None and self.process.poll() is None:
                        if self.stop.is_set(): (directory/'cancel.request').touch()
                        (self.store.data/'service.heartbeat').touch(); time.sleep(1)
                hb=threading.Thread(target=heartbeat,daemon=True); hb.start()
                for line in self.process.stdout:
                    try: e=json.loads(line)
                    except (ValueError,TypeError): log.write('Rejected non-protocol stdout: '+line); log.flush(); continue
                    if e.get('kind')=='progress':
                        self.loaded=bool(e.get('modelLoaded')); self.store.update(id,e['state'],progress=e['progress'])
                    elif e.get('kind')=='outcome': outcome=e
                code=self.process.wait(); hb.join(timeout=2)
                # Only after process exit can terminal cancellation/success be confirmed.
                if outcome and outcome['status']=='succeeded' and code==0: self.store.commit(id)
                elif outcome and outcome['status']=='cancelled' and code==0: self.store.update(id,'cancelled')
                elif outcome: self.store.update(id,'failed',error=outcome.get('error','推理失败'))
                else: self.store.update(id,'interrupted',error=f'工作进程意外退出 ({code})')
        except Exception as exc:
            if self.process and self.process.poll() is None: self.process.terminate(); self.process.wait(timeout=10)
            self.store.update(id,'failed',error=f'{type(exc).__name__}: {exc}')
        finally:
            if self.process and self.process.stdout: self.process.stdout.close()
            self.process=None; self.current=None; self.loaded=False; self.last_health=0

def create_app(data=ROOT/'data',schedule=True,test_mode=False):
    if test_mode and Path(data).resolve()==(ROOT/'data').resolve(): raise ValueError('Test workers require an isolated data directory')
    store=Store(data); ctl=Controller(store,test_mode)
    @asynccontextmanager
    async def lifespan(app):
        if schedule: ctl.start()
        yield
        if schedule: ctl.close()
    app=FastAPI(lifespan=lifespan); app.state.store=store; app.state.controller=ctl
    @app.exception_handler(HTTPException)
    async def errors(request,exc): return JSONResponse(exc.detail if isinstance(exc.detail,dict) else {'detail':str(exc.detail)},status_code=exc.status_code)
    @app.exception_handler(RequestValidationError)
    async def invalid_json(request,exc): return JSONResponse({'detail':'请求 JSON 的结构或字段格式无效','code':'invalid_request'},status_code=422)
    @app.middleware('http')
    async def local_only(request,call_next):
        if request.url.path.startswith('/api/') and request.method in ('POST','PATCH','PUT','DELETE'):
            origin=request.headers.get('origin')
            if origin:
                parsed=urlsplit(origin)
                allowed_ports={4174,5173,8767,request.url.port}
                if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.port not in allowed_ports: return JSONResponse({'detail':'不允许的请求来源','code':'origin_rejected'},403)
            if getattr(app.state,'shutting_down',False): return JSONResponse({'detail':'服务正在关闭','code':'shutting_down'},503)
            if request.headers.get('content-type','').split(';')[0]!='application/json': return JSONResponse({'detail':'写入请求须使用 application/json'},415)
        response=await call_next(request)
        if request.url.path.startswith('/api/'): response.headers['Cache-Control']='no-store'
        response.headers['X-Content-Type-Options']='nosniff'; return response
    from .reference_files import install_reference_routes
    install_reference_routes(app, data)
    from .score_jobs import install_score_routes
    install_score_routes(app,ctl.scores)
    from .chat import install_chat_routes
    install_chat_routes(app, data)
    @app.get('/api/v1/health')
    def health(): return ctl.health()
    @app.get('/api/v1/state')
    def state(): return store.state()
    @app.post('/api/v1/shutdown')
    def shutdown():
        with store.lock:
            if ctl.process or any(r['state'] in ('queued','analyzing','rendering','cancelling') for r in ctl.scores.all()) or any(r['state'] not in TERMINAL for r in store.state()['runs']): failure('仍有排队或运行任务，请完成或取消后停止服务','tasks_pending',409)
            callback=getattr(app.state,'shutdown_callback',None)
            if not callback: failure('此启动方式未启用安全关闭','shutdown_unavailable',503)
            app.state.shutting_down=True; ctl.stop.set(); callback()
        return JSONResponse({'status':'shutting_down'},status_code=202)
    @app.post('/api/v1/batches')
    def batches(body:dict):
        result=store.batch(body); return JSONResponse(result,status_code=200 if result['replayed'] else 201)
    @app.get('/api/v1/batches/by-request/{id}')
    def by_request(id:str): return store.batch_result(id)
    @app.post('/api/v1/runs/{id}/cancel')
    def cancel(id:str):
        run=store.cancel(id); return JSONResponse(run,status_code=202 if run['state']=='cancelling' else 200)
    @app.post('/api/v1/runs/{id}/retry')
    def retry(id:str,body:dict):
        run=store.get_run(id)
        if run['state'] not in TERMINAL: failure('活动任务不能重试','run_active',409)
        draft=copy.deepcopy(run['snapshot']['draft']); draft.update(count=1,seedMode='fixed',seed=run['snapshot']['seed'])
        result=store.batch({'requestId':body.get('requestId'),'draft':draft,'resolvedSeeds':[run['snapshot']['seed']],'attemptOf':id})
        return JSONResponse(result,status_code=200 if result['replayed'] else 201)
    @app.patch('/api/v1/queue')
    def queue(body:dict): return store.pause(body.get('paused'))
    @app.patch('/api/v1/tracks/{id}')
    def track(id:str,body:dict): return store.patch_track(id,body)
    @app.delete('/api/v1/tracks/{id}')
    def delete_track(id:str): return store.delete_track(id)
    @app.api_route('/api/v1/tracks/{id}/audio',methods=['GET','HEAD'])
    def audio(id:str,request:Request):
        t=store.track(id); path=store.run_dir(t['runId'])/'artifacts/audio.flac'
        if not path.is_file() or not path.resolve().is_relative_to(store.data/'runs'): failure('音频文件不存在','audio_missing',404)
        return FileResponse(path,media_type='audio/flac',headers={'Content-Disposition':'inline','Accept-Ranges':'bytes'})
    @app.get('/api/v1/runs/{id}/artifacts')
    def artifacts(id:str):
        store.get_run(id); directory=store.run_dir(id); path=directory/'artifacts/result.json'
        if not path.is_file(): return {'runId':id,'artifacts':[]}
        response={'runId':id,'artifacts':[{'name':name,**entry} for name,entry in read_json(path)['artifacts'].items()]}
        audit=directory/'reference-audit.json'
        if audit.is_file(): response['referenceAudit']=read_json(audit)
        attention=directory/'attention-audit.json'
        if attention.is_file(): response['attentionAudit']=read_json(attention)
        return response
    @app.get('/api/v1/runs/{id}/logs')
    def logs(id:str):
        store.get_run(id); path=store.run_dir(id)/'worker.log'
        if not path.exists(): return {'runId':id,'log':'','truncated':False}
        with path.open('rb') as stream:
            size=path.stat().st_size; stream.seek(max(0,size-131072)); value=stream.read().decode('utf-8',errors='replace')
        return {'runId':id,'log':value,'truncated':size>131072}
    if (ROOT/'studio/dist/client').is_dir(): app.mount('/',StaticFiles(directory=ROOT/'studio/dist/client',html=True),name='frontend')
    return app

def import_artifacts(source,title,data):
    source=Path(source).resolve(); meta=validate_artifacts(source)
    request=read_json(source/'request.json'); config=read_json(source/'config.json'); gen=config['generation']; sampling=gen['semantic']
    draft={'title':title,'style':request['style'],'lyrics':request['lyrics'],'count':1,'seedMode':'fixed','seed':str(request['seed']),
       'config':{'cot':request['cot'],'cfg':'auto' if request['cfg_scale'] is None else request['cfg_scale'],'temperature':sampling['temperature'],'topP':sampling['top_p'],'topK':sampling['top_k'],'repetitionPenalty':sampling['repetition_penalty'],'maxTokens':sampling['max_tokens'],'odeSteps':gen['ode_steps']}}
    store=Store(data); store.pause(True)
    batch=store.batch({'requestId':'import-'+meta['identity'],'draft':draft}); run=batch['runs'][0]
    if run['state']=='succeeded': return batch
    directory=store.run_dir(run['id']); directory.mkdir(parents=True,exist_ok=True)
    staging=directory/'artifacts.partial'; shutil.copytree(source,staging)
    checked=validate_artifacts(staging,meta['identity'])
    write_json(directory/'snapshot.json',run['snapshot']); write_json(directory/'import-source.json',{'sourceIdentity':meta['identity'],'sourceRequestId':request['id'],'importedAt':now()})
    write_json(directory/'commit.json',{'runId':run['id'],'snapshotHash':digest(run['snapshot']),'identity':meta['identity'],'metadata':checked})
    os.rename(staging,directory/'artifacts'); store.update(run['id'],'finalizing'); store.commit(run['id'])
    return store.batch_result(batch['requestId'])

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--port',type=int,default=8767); parser.add_argument('--data-dir',type=Path,default=ROOT/'data')
    sub=parser.add_subparsers(dest='command'); imp=sub.add_parser('import-artifacts'); imp.add_argument('source',type=Path); imp.add_argument('--title',default='平常的一天 · 本机验证')
    args=parser.parse_args()
    if args.command: print(canonical(import_artifacts(args.source,args.title,args.data_dir))); return
    import uvicorn
    app=create_app(args.data_dir)
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,access_log=False))
    app.state.shutdown_callback=lambda: setattr(server,'should_exit',True)
    server.run()
if __name__=='__main__': main()
