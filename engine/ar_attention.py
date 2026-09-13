"""Worker-local external FA2 adapters for the official YuE2 AR loop.

Keep sampling, RoPE, CFG, static cache allocation, and graph lifecycle in YuE2.
Only the attention implementation and graph decode attention call are adapted.
"""
from contextlib import contextmanager
from copy import deepcopy

import torch
from yue2.cuda_graph import GraphAR

from .attention import external_capability_error, external_flash_function


class ExternalFlashUnavailable(RuntimeError):
    pass


class GraphCaptureUnavailable(RuntimeError):
    pass


def flash_call(function, *args, **kwargs):
    try:
        return function(*args, **kwargs)
    except (RuntimeError, NotImplementedError) as error:
        if not external_capability_error(error):
            raise
        raise ExternalFlashUnavailable(str(error)) from error


def external_flash_installed():
    try:
        from flash_attn import flash_attn_func, flash_attn_with_kvcache
        return callable(flash_attn_func) and callable(flash_attn_with_kvcache)
    except (ImportError, OSError):
        return False


@contextmanager
def eager_flash_scope(function, counters):
    """The official unpadded prefill/decode has no custom mask.

    Preserve arbitrary masks via the original helper. Scoped to one AR phase,
    including FP8 (whose Q/K/V outputs are BF16), never all of torch SDPA.
    """
    from yue2 import modeling_yue2
    original = modeling_yue2.sdpa

    def attention(query, key, value, *, attn_mask=None, is_causal=False):
        if (attn_mask is not None or query.device.type != 'cuda'
                or query.dtype not in (torch.bfloat16, torch.float16)):
            counters['maskedOrUnsupportedSdpaCalls'] += 1
            return original(query, key, value, attn_mask=attn_mask, is_causal=is_causal)
        result = flash_call(function, query.transpose(1, 2), key.transpose(1, 2),
                            value.transpose(1, 2), dropout_p=0.0, causal=is_causal)
        counters['externalPrefillCalls' if query.shape[2] > 1 else 'externalEagerDecodeCalls'] += 1
        return result.transpose(1, 2)

    modeling_yue2.sdpa = attention
    try:
        yield
    finally:
        modeling_yue2.sdpa = original


class ExternalGraphAR(GraphAR):
    """Official GraphAR lifecycle, external cache-length-aware decode kernel.

    QKV projections and cache writes mirror the unfused official _decode.
    Retains the official KV cache, RoPE and CFG math; FP8 graphs require validation.
    """
    def __init__(self, model, prefixes, max_tokens, *, capture=True,
                 attention_backend='auto', fuse_projections=False):
        if fuse_projections:
            raise ValueError('ExternalGraphAR does not enable fused projections')
        from flash_attn import flash_attn_with_kvcache
        self.flash_kvcache = flash_attn_with_kvcache
        super().__init__(model, prefixes, max_tokens, capture=capture,
                         attention_backend='sdpa', fuse_projections=False)
        self.attention_backend = 'external-flash-attn-2-kvcache'

    @torch.inference_mode()
    def _decode(self):
        backbone, config = self.model.model, self.model.config
        cos, sin = backbone.rotary_emb(self.positions[:, None])
        x = backbone.embed_tokens(self.tokens)
        used_lengths = (self.positions + 1).to(torch.int32)
        slots = self.positions[:, None, None, None].expand(
            self.branches, 1, config.num_key_value_heads, config.head_dim)
        for layer, keys, values in zip(backbone.layers, self.keys, self.values):
            q, k, v = layer.self_attn.project_qkv(layer.input_layernorm(x), cos, sin)
            keys.scatter_(1, slots, k)
            values.scatter_(1, slots, v)
            # Only filled slots are visible; each CFG branch has its own length.
            # K/V already contain rotated new keys: do not append or rotate twice.
            h = flash_call(self.flash_kvcache, q, keys, values,
                           cache_seqlens=used_lengths, causal=False)
            x = x + layer.self_attn.o_proj(h.reshape(self.branches, 1, -1))
            x = x + layer.mlp(layer.post_attention_layernorm(x))
        output = self.model.lm_head(backbone.norm(x))[:, 0]
        self.positions.add_(1)
        return output

    def _capture(self):
        try:
            return super()._capture()
        except RuntimeError as error:
            message = str(error).lower()
            if not any(x in message for x in ('out of memory', 'illegal memory', 'device-side assert', 'launch failure')) and any(
                    x in message for x in ('not permitted when stream is capturing', 'not supported during capture')):
                raise GraphCaptureUnavailable(str(error)) from error
            raise


