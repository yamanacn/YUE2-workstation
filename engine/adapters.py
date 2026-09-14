r"""LoRA adapters for YuE2 runs.

Adapters live under ``models/loras/<artist|nar>/<family>/`` with an
``adapter.json`` sidecar; every ``*.pt`` in the folder is one selectable
checkpoint, so ``defaultFile`` marks the one the UI leads with.

They are applied by folding their deltas into the base weights *before* the
first forward pass, which keeps the official sampler, CUDA graphs, FP8
preparation and the result identity intact. The vendored ``yue2`` package is
never modified, so engine/runtime_integrity.py keeps passing unchanged.

Checkpoint formats mirror the training repository (E:\项目\YUE2训练器):

    artist AR : {"lora": [A, B, ... 392 tensors], "rank": 64, "targets": "..."}
    NAR       : {"lora": [...], "io": {"vae2llm": {...}, "llm2vae": {...}}}

Merging follows that repository's ``scripts/ar_generate.py`` exactly::

    W += scale * (B @ A)      # B@A in fp32, cast back to the base dtype
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from pathlib import Path

from .common import ROOT

LORA_ROOT = ROOT / 'models' / 'loras'
ARTIST = 'artist'
NAR = 'nar'
KINDS = (ARTIST, NAR)
ARTIST_TARGETS = (('self_attn', ('q_proj', 'k_proj', 'v_proj', 'o_proj')),
                  ('mlp', ('gate_proj', 'up_proj', 'down_proj')))
NAR_TARGETS = (('nar_self_attn', ('q_proj', 'k_proj', 'v_proj', 'o_proj')),
               ('nar_mlp', ('gate_proj', 'up_proj', 'down_proj')))
SELECTION_FIELDS = ('artistId', 'artistScale', 'narId', 'narEnabled')
DEFAULT_SCALE = 1.0
MAX_SCALE = 1.5
PUBLIC_FIELDS = ('id', 'name', 'family', 'file', 'format', 'rank', 'bytes', 'sha256',
                 'recommendedNarAdapterId', 'default')
_HASHES = {}


class AdapterError(ValueError):
    """An adapter is missing, changed on disk, or incompatible with the model.

    Subclasses ValueError so the service's draft validation reports it as a
    rejected request instead of a server error."""

    def __init__(self, message, code='adapter_invalid'):
        super().__init__(message)
        self.code = code


def file_sha256(path):
    """SHA256 with a (path, size, mtime) cache: the checkpoints are ~270 MB."""
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    cached = _HASHES.get(key)
    if cached:
        return cached
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    value = digest.hexdigest()
    _HASHES[key] = value
    return value


def _sidecar(folder):
    path = folder / 'adapter.json'
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe(path):
    """Adapter files must resolve inside models/loras and be real files."""
    resolved = Path(path).resolve()
    if Path(path).is_symlink() or not resolved.is_relative_to(LORA_ROOT.resolve()):
        raise AdapterError('LoRA 路径不在 models/loras 内：' + Path(path).name)
    if not resolved.is_file():
        raise AdapterError('LoRA 文件不存在：' + Path(path).name, 'adapter_missing')
    return resolved


def _entries(folder, kind, files):
    sidecar = _sidecar(folder)
    display = str(sidecar.get('displayName') or folder.name)
    default_file = sidecar.get('defaultFile')
    fallback_format = 'yue2_artist_ar_lora' if kind == ARTIST else 'yue2_realaudio_nar_v4'
    rank = sidecar.get('rank') if type(sidecar.get('rank')) is int else None
    single = len(files) == 1
    items = []
    for path in files:
        resolved = _safe(path)
        label = display if single else f'{display} · {path.stem}'
        identifier = f'{kind}/{folder.name}' + ('' if single else f'/{path.stem}')
        items.append({
            'id': identifier,
            'type': kind,
            'name': label,
            'family': folder.name,
            'file': path.name,
            'path': str(resolved),
            'format': str(sidecar.get('format') or fallback_format),
            'rank': rank,
            'bytes': resolved.stat().st_size,
            'sha256': file_sha256(resolved),
            'baseModel': sidecar.get('baseModel'),
            'recommendedNarAdapterId': sidecar.get('recommendedNarAdapterId'),
            'default': path.name == default_file,
        })
    return items


def scan_registry():
    """Every installed adapter, grouped by kind. An empty root is not an error."""
    registry = {kind: [] for kind in KINDS}
    for kind in KINDS:
        base = LORA_ROOT / kind
        if not base.is_dir():
            continue
        for folder in sorted((item for item in base.iterdir() if item.is_dir()), key=lambda item: item.name):
            files = sorted((path for path in folder.glob('*.pt') if path.is_file()), key=lambda path: path.name)
            if files:
                registry[kind].extend(_entries(folder, kind, files))
    for items in registry.values():
        items.sort(key=lambda item: (not item['default'], item['id']))
    return registry


def public_catalog():
    """Registry view for the browser: no filesystem paths are exposed."""
    return {kind: [{field: item[field] for field in PUBLIC_FIELDS} for item in items]
            for kind, items in scan_registry().items()}


def resolve(adapter_id):
    if not adapter_id:
        return None
    for items in scan_registry().values():
        for item in items:
            if item['id'] == adapter_id:
                return item
    raise AdapterError('没有找到 LoRA：' + str(adapter_id), 'adapter_missing')


def normalize_request(value):
    """Turn ``draft.config.adapters`` into a resolved request, or None when off.

    Runs when a batch is accepted (to freeze the identity) and again when the
    worker starts, so a checkpoint replaced while queued fails the run instead
    of silently changing the result.
    """
    if value in (None, {}, []):
        return None
    if not isinstance(value, dict):
        raise AdapterError('LoRA 设置必须是对象')
    unknown = set(value) - set(SELECTION_FIELDS)
    if unknown:
        raise AdapterError('LoRA 设置包含未知字段：' + ', '.join(sorted(unknown)))
    artist_id = value.get('artistId') or None
    nar_id = value.get('narId') or None
    nar_enabled = bool(value.get('narEnabled'))
    scale = value.get('artistScale', DEFAULT_SCALE)
    for key, item in (('artistId', artist_id), ('narId', nar_id)):
        if item is not None and (not isinstance(item, str) or not item.strip() or len(item) > 180):
            raise AdapterError(key + ' 无效')
    if scale is None:
        scale = DEFAULT_SCALE
    if type(scale) not in (int, float) or not math.isfinite(scale) or not 0 <= scale <= MAX_SCALE:
        raise AdapterError(f'artistScale 必须在 0 到 {MAX_SCALE} 之间')
    if nar_enabled and not nar_id:
        raise AdapterError('启用 NAR 时必须选择 narId')
    artist = resolve(artist_id) if artist_id else None
    nar = resolve(nar_id) if (nar_enabled and nar_id) else None
    if artist is None and nar is None:
        return None
    if artist is not None and not artist['id'].startswith(ARTIST + '/'):
        raise AdapterError('artistId 指向的不是风格 LoRA：' + artist['id'])
    if nar is not None and not nar['id'].startswith(NAR + '/'):
        raise AdapterError('narId 指向的不是音色适配器：' + nar['id'])
    if artist is not None:
        artist = {**artist, 'scale': round(float(scale), 4)}
    return {'artist': artist, 'nar': nar}


def adapter_identity(request):
    """The frozen identity of every adapter in a run (the strength lives in config)."""
    if not request:
        return None
    fields = ('id', 'sha256', 'bytes', 'rank', 'format')
    return {kind: ({field: request[kind][field] for field in fields} if request.get(kind) else None)
            for kind in KINDS}


def verify_identity(expected, request):
    """Fail when a checkpoint was replaced between acceptance and execution."""
    expected = expected or {}
    for kind in KINDS:
        want, got = expected.get(kind), (request or {}).get(kind)
        if (want is None) != (got is None):
            raise AdapterError(f'{kind} LoRA 与任务快照不一致', 'adapter_changed')
        if not want:
            continue
        if want.get('id') != got['id'] or want.get('sha256') != got['sha256'] or want.get('bytes') != got['bytes']:
            raise AdapterError(f'LoRA 文件在排队期间发生变化：{got["id"]}', 'adapter_changed')


def load_checkpoint(path):
    import torch
    try:
        data = torch.load(path, map_location='cpu', weights_only=True)
    except Exception:
        try:
            data = torch.load(path, map_location='cpu', weights_only=False)
        except (OSError, RuntimeError, EOFError) as error:
            raise AdapterError(f'无法读取 LoRA 文件：{error}') from error
    if not isinstance(data, dict) or not isinstance(data.get('lora'), (list, tuple)) or not data['lora']:
        raise AdapterError(f'{Path(path).name} 不是可识别的 LoRA 检查点（缺少 lora 张量列表）', 'adapter_incompatible')
    return data


def target_linears(model, targets):
    """Walk the base model in the exact order the trainer used to save tensors."""
    found = []
    for layer in model.model.layers:
        for module_name, names in targets:
            module = getattr(layer, module_name, None)
            if module is None:
                raise AdapterError(f'模型缺少 {module_name} 模块，无法应用 LoRA', 'adapter_incompatible')
            for name in names:
                linear = getattr(module, name, None)
                if not hasattr(linear, 'weight') or not hasattr(linear, 'in_features'):
                    raise AdapterError(f'模型缺少 {module_name}.{name}，无法应用 LoRA', 'adapter_incompatible')
                found.append((f'{module_name}.{name}', linear))
    return found


def validate_tensors(linears, tensors, kind):
    """Validate every shape before anything is merged, so a bad file cannot
    leave the model half-patched."""
    expected = 2 * len(linears)
    if len(tensors) != expected:
        raise AdapterError(f'{kind} LoRA 张量数量为 {len(tensors)}，期望 {expected}', 'adapter_incompatible')
    for index, (name, linear) in enumerate(linears):
        first, second = tensors[2 * index], tensors[2 * index + 1]
        if getattr(first, 'ndim', 0) != 2 or getattr(second, 'ndim', 0) != 2:
            raise AdapterError(f'{kind} LoRA 的 {name} 不是二维张量', 'adapter_incompatible')
        rank = int(first.shape[0])
        if first.shape[1] != linear.in_features or tuple(second.shape) != (linear.out_features, rank):
            raise AdapterError(f'{kind} LoRA 的 {name} 形状与模型不匹配：'
                               f'A{tuple(first.shape)} B{tuple(second.shape)}，'
                               f'期望 A(r,{linear.in_features}) B({linear.out_features},r)', 'adapter_incompatible')
    return len(linears)


def merge_tensors(linears, tensors, scale, device):
    """W += scale · (B @ A) in fp32, cast back to the weight's dtype."""
    import torch
    merged = 0
    with torch.no_grad():
        for index, (_, linear) in enumerate(linears):
            first = tensors[2 * index].to(device).float()
            second = tensors[2 * index + 1].to(device).float()
            delta = scale * (second @ first)
            linear.weight.add_(delta.to(device=linear.weight.device, dtype=linear.weight.dtype))
            merged += 1
    return merged


