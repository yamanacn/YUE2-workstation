"""Download the four model repositories required by YuE2 Workstation."""
from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "YuE2-3B": ("m-a-p/YuE2-3B", "1a96eca688d6ae5d7f0feb88573fec89920fcd19"),
    "YuE2-Vae": ("m-a-p/YuE2-Vae", "95535e72a97bc0f09b8ada125d26b4009428c0e8"),
    "MERT-v2-FullSong": ("m-a-p/MERT-v2-FullSong", "d8ba1c745e733b3908ce6ad16ebeb17ac7600a42"),
    "SheetSage2": ("m-a-p/SheetSage2", "eab522a8168e8b8b8c4856bf8609cd86198f01fe"),
}
REQUIRED = {
    "YuE2-3B": ("config.json", "model.safetensors", "qwen.tiktoken", "weights_manifest.json"),
    "YuE2-Vae": ("config.json", "model.safetensors", "weights_manifest.json"),
    "MERT-v2-FullSong": ("config.json", "model.safetensors"),
    "SheetSage2": ("config.json", "model.safetensors"),
}


def download(name: str) -> None:
    repo, revision = MODELS[name]
    target = ROOT / "models" / name
    print(f"Downloading {repo} -> {target}", flush=True)
    snapshot_download(
        repo_id=repo,
        revision=revision,
        local_dir=target,
        local_dir_use_symlinks=False,
    )
    missing = [filename for filename in REQUIRED[name] if not (target / filename).is_file()]
    if missing:
        raise RuntimeError(f"{name} is incomplete: {', '.join(missing)}")
    print(f"Ready: {name}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*", choices=tuple(MODELS), default=tuple(MODELS))
    args = parser.parse_args()
    for name in args.models:
        download(name)


if __name__ == "__main__":
    main()
