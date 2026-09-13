"""Environment-bound opt-in FP8 graph validation certificates.
Only the explicit benchmark writes a passing certificate; workers never guess.
"""
from pathlib import Path
import hashlib,json,subprocess
import torch
ROOT=Path(__file__).resolve().parents[1]
CACHE=ROOT/'runtime/fp8-graph/validation.json'

def fingerprint(model):
    import flash_attn
    from yue2 import quantization,cuda_graph,sampling
    paths=[Path(m.__file__) for m in (quantization,cuda_graph,sampling)]
    paths += [Path(__file__),ROOT/'engine/ar_attention.py',ROOT/'benchmarks/bench_fp8_graph.py']
    digest=hashlib.sha256()
    for p in paths:digest.update(p.read_bytes())
    driver=subprocess.check_output(['nvidia-smi','--query-gpu=driver_version','--format=csv,noheader'],text=True).strip()
    return {'gpu':torch.cuda.get_device_name(),'cc':list(torch.cuda.get_device_capability()),
            'driver':driver,'torch':torch.__version__,'cuda':torch.version.cuda,'flash':flash_attn.__version__,
            'runtime':digest.hexdigest(),'config':model.config.to_dict()}

def validation_status(model):
    try:
        if torch.cuda.get_device_capability() < (8,9):return {'validated':False,'reason':'unsupported_compute_capability'}
        key=fingerprint(model)
        saved=json.loads(CACHE.read_text(encoding='utf-8'))
        if saved.get('fingerprint')!=key:return {'validated':False,'reason':'environment_or_model_changed'}
        if saved.get('validated') is not True:return {'validated':False,'reason':'validation_failed'}
        return {'validated':True,'reason':'local_benchmark_passed'}
    except (OSError,ValueError,ImportError,subprocess.SubprocessError) as error:
        return {'validated':False,'reason':f'validation_unavailable: {error}'}
