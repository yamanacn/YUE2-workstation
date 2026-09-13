"""CPU-only behavioral checks. No model/GPU task is started."""
import copy,json,sqlite3,subprocess,sys,tempfile,threading,time,unittest,uuid
from pathlib import Path
from fastapi.testclient import TestClient
from fastapi import HTTPException
from .common import digest,write_json,validate_artifacts,read_json
from .service import Store,Controller,create_app
from .fake_worker import make_artifacts

def body():
    return {'requestId':str(uuid.uuid4()),'draft':{'title':'CPU TEST','lyrics':'[Verse]\n测试歌词','style':'soft piano','count':1,'seedMode':'fixed','seed':'9223372036854775807',
        'config':{'cot':'off','temperature':1,'topP':.95,'topK':100,'repetitionPenalty':1.2,'maxTokens':200,'odeSteps':8,'cfg':'auto'}}}

class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.data=Path(self.temp.name); self.app=create_app(self.data,schedule=False,test_mode=True); self.client=TestClient(self.app); self.store=self.app.state.store
    def tearDown(self): self.client.close(); self.store.db.close(); self.temp.cleanup()
    def submit(self): return self.store.batch(body())['runs'][0]
    def complete(self):
        r=self.submit(); self.app.state.controller.run_worker(r); self.assertEqual(self.store.get_run(r['id'])['state'],'succeeded'); return self.store.state()['tracks'][0]
    def test_recovered_score_warning_reaches_track(self):
        r=self.submit()
        write_json(self.store.run_dir(r['id'])/'score-recovery.json',
                   {'tailRecovered':True,'warning':'谱曲达到上限，已保留完整部分。'})
        self.app.state.controller.run_worker(r)
        track=self.store.state()['tracks'][0]
        self.assertEqual(track['warning'],'谱曲达到上限，已保留完整部分。')

    def test_vocal_preferences_and_empty_lyrics(self):
        from .prompting import resolve_prompt
        for mode in ('auto','male','female','instrumental'):
            b=body(); b['draft'].update(vocalMode=mode,lyrics='')
            response=self.client.post('/api/v1/batches',json=b)
            self.assertEqual(response.status_code,201,response.text)
            style,lyrics=resolve_prompt(response.json()['runs'][0]['snapshot']['draft'])
            self.assertEqual(lyrics,''); self.assertIn('no vocals',style)
        d=body()['draft']; d.update(vocalMode='female',style='温暖男声 · piano')
        style,lyrics=resolve_prompt(d)
        self.assertNotIn('男声',style); self.assertIn('female vocal',style)
        self.assertTrue(style.startswith('female vocal, '))
        self.assertEqual(lyrics,d['lyrics'])
        d['vocalMode']='male'
        style,lyrics=resolve_prompt(d)
        self.assertTrue(style.startswith('male vocal, ')); self.assertNotIn('female vocal',style)
        d['vocalMode']='auto'
        style,lyrics=resolve_prompt(d)
        self.assertEqual(style,d['style'])
        d['vocalMode']='instrumental'
        d['lyrics']='[Intro]\n钢琴独奏\n[Build]\n加入弦乐与鼓点\n'
        style,lyrics=resolve_prompt(d)
        self.assertEqual(lyrics,d['lyrics']); self.assertIn('instrumental, no vocals',style)
        b=body(); b['draft']['vocalMode']='invalid'
        self.assertEqual(self.client.post('/api/v1/batches',json=b).status_code,400)

    def test_cover_snapshot_persists_strength_and_forces_melody_cot(self):
        audio=self.data/'reference.wav'; audio.write_bytes(b'reference')
        write_json(self.data/'reference-paths.json',{'ref':{'id':'ref','path':str(audio),'name':'reference.wav'}})
        b=body(); b['draft']['config']['cot']='full'; b['draft']['reference']={'id':'ref','range':None,'preserve':'full','strength':'faithful'}
        response=self.client.post('/api/v1/batches',json=b)
        self.assertEqual(response.status_code,201,response.text)
        snapshot=response.json()['runs'][0]['snapshot']
        self.assertEqual(snapshot['draft']['reference']['strength'],'faithful')
        self.assertEqual(snapshot['draft']['config']['cot'],'melody')
        self.assertNotIn('confidenceScores',snapshot['draft']['reference'])

    def test_idempotency_immutable_snapshot_and_conflict(self):
        b=body(); first=self.client.post('/api/v1/batches',json=b); self.assertEqual(first.status_code,201)
        replay=self.client.post('/api/v1/batches',json=b); self.assertEqual(replay.status_code,200); self.assertEqual(first.json()['runs'][0]['id'],replay.json()['runs'][0]['id'])
        b['draft']['lyrics']='changed'; self.assertEqual(self.client.post('/api/v1/batches',json=b).status_code,409)
        self.assertEqual(self.store.state()['runs'][0]['snapshot']['seed'],'9223372036854775807'); self.assertNotEqual(self.store.state()['runs'][0]['snapshot']['draft']['lyrics'],'changed')

    def test_creation_mode_isolates_abc(self):
        score='X:1\nM:4/4\nK:C\nC4|'
        quick=body(); quick['creationMode']='quick'; quick['draft']['abc']=score
        response=self.client.post('/api/v1/batches',json=quick); self.assertEqual(response.status_code,201,response.text)
        self.assertNotIn('abc',response.json()['runs'][0]['snapshot']['draft'])
        advanced_empty=body(); advanced_empty['creationMode']='advanced'; advanced_empty['draft']['abc']='   '
        response=self.client.post('/api/v1/batches',json=advanced_empty); self.assertEqual(response.status_code,201,response.text)
        self.assertNotIn('abc',response.json()['runs'][0]['snapshot']['draft'])
        advanced=body(); advanced['creationMode']='advanced'; advanced['draft']['abc']=score; advanced['draft']['reference']={'id':'not-used'}; advanced['draft']['config']['cot']='full'
        response=self.client.post('/api/v1/batches',json=advanced); self.assertEqual(response.status_code,201,response.text)
        snapshot=response.json()['runs'][0]['snapshot']['draft'];self.assertEqual(snapshot['abc'],score);self.assertNotIn('reference',snapshot)
    def test_validation_seeds_bool_and_range(self):
        for mutate in (lambda b:b['draft'].update(seed='9223372036854775808'),lambda b:b['draft']['config'].update(topK=True),lambda b:b['draft'].update(seedMode='increment',count=2),lambda b:b.update(resolvedSeeds=['4']),lambda b:b['draft']['config'].update(maxTokens=24576)):
            b=body(); mutate(b); self.assertEqual(self.client.post('/api/v1/batches',json=b).status_code,400)
        self.assertEqual(self.store.state()['runs'],[])
    def test_out_of_order_progress_and_terminal_are_ignored(self):
        r=self.submit(); self.store.update(r['id'],'decoding'); self.store.update(r['id'],'planning'); self.assertEqual(self.store.get_run(r['id'])['state'],'decoding')
        self.store.update(r['id'],'failed'); self.store.update(r['id'],'succeeded'); self.assertEqual(self.store.get_run(r['id'])['state'],'failed')
    def test_queued_cancel_and_retry_seed(self):
        r=self.submit(); result=self.client.post(f"/api/v1/runs/{r['id']}/cancel",json={}); self.assertEqual(result.json()['state'],'cancelled')
        result=self.client.post(f"/api/v1/runs/{r['id']}/retry",json={'requestId':'retry-1'}); self.assertEqual(result.status_code,201); self.assertEqual(result.json()['runs'][0]['snapshot']['seed'],r['snapshot']['seed'])
    def test_active_cancel_waits_for_exit(self):
        r=self.submit(); ctl=self.app.state.controller; thread=threading.Thread(target=ctl.run_worker,args=(r,)); thread.start()
        deadline=time.time()+5
        while ctl.process is None and time.time()<deadline: time.sleep(.01)
        run=self.store.cancel(r['id']); self.assertEqual(run['state'],'cancelling')
        self.store.update(r['id'],'decoding'); self.assertEqual(self.store.get_run(r['id'])['state'],'cancelling')
        thread.join(8); self.assertFalse(thread.is_alive()); self.assertIsNone(ctl.process); self.assertEqual(self.store.get_run(r['id'])['state'],'cancelled'); self.assertEqual(self.store.state()['tracks'],[])
    def test_flac_range_head_patch_and_security(self):
        t=self.complete(); url=t['audioUrl']; whole=self.client.get(url); self.assertEqual(whole.headers['content-type'],'audio/flac'); self.assertTrue(whole.content.startswith(b'fLaC'))
        partial=self.client.get(url,headers={'Range':'bytes=4-127'}); self.assertEqual(partial.status_code,206); self.assertEqual(partial.content,whole.content[4:128]); self.assertEqual(len(self.client.head(url).content),0)
        self.assertEqual(self.client.get(url,headers={'Range':'bytes=999999999-'}).status_code,416)
        self.assertEqual(self.client.patch('/api/v1/tracks/'+t['id'],json={'title':'新标题','favorite':True,'removed':True}).status_code,200)
        self.client.patch('/api/v1/tracks/'+t['id'],json={'removed':False}); self.assertFalse(self.store.track(t['id'])['removed']); self.assertEqual(self.store.track(t['id'])['snapshot']['draft']['title'],'CPU TEST')
        self.assertEqual(self.client.patch('/api/v1/queue',json={'paused':True},headers={'Origin':'https://evil.example'}).status_code,403)
        self.assertEqual(self.client.post('/api/v1/batches',content='{}').status_code,415)
        self.assertEqual(self.client.get('/api/v1/tracks/does-not-exist/audio').status_code,404)
        with self.assertRaises(HTTPException): self.store.run_dir('../secret')
    def test_startup_recovery_pauses_queue(self):
        a=self.submit(); b=self.submit(); self.store.update(a['id'],'generating_tokens'); self.store.recover()
        self.assertEqual(self.store.get_run(a['id'])['state'],'interrupted'); self.assertEqual(self.store.get_run(b['id'])['state'],'queued'); self.assertTrue(self.store.state()['queuePaused'])
    def prepare_commit(self,r):
        d=self.store.run_dir(r['id']); d.mkdir(parents=True); make_artifacts(d/'artifacts'); meta=validate_artifacts(d/'artifacts')
        write_json(d/'commit.json',{'runId':r['id'],'snapshotHash':digest(r['snapshot']),'identity':meta['identity'],'metadata':meta}); self.store.update(r['id'],'finalizing'); return d
    def test_recovery_after_rename_before_db_commit(self):
        r=self.submit(); self.prepare_commit(r); self.store.recover(); self.assertEqual(self.store.get_run(r['id'])['state'],'succeeded'); self.assertEqual(len(self.store.state()['tracks']),1)
        self.store.recover(); self.assertEqual(len(self.store.state()['tracks']),1)
    def test_corrupt_commit_has_no_track_and_manifest_rejects_escape(self):
        r=self.submit(); d=self.prepare_commit(r); (d/'artifacts/audio.flac').write_bytes(b'invalid')
        with self.assertRaises(ValueError): self.store.commit(r['id'])
        self.assertEqual(self.store.state()['tracks'],[]); self.store.recover(); self.assertEqual(self.store.get_run(r['id'])['state'],'interrupted')
        manifest=read_json(d/'artifacts/result.json'); manifest['artifacts']['../secret']={'bytes':0,'sha256':'x'}; write_json(d/'artifacts/result.json',manifest)
        with self.assertRaises(ValueError): validate_artifacts(d/'artifacts')
    def test_cancel_commit_race_never_creates_track(self):
        r=self.submit(); self.prepare_commit(r); self.store.cancel(r['id']); self.store.commit(r['id']); self.assertEqual(self.store.get_run(r['id'])['state'],'cancelled'); self.assertEqual(self.store.state()['tracks'],[])
    def test_shutdown_pending_guard(self):
        self.submit(); self.assertEqual(self.client.post('/api/v1/shutdown',json={}).status_code,409)
    def test_official_validation_does_not_import_torch(self):
        source="import sys; from engine.service import validate_draft; from engine.test_service import body; from yue2.storage import verify_result; validate_draft(body()['draft']); assert 'torch' not in sys.modules"
        result=subprocess.run([sys.executable,'-X','utf8','-c',source],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
    def test_atomic_database_failure_rolls_back_success_and_recovers(self):
        r=self.submit(); self.prepare_commit(r)
        self.store.db.execute("CREATE TRIGGER reject_track BEFORE INSERT ON tracks BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END")
        with self.assertRaises(sqlite3.IntegrityError): self.store.commit(r['id'])
        self.assertEqual(self.store.get_run(r['id'])['state'],'finalizing'); self.assertEqual(self.store.state()['tracks'],[])
        self.store.db.execute('DROP TRIGGER reject_track'); self.store.recover(); self.assertEqual(self.store.get_run(r['id'])['state'],'succeeded')
    def test_worker_crash_is_interrupted(self):
        r=self.submit(); ctl=self.app.state.controller; thread=threading.Thread(target=ctl.run_worker,args=(r,)); thread.start()
        deadline=time.time()+5
        while ctl.process is None and time.time()<deadline: time.sleep(.01)
        ctl.process.terminate(); thread.join(8); self.assertFalse(thread.is_alive()); self.assertEqual(self.store.get_run(r['id'])['state'],'interrupted'); self.assertEqual(self.store.state()['tracks'],[])

if __name__=='__main__': unittest.main(verbosity=2)
