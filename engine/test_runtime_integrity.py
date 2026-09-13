"""Regression coverage for the actual worker's preflight runtime gate."""
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from .common import CODE
from .runtime_integrity import verify_runtime

class RuntimeIntegrityTests(unittest.TestCase):
    def test_current_reviewed_runtime_passes(self):
        self.assertEqual(verify_runtime()['patchSet'],'fp8-cuda-graph-v1')

    def test_modified_runtime_is_only_accepted_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); target=root/'src/yue2/sampling.py'
            target.parent.mkdir(parents=True); target.write_text('reviewed\n',encoding='utf-8')
            (root/'.git').mkdir()
            manifest=root/'patches.json'
            manifest.write_text(json.dumps({'baseRevision':CODE,'patchSet':'test','files':{'src/yue2/sampling.py':hashlib.sha256(b'reviewed\n').hexdigest()}}),encoding='utf-8')
            with patch('engine.runtime_integrity.subprocess.check_output',side_effect=[CODE,'src/yue2/sampling.py\0','']):
                self.assertEqual(verify_runtime(root,manifest)['patchSet'],'test')
            target.write_text('unexpected\n',encoding='utf-8')
            with patch('engine.runtime_integrity.subprocess.check_output',side_effect=[CODE,'src/yue2/sampling.py\0','']):
                with self.assertRaisesRegex(RuntimeError,'patch verification failed'):
                    verify_runtime(root,manifest)
            for tracked,untracked in [('src/yue2/other.py\0',''),('','src/yue2/other.py\0')]:
                with patch('engine.runtime_integrity.subprocess.check_output',side_effect=[CODE,tracked,untracked]):
                    with self.assertRaisesRegex(RuntimeError,'Unrecognized runtime'):
                        verify_runtime(root,manifest)

    def test_revision_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'.git').mkdir(); target=root/'src/yue2/sampling.py'
            target.parent.mkdir(parents=True); target.write_text('reviewed\n',encoding='utf-8')
            manifest=root/'patches.json'
            manifest.write_text(json.dumps({'baseRevision':CODE,'patchSet':'test','files':{'src/yue2/sampling.py':hashlib.sha256(b'reviewed\n').hexdigest()}}),encoding='utf-8')
            with patch('engine.runtime_integrity.subprocess.check_output',return_value='wrong'):
                with self.assertRaisesRegex(RuntimeError,'revision mismatch'):
                    verify_runtime(root,manifest)

if __name__=='__main__': unittest.main()
