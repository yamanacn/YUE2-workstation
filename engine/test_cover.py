import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from engine.cover import resolve_reference,transcribe_reference,sha,SHEET_REV,MERT_REV
from engine.worker import reference_audit
from engine.common import write_json,digest
class CoverTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.data=Path(self.temp.name);self.audio=self.data/'original.wav';self.audio.write_bytes(b'original');self.run=self.data/'run';self.run.mkdir();write_json(self.data/'reference-paths.json',{'ref':{'id':'ref','path':str(self.audio),'name':'original.wav'}})
 def tearDown(self):self.temp.cleanup()
 def source(self):return resolve_reference({'id':'ref','path':'ignored','range':[0,1],'preserve':'melody'},self.data)
 def test_registry_is_authority(self):self.assertEqual(self.source()['path'],str(self.audio))
 def test_client_confidence_is_not_persisted_or_used(self):
  source=resolve_reference({'id':'ref','range':None,'preserve':'melody','strength':'faithful','confidenceScores':{'m0_n0':0}},self.data)
  self.assertNotIn('confidenceScores',source)
  self.assertEqual(source['sha256'],sha(self.audio))
 def test_reference_audit_records_source_audio_sha_directly(self):
  source=self.source();audit=reference_audit(source,'X:1\nK:C\nC4|','X:1\nK:C\nC4|',{'strength':'balanced','unchanged':True,'degraded':True})
  self.assertEqual(audit['sourceAudioSha256'],sha(self.audio))
  self.assertEqual(audit['rawSha256'],audit['processedSha256'])
 def test_invalid_range(self):
  for region in ([1,0],[0,float('nan')],[False,2],[-1,2],[0,.01]):
   with self.assertRaises(ValueError):resolve_reference({'id':'ref','range':region},self.data)
 def test_missing(self):
  self.audio.unlink()
  with self.assertRaises(ValueError):self.source()
 def test_changed_source_is_rejected(self):
  source=self.source();self.audio.write_bytes(b'changed')
  with self.assertRaises(ValueError):transcribe_reference(source,self.run,self.data,lambda:None,lambda *_:None)
 def test_valid_cache_skips_model(self):
  source=self.source();identity={'audio':source['sha256'],'range':source['range'],'preserve':'melody','sheet':SHEET_REV,'mert':MERT_REV,'adapter':1};cache=self.data/'transcriptions'/digest(identity);cache.mkdir(parents=True);score=cache/'score.abc';score.write_text('X:1\nK:C\nC4|');write_json(cache/'manifest.json',{'scoreSha256':sha(score)})
  with patch('engine.cover.subprocess.Popen',side_effect=AssertionError('Must use cache')):
   self.assertIn('C4',transcribe_reference(source,self.run,self.data,lambda:None,lambda *_:None))
if __name__=='__main__':unittest.main()
