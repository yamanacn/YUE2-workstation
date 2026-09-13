import tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from engine.reference_files import install_reference_routes
class ReferenceTests(unittest.TestCase):
 def test_path_only_and_missing(self):
  with tempfile.TemporaryDirectory() as root:
   data=Path(root)/'data';source=Path(root)/'song.wav';source.write_bytes(b'RIFFtest')
   app=FastAPI();install_reference_routes(app,data);c=TestClient(app)
   with patch('engine.reference_files._native_pick',return_value=(True,str(source))): item=c.post('/api/v1/references/pick',json={'picker':'native'}).json()
   self.assertEqual(item['path'],str(source.resolve()));self.assertEqual(len(list(data.iterdir())),1)
   self.assertEqual(c.get('/api/v1/references/'+item['id']+'/audio').content,b'RIFFtest')
   source.unlink();self.assertEqual(c.get('/api/v1/references/'+item['id']).status_code,404)
   self.assertEqual(c.get('/api/v1/references/unknown/audio').status_code,404)
 def test_cancel(self):
  with tempfile.TemporaryDirectory() as root:
   app=FastAPI();install_reference_routes(app,root);c=TestClient(app)
   with patch('engine.reference_files._native_pick',return_value=(True,'')): self.assertIsNone(c.post('/api/v1/references/pick',json={'picker':'native'}).json())
   self.assertEqual(list(Path(root).iterdir()),[])
 def test_tk_fallback(self):
  with tempfile.TemporaryDirectory() as root:
   data=Path(root)/'data';source=Path(root)/'song.wav';source.write_bytes(b'RIFFtest')
   app=FastAPI();install_reference_routes(app,data);c=TestClient(app)
   with patch('engine.reference_files._native_pick',return_value=(False,'')),patch('engine.reference_files._tk_pick',return_value=(True,str(source))):
    item=c.post('/api/v1/references/pick',json={'picker':'native'}).json()
   self.assertEqual(item['path'],str(source.resolve()))
 def test_picker_failure_exposes_diagnostic_detail(self):
  with tempfile.TemporaryDirectory() as root:
   app=FastAPI();install_reference_routes(app,root);c=TestClient(app)
   with patch('engine.reference_files._native_pick',return_value=(False,'')),patch('engine.reference_files._tk_pick',return_value=(False,'')):
    response=c.post('/api/v1/references/pick',json={'picker':'native'})
   self.assertEqual(response.status_code,503,response.text)
   self.assertIn('本地文件选择器无法打开',response.json()['detail'])
 def test_advanced_transcription_endpoint(self):
  with tempfile.TemporaryDirectory() as root:
   data=Path(root)/'data';source=Path(root)/'song.wav';source.write_bytes(b'RIFFtest')
   app=FastAPI();install_reference_routes(app,data);c=TestClient(app)
   with patch('engine.reference_files._native_pick',return_value=(True,str(source))): item=c.post('/api/v1/references/pick',json={'picker':'native'}).json()
   with patch('engine.cover.transcribe_reference',return_value='raw abc') as transcribe, patch('engine.abc_processor.ABCReferenceProcessor.process',return_value='processed abc') as process:
    response=c.post('/api/v1/references/'+item['id']+'/transcribe',json={'preserve':'full','strength':'faithful'})
   self.assertEqual(response.status_code,200,response.text);payload=response.json();self.assertEqual(payload['abc'],'processed abc');self.assertEqual(payload['recommendedCot'],'full');transcribe.assert_called_once();process.assert_called_once_with('raw abc','faithful')
if __name__=='__main__':unittest.main()