def install_ar_policy(preference='auto', fp8_cuda_graph=False):
    """Replace only pipeline's sampling entry; retries restart one AR phase.

    Unsupported external kernels -> original eager SDPA. Capture-only rejection
    -> external eager. Neither path retries OOM or damaged CUDA contexts.
    """
    if preference not in ('auto', 'sdpa'):
        raise ValueError('AR attention preference must be auto or sdpa')
    from yue2 import pipeline, cuda_graph
    original = vars(pipeline.generate_tokens).get('_yue2_original', pipeline.generate_tokens)
    disabled = False
    graph_disabled = False
    state = {'requested': preference, 'externalInstalled': external_flash_installed(), 'phases': {}}

    def generate(model, prefix, sampling, seed, phase, *args, **kwargs):
        nonlocal disabled, graph_disabled
        function = external_flash_function(model) if preference == 'auto' and not disabled else None
        use_external = function is not None
        use_graph = bool(kwargs.get('use_cuda_graph', True)) and preference == 'auto' and not graph_disabled
        if not use_external and not torch.backends.cuda.is_flash_attention_available():
            use_graph = False
        fp8_validation = {'validated': False, 'reason': 'disabled'}
        if getattr(model, '_yue2_fp8_originals', {}):
            if fp8_cuda_graph and use_graph and use_external:
                from .fp8_graph import validation_status
                fp8_validation = validation_status(model)
            model._yue2_fp8_graph_validated = fp8_validation['validated']
            use_graph = use_graph and fp8_validation['validated']
        record = {'status': 'running', 'execution': 'eager', 'attention': 'sdpa',
                  'fallback': False, 'reasons': [], 'externalPrefillCalls': 0,
                  'externalEagerDecodeCalls': 0, 'maskedOrUnsupportedSdpaCalls': 0}
        record['fp8GraphValidation'] = fp8_validation
        state['phases'][phase] = record
        while True:
            saved_graph = cuda_graph.GraphAR
            kwargs['use_cuda_graph'] = use_graph
            record.update(execution='cuda_graph' if use_graph else 'eager',
                          attention=('external-flash-attn-2-kvcache' if use_graph else 'external-flash-attn-2') if use_external else 'sdpa')
            try:
                if use_external:
                    cuda_graph.GraphAR = ExternalGraphAR
                    with eager_flash_scope(function, record):
                        result = original(model, prefix, sampling, seed, phase, *args, **kwargs)
                else:
                    result = original(model, prefix, sampling, seed, phase, *args, **kwargs)
                timing = result[1]
                if use_external and timing['execution'] == 'eager':
                    timing['attention'] = 'external-flash-attn-2'
                timing['attention_fallback'] = record['fallback']
                record.update(status='succeeded', execution=timing['execution'], attention=timing['attention'])
                return result
            except GraphCaptureUnavailable as error:
                graph_disabled = True
                use_graph = False
                record['fallback'] = True
                record['reasons'].append(str(error))
            except ExternalFlashUnavailable as error:
                disabled = True
                use_external = use_graph = False
                record['fallback'] = True
                record['reasons'].append(str(error))
            except BaseException as error:
                record.update(status='failed', error=f'{type(error).__name__}: {error}')
                raise
            finally:
                cuda_graph.GraphAR = saved_graph

    generate._yue2_original = original
    pipeline.generate_tokens = generate
    return lambda: deepcopy(state)
