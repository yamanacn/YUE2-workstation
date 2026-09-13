"""Application runtime policy for memory and experimental acceleration."""
import math

DEFAULT = dict(quantization='none', offloadAr=True, vaeCoreFrames=512,
               memoryBudgetGiB=0, dynamicTokens=True, targetSeconds=0,
               attention='auto', queryChunkSize=128, fp8CudaGraph=False)

def settings(config):
    value = config.get('performance', {})
    if not isinstance(value, dict):
        raise ValueError('performance must be an object')
    p = {**DEFAULT, **value}
    for key, allowed in [('quantization', ('none', 'fp8')), ('attention', ('auto', 'sdpa')),
                         ('vaeCoreFrames', (256, 512, 1024)), ('queryChunkSize', (64, 128, 256))]:
        if p[key] not in allowed:
            raise ValueError('Invalid performance setting: ' + key)
    for key in ('offloadAr', 'dynamicTokens', 'fp8CudaGraph'):
        if type(p[key]) is not bool:
            raise ValueError('Invalid boolean: ' + key)
    for key in ('memoryBudgetGiB', 'targetSeconds'):
        if type(p[key]) not in (int, float) or not math.isfinite(p[key]):
            raise ValueError('Invalid number: ' + key)
    if p['memoryBudgetGiB'] != 0 and p['memoryBudgetGiB'] <= 2:
        raise ValueError('memoryBudgetGiB must be auto (0) or greater than 2')
    if not 0 <= p['targetSeconds'] <= 960:
        raise ValueError('targetSeconds must be between 0 and 960')
    return p

def token_budget(config, reference_seconds=None):
    p = settings(config)
    seconds = p['targetSeconds'] or reference_seconds
    if not p['dynamicTokens'] or not seconds:
        return config['maxTokens']
    return min(config['maxTokens'], max(200, math.ceil(seconds * 27.5) + 128))

def fp8_unavailable_reason():
    import torch
    if not torch.cuda.is_available() or torch.cuda.get_device_capability(0) < (8, 9):
        return 'FP8 requires CUDA compute capability >= 8.9'
    try:
        from yue2.quantization import FP8Linear
        with torch.inference_mode():
            layer=FP8Linear(torch.nn.Linear(16,16,bias=False,dtype=torch.bfloat16),'cuda')
            layer(torch.zeros((1,16),device='cuda',dtype=torch.bfloat16))
            torch.cuda.synchronize()
        return None
    except (RuntimeError, NotImplementedError, AttributeError) as error:
        if isinstance(error, torch.OutOfMemoryError):
            raise
        return str(error)
