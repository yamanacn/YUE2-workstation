"""Read-only environment inspection and optional tiny BF16 CUDA SDPA probe."""
import importlib
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = {
    "torch": "2.10.0", "transformers": "4.57.6", "huggingface-hub": "0.36.2",
    "safetensors": "0.7.0", "tiktoken": "0.12.0", "numpy": "2.2.6",
    "soundfile": "0.13.1", "accelerate": "1.13.0", "yue2-infer": "0.1.6",
}

def main():
    versions = {key: importlib.metadata.version(key) for key in PACKAGES}
    for key, expected in PACKAGES.items():
        assert versions[key].split("+")[0] == expected, (key, versions[key], expected)
        importlib.import_module({"huggingface-hub": "huggingface_hub", "yue2-infer": "yue2"}.get(key, key))
    from yue2 import YuE2Pipeline
    from yue2.modeling_yue2 import YuE2ForCausalLM
    from yue2.modeling_vae import YuE2VAE
    import torch
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "python": sys.executable,
              "python_version": platform.python_version(), "platform": platform.platform(),
              "versions": versions, "cuda_available": torch.cuda.is_available(),
              "cuda_runtime": torch.version.cuda, "cuda_probe": "not run", "model_inference": "not run"}
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        smi_free_mib = int(subprocess.check_output([
            "nvidia-smi", "--id=0", "--query-gpu=memory.free", "--format=csv,noheader,nounits"
        ], text=True).strip())
        # WDDM CUDA memory reporting can differ from the physical-device inventory.
        available = min(free, smi_free_mib * 2**20)
        report.update({"gpu": torch.cuda.get_device_name(), "capability": torch.cuda.get_device_capability(),
                       "bf16_supported": torch.cuda.is_bf16_supported(), "free_bytes": free, "total_bytes": total,
                       "nvidia_smi_free_mib": smi_free_mib, "conservative_free_bytes": available,
                       "torch_arch_list": torch.cuda.get_arch_list()})
        if available >= 20 * 2**30:
            torch.cuda.reset_peak_memory_stats()
            tensor = torch.randn((1, 2, 64, 64), device="cuda", dtype=torch.bfloat16)
            result = torch.nn.functional.scaled_dot_product_attention(tensor, tensor, tensor)
            torch.cuda.synchronize()
            assert torch.isfinite(result).all().item()
            report["cuda_probe"] = "PASS: finite BF16 SDPA output, shape [1, 2, 64, 64]"
            report["cuda_probe_peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            del tensor, result
            torch.cuda.empty_cache()
        else:
            report["cuda_probe"] = "SKIPPED: free VRAM below 20 GiB"
    output = ROOT / "runtime" / "sanity-report.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
