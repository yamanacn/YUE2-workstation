"""Score workflow tests: no GPU or changes to the user's source files."""
import threading,unittest,uuid,tempfile
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from .service import create_app
from .common import write_json

class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.data=Path(self.tmp.name)
        self.app=create_app(self.data,schedule=False,test_mode=True);self.client=TestClient(self.app)
        self.jobs=self.app.state.controller.scores
        self.audio=self.data/'original.wav';self.audio.write_bytes(b'original source')
        write_json(self.data/'reference-paths.json',{'ref':{'id':'ref','path':str(self.audio),'name':'original.wav'}})
    def tearDown(self):
        self.client.close();self.app.state.store.db.close();self.tmp.cleanup()
    def body(self):return {'requestId':str(uuid.uuid4()),'source':{'id':'ref','range':None},'mode':'full'}
    def test_idempotency_validation_and_no_source_copy(self):
        b=self.body();a=self.client.post('/api/v1/scores',json=b);self.assertEqual(a.status_code,200,a.text)
        self.assertEqual(self.client.post('/api/v1/scores',json=b).json()['id'],a.json()['id'])
        b['mode']='melody';self.assertEqual(self.client.post('/api/v1/scores',json=b).status_code,409)
        for invalid in (None,123,'../bad'):
            b=self.body();b['requestId']=invalid;self.assertEqual(self.client.post('/api/v1/scores',json=b).status_code,400)
        self.assertEqual(self.audio.read_bytes(),b'original source');self.assertFalse((self.data/'scores').exists())
    def test_cancel_and_recovery_keep_abc(self):
        r=self.jobs.submit(self.body());self.jobs.cancel(r['id']);self.assertEqual(self.jobs.get(r['id'])['state'],'cancelled')
        r=self.jobs.submit(self.body());self.jobs.update(r['id'],state='rendering',hasAbc=True);self.jobs.recover()
        self.assertEqual(self.jobs.get(r['id'])['state'],'interrupted');self.assertTrue(self.jobs.get(r['id'])['hasAbc'])
        self.assertEqual(self.jobs.rerender(r['id'])['state'],'queued')
    def test_render_failure_preserves_abc_and_allows_retry(self):
        r=self.jobs.submit(self.body())
        def transcribe(source,directory,data,check,progress):
            write_json(directory/'reference-score.json',{'cache':str(directory),'reused':False})
            return 'X:1\nM:4/4\nK:C\nCDEF|'
        with patch('engine.score_jobs.transcribe_reference',side_effect=transcribe),patch('engine.score_jobs.subprocess.Popen',side_effect=RuntimeError('renderer unavailable')):
            self.jobs.run(r,threading.Event())
        item=self.jobs.get(r['id']);self.assertEqual(item['state'],'failed');self.assertTrue(item['hasAbc'])
        self.assertIsNone(self.jobs.current)
        self.assertEqual(self.client.get('/api/v1/scores/'+r['id']+'/abc').status_code,200)
        self.assertEqual(self.client.post('/api/v1/scores/'+r['id']+'/render',json={}).status_code,200)
    def test_cancel_before_work_never_transcribes(self):
        r=self.jobs.submit(self.body());self.jobs.cancel(r['id'])
        with patch('engine.score_jobs.transcribe_reference') as transcribe:
            self.jobs.run(r,threading.Event());transcribe.assert_not_called()
        self.assertEqual(self.jobs.get(r['id'])['state'],'cancelled')
    def test_cancel_cannot_be_overwritten_by_a_late_stage(self):
        r=self.jobs.submit(self.body());self.jobs.update(r['id'],state='analyzing');self.jobs.cancel(r['id'])
        with self.assertRaises(InterruptedError):self.jobs.update(r['id'],state='rendering')
        self.jobs.update(r['id'],stage='late progress')
        self.assertEqual(self.jobs.get(r['id'])['stage'],'正在取消')
    def test_shutdown_rejects_pending_score(self):
        self.jobs.submit(self.body())
        self.assertEqual(self.client.post('/api/v1/shutdown',json={}).status_code,409)

if __name__=='__main__':unittest.main()
