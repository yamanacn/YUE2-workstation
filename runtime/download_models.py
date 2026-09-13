"""Download pinned YuE2 inference assets; resume partial files and verify HF object hashes."""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
MODELS = [
    ("YuE2-3B", "1a96eca688d6ae5d7f0feb88573fec89920fcd19", "main-tree.json"),
    ("YuE2-Vae", "95535e72a97bc0f09b8ada125d26b4009428c0e8", "vae-tree.json"),
]
ALLOWED = {"config.json", "generation_config.json", "yue2_generation_config.json",
           "weights_manifest.json", "model.safetensors", "qwen.tiktoken",
           "LICENSE", "THIRD_PARTY_NOTICES.md",
           "licenses/SnakeBeta-NVIDIA-MIT.txt", "licenses/stable-audio-tools-MIT.txt"}

def verify(path, item):
    if not path.exists() or path.stat().st_size != item["size"]:
        return None
    sha256 = hashlib.sha256()
    gitsha = hashlib.sha1(f'blob {item["size"]}\0'.encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha256.update(chunk)
            gitsha.update(chunk)
    actual = sha256.hexdigest() if "lfs" in item else gitsha.hexdigest()
    expected = item.get("lfs", {}).get("oid", item["oid"])
    if actual != expected:
        raise ValueError(f"Hash mismatch: {path}")
    return {"path": str(path.relative_to(ROOT)), "bytes": item["size"],
            "sha256": sha256.hexdigest(), "source_hash": expected,
            "source_hash_type": "sha256" if "lfs" in item else "git-blob-sha1", "verified": True}

def download_model(spec):
    name, revision, tree = spec
    entries = json.loads((ROOT / "runtime" / tree).read_text(encoding="utf-8-sig"))
    records = []
    for item in entries:
        if item["path"] not in ALLOWED:
            continue
        destination = ROOT / "models" / name / item["path"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        record = verify(destination, item)
        if record is None:
            partial = destination.with_name(destination.name + ".partial")
            print(f"Downloading {name}/{item['path']} ({item['size']:,} bytes)", flush=True)
            subprocess.run(["curl.exe", "--fail", "--location", "--silent", "--show-error",
                            "--retry", "8", "--retry-delay", "3", "--connect-timeout", "30",
                            "--speed-time", "120", "--speed-limit", "1024",
                            "--continue-at", "-", "--output", str(partial),
                            f"https://huggingface.co/m-a-p/{name}/resolve/{revision}/{item['path']}?download=true"], check=True)
            record = verify(partial, item)
            if record is None:
                raise ValueError(f"Incomplete download: {partial}")
            partial.replace(destination)
            record["path"] = str(destination.relative_to(ROOT))
        records.append(record)
        print(f"Verified {name}/{item['path']}", flush=True)
    return {"repository": f"m-a-p/{name}", "revision": revision, "files": records}

if __name__ == "__main__":
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(download_model, MODELS))
    report = {"verified_at": datetime.now(timezone.utc).isoformat(), "models": results}
    (ROOT / "runtime" / "models-manifest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("All selected model files downloaded and verified.", flush=True)
