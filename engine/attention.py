"""Application-side attention policy for the unmodified YuE2 runtime.

The NAR helper prefers the optional external FA2 package, with native Torch
FlashAttention and SDPA fallbacks. AR CUDA graph interfaces remain separate.
"""
from __future__ import annotations

from typing import Any, Callable


def can_attempt_flash(model: Any) -> bool:
    """Return whether the official NAR flash path is worth attempting."""
    try:
        import torch

        parameter = next(model.vae2llm.parameters())
        head_dim = int(getattr(model.config, "head_dim", 0))
        return (
            parameter.device.type == "cuda"
            and parameter.dtype in {torch.float16, torch.bfloat16}
            and 0 < head_dim <= 256
            and head_dim % 8 == 0
            and hasattr(torch.ops.aten, "_flash_attention_forward")
            and torch.backends.cuda.is_flash_attention_available()
        )
    except (AttributeError, StopIteration, TypeError, ValueError, RuntimeError):
        return False


def is_flash_capability_error(error: BaseException) -> bool:
    """Only fallback for kernel/shape availability errors, never model errors."""
    message = str(error).lower()
    markers = (
        "flashattention",
        "flash attention",
        "use_flash_attention",
        "no available kernel",
        "flash kernel",
    )
    return any(marker in message for marker in markers)


def external_flash_function(model):
    """Optional dependency; absence/DLL mismatch does not prevent generation."""
    try:
        import torch
        weight = next(model.vae2llm.parameters())
        dim = int(model.config.head_dim)
        if weight.device.type != "cuda" or weight.dtype not in (torch.float16, torch.bfloat16):
            return None
        if not 0 < dim <= 256 or dim % 8:
            return None
        from flash_attn import flash_attn_func
        return flash_attn_func
    except (ImportError, OSError, AttributeError, StopIteration):
        return None


def external_attention(func, q, k, v, *, causal=False, query_chunk_size=None):
    """Preserve absolute causal positions with FA2's bottom-right alignment."""
    import torch
    if causal and len(q) != len(k):
        raise ValueError("Causal prefill requires matching Q/K sequence lengths")
    block = query_chunk_size or len(q)
    outputs = []
    for start in range(0, len(q), block):
        end = min(start + block, len(q))
        # For later causal blocks, key length=end and query length=end-start:
        # bottom-right alignment yields the original global query positions.
        key, value = (k[:end], v[:end]) if causal else (k, v)
        outputs.append(func(q[start:end].unsqueeze(0).contiguous(),
                            key.unsqueeze(0).contiguous(), value.unsqueeze(0).contiguous(),
                            dropout_p=0.0, causal=causal)[0])
    return torch.cat(outputs, dim=0)


def external_capability_error(error):
    """Never retry OOM, invalid memory access, or unrelated model errors."""
    text = str(error).lower()
    if any(x in text for x in ("out of memory", "illegal memory", "device-side assert", "launch failure")):
        return False
    return isinstance(error, NotImplementedError) or any(x in text for x in (
        "no kernel image", "invalid device function", "no available kernel",
        "only supports", "not supported", "unsupported", "head dimension", "use_flash_attention", "not compiled with flash"))


def install_nar_policy(preference: str = "auto", query_chunk_size: int = 128) -> Callable[[], dict[str, str]]:
    """Worker-local NAR adapter. External FA2 -> native FA -> SDPA.

    No global torch patch, no persistent vendor modification. A recoverable
    kernel rejection retries the whole NAR pass with the original seed/noise.
    """
    if preference not in {"auto", "sdpa", "flash"}:
        raise ValueError("attention preference must be auto, sdpa or flash")
    from yue2 import nar
    original = vars(nar.synthesize).get("_yue2_original", nar.synthesize)
    state = {"requested": preference, "selected": "sdpa", "fallback": "false", "reason": ""}
    disabled = False

    def wrapped(model, prefix, codec, seed, *args, **kwargs):
        nonlocal disabled
        kwargs.pop("attention", None)
        kwargs["query_chunk_size"] = query_chunk_size
        state.update(selected="sdpa", fallback="false", reason="")
        func = external_flash_function(model) if preference != "sdpa" and not disabled else None
        if func is not None:
            saved_attention = nar.attention
            def adapter(q, k, v, *, causal=False, backend="sdpa", query_chunk_size=None):
                return external_attention(func, q, k, v, causal=causal, query_chunk_size=query_chunk_size)
            state["selected"] = "external-flash-attn-2"
            try:
                nar.attention = adapter
                return original(model, prefix, codec, seed, *args, attention="sdpa", **kwargs)
            except (RuntimeError, NotImplementedError) as error:
                if not external_capability_error(error):
                    raise
                disabled = True
                state.update(fallback="true", reason=str(error))
            finally:
                nar.attention = saved_attention
        selected = "flash" if preference != "sdpa" and can_attempt_flash(model) else "sdpa"
        state["selected"] = selected
        try:
            return original(model, prefix, codec, seed, *args, attention=selected, **kwargs)
        except (RuntimeError, NotImplementedError) as error:
            if selected != "flash" or not is_flash_capability_error(error) or not external_capability_error(error):
                raise
            state.update(selected="sdpa", fallback="true", reason=str(error))
            return original(model, prefix, codec, seed, *args, attention="sdpa", **kwargs)

    wrapped._yue2_original = original
    nar.synthesize = wrapped
    return lambda: dict(state)
