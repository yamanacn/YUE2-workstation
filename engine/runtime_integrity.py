"""Verify the pinned upstream runtime plus the explicitly reviewed local patch set."""
import hashlib
import json
import os
import subprocess
from pathlib import Path
from .common import ROOT, CODE


def verify_runtime(vendor=None, manifest_path=None):
    vendor = Path(vendor) if vendor is not None else ROOT / 'vendor/yue2'
    manifest_path = Path(manifest_path) if manifest_path is not None else Path(__file__).with_name('vendor-patches.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    def git(*args):
        return subprocess.check_output(['git', '-C', str(vendor), *args], encoding='utf-8').strip()
    portable = os.environ.get('YUE2_PORTABLE') == '1'
    source_snapshot = not (vendor / '.git').exists()
    if portable or source_snapshot:
        commit = manifest['baseRevision']
    else:
        commit = git('rev-parse', 'HEAD')
    if commit != CODE:
        raise RuntimeError('ObservedPipeline revision mismatch')
    if manifest['baseRevision'] != commit:
        raise RuntimeError('Runtime patch manifest base revision mismatch')
    allowed = manifest['files']
    if portable or source_snapshot:
        unexpected = set()
    else:
        changed = set(filter(None, git('diff', 'HEAD', '--name-only', '-z', '--', 'src/yue2').split('\0')))
        untracked = set(filter(None, git('ls-files', '--others', '--exclude-standard', '-z', '--', 'src/yue2').split('\0')))
        unexpected = (changed | untracked) - set(allowed)
        if unexpected:
            raise RuntimeError('Unrecognized runtime modifications: ' + ', '.join(sorted(unexpected)))
    for name, expected in allowed.items():
        path = vendor / name
        if not path.is_file():
            raise RuntimeError('Runtime patch file missing: ' + name)
        actual = hashlib.sha256(path.read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8')).hexdigest()
        if actual != expected:
            raise RuntimeError('Runtime patch verification failed: ' + name)
    mode = 'portable-static' if portable else 'source-static' if source_snapshot else 'git'
    return {'baseRevision': commit, 'patchSet': manifest['patchSet'], 'files': allowed, 'mode': mode}
