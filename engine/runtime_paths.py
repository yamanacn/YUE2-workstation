"""Project-local runtime paths used by the service and worker processes."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = ROOT / "runtime"
MAIN_RUNTIME = RUNTIME_ROOT / "python312"
CACHE_ROOT = RUNTIME_ROOT / "cache"
PLAYWRIGHT_BROWSERS_ROOT = RUNTIME_ROOT / "playwright-browsers"


def main_python() -> Path:
    portable = os.environ.get("YUE2_PORTABLE") == "1"
    if portable:
        path = MAIN_RUNTIME / "python.exe"
        if not path.is_file():
            raise RuntimeError(f"YuE2 Python 3.12 运行时不存在：{path}")
        return path
    configured = os.environ.get("YUE2_PYTHON")
    candidates = [Path(configured)] if configured else []
    candidates.extend((ROOT / ".venv" / "Scripts" / "python.exe", Path(sys.executable)))
    for path in candidates:
        if path.is_file():
            return path.resolve()
    raise RuntimeError("未找到开发环境 Python；请先运行 runtime/setup-dev.ps1。")


def score_python() -> Path:
    # SheetSage2 is compatible with the shared Python 3.12 + Torch 2.10
    # runtime; keep this named helper for the score worker call sites.
    return main_python()


def portable_runtime_ready() -> bool:
    return (MAIN_RUNTIME / "python.exe").is_file()


def runtime_environment(base=None) -> dict[str, str]:
    """Return an isolated environment for portable or source development."""
    environment = dict(os.environ if base is None else base)
    environment.update({
        "YUE2_CACHE": str(CACHE_ROOT / "yue2"),
        "HF_HOME": str(CACHE_ROOT / "huggingface"),
        "HF_HUB_CACHE": str(CACHE_ROOT / "huggingface" / "hub"),
        "HF_MODULES_CACHE": str(CACHE_ROOT / "huggingface" / "modules"),
        "TRANSFORMERS_CACHE": str(CACHE_ROOT / "huggingface" / "transformers"),
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    if os.environ.get("YUE2_PORTABLE") == "1":
        environment["YUE2_PORTABLE"] = "1"
        environment["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_ROOT)
    else:
        environment.pop("YUE2_PORTABLE", None)
        environment["YUE2_PYTHON"] = str(main_python())
        if PLAYWRIGHT_BROWSERS_ROOT.is_dir():
            environment["PLAYWRIGHT_BROWSERS_PATH"] = str(PLAYWRIGHT_BROWSERS_ROOT)
        else:
            environment.pop("PLAYWRIGHT_BROWSERS_PATH", None)
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    return environment