def load_nar_bridges(model, checkpoint):
    """The Real Audio NAR adapter also swaps the two audio/llm bridges."""
    import torch
    io = checkpoint.get('io') or {}
    loaded = []
    for attribute in ('vae2llm', 'llm2vae'):
        state = io.get(attribute)
        if not state:
            raise AdapterError(f'NAR LoRA 缺少 io.{attribute}', 'adapter_incompatible')
        module = getattr(model, attribute, None)
        if module is None:
            raise AdapterError(f'模型缺少 {attribute}', 'adapter_incompatible')
        module.load_state_dict({key: value.to(torch.bfloat16) for key, value in state.items()})
        loaded.append(attribute)
    return loaded


def prepare_pipeline_adapters(pipe, request, snapshot_identity, quantization, progress=None):
    """Fold the requested adapters into a freshly built pipeline.

    Returns an audit dict, or None when the request selects no adapter. The
    pipeline is left untouched otherwise, so a run without LoRA behaves exactly
    as before.
    """
    if not request:
        return None
    verify_identity(snapshot_identity, request)
    original = pipe.quantization
    started = time.perf_counter()
    audit = {'requested': {kind: (request[kind]['id'] if request.get(kind) else None) for kind in KINDS},
             'quantization': original, 'adapters': {}}
    # FP8 replaces the AR Linears with FP8Linear, so the deltas must be folded
    # into the BF16 weights first; prepare_fp8_ar() then captures base+LoRA as
    # the CPU originals that restore_ar() brings back before the NAR phase.
    try:
        if quantization == 'fp8':
            pipe.quantization = 'none'
        model = pipe._load_model()
        device = pipe.device
        plan = []
        for kind, targets in ((ARTIST, ARTIST_TARGETS), (NAR, NAR_TARGETS)):
            if not request.get(kind):
                continue
            checkpoint = load_checkpoint(Path(request[kind]['path']))
            linears = target_linears(model, targets)
            validate_tensors(linears, checkpoint['lora'], kind)
            plan.append((kind, linears, checkpoint))
        for kind, linears, checkpoint in plan:
            scale = float(request[kind].get('scale', DEFAULT_SCALE)) if kind == ARTIST else 1.0
            merged = merge_tensors(linears, checkpoint['lora'], scale, device)
            entry = {'id': request[kind]['id'], 'sha256': request[kind]['sha256'],
                     'rank': checkpoint.get('rank'), 'scale': scale, 'mergedLinears': merged}
            if kind == NAR:
                entry['ioBridgesLoaded'] = load_nar_bridges(model, checkpoint)
            audit['adapters'][kind] = entry
            if progress:
                label = request[kind].get('name') or request[kind]['id']
                progress(f"已合并 {label}（强度 {scale:g}）" if kind == ARTIST else f"已载入音色适配器 {label}")
        if quantization == 'fp8':
            from yue2.quantization import prepare_fp8_ar
            audit['fp8'] = prepare_fp8_ar(model, device)
    finally:
        pipe.quantization = original
    audit['seconds'] = round(time.perf_counter() - started, 3)
    pipe._adapter_config = {kind: ({'id': request[kind]['id'], 'scale': float(request[kind]['scale'])} if kind == ARTIST
                                   else {'id': request[kind]['id'], 'enabled': True}) if request.get(kind) else None
                            for kind in KINDS}
    return audit
