import os,sys,unittest
from pathlib import Path
from unittest.mock import patch

from .runtime_paths import CACHE_ROOT, MAIN_RUNTIME, main_python, runtime_environment, score_python


class RuntimePathTests(unittest.TestCase):
    def test_generation_and_score_workers_share_internal_python(self):
        with patch.dict(os.environ, {'YUE2_PORTABLE':'1'}):
            expected=MAIN_RUNTIME/'python.exe'
            if expected.is_file():
                self.assertEqual(main_python(), expected)
                self.assertEqual(score_python(), main_python())
            else:
                with self.assertRaises(RuntimeError): main_python()

    def test_source_mode_uses_current_or_project_venv_python(self):
        with patch.dict(os.environ, {}, clear=True):
            expected=(Path(__file__).resolve().parents[1]/'.venv/Scripts/python.exe')
            if not expected.is_file(): expected=Path(sys.executable).resolve()
            self.assertEqual(main_python(),expected.resolve())

    def test_runtime_environment_isolated_from_user_python_paths(self):
        env = runtime_environment({'PATH': 'external', 'PYTHONPATH': 'external', 'PYTHONHOME': 'external'})
        self.assertNotIn('PYTHONPATH', env)
        self.assertNotIn('PYTHONHOME', env)
        self.assertEqual(Path(env['YUE2_CACHE']), CACHE_ROOT / 'yue2')
        self.assertEqual(env['PYTHONNOUSERSITE'], '1')


if __name__ == '__main__':
    unittest.main()
