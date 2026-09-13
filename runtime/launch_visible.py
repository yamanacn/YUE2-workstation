"""Launch the YuE2 service in the current console using the bundled Python."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.runtime_paths import runtime_environment


def health(url: str):
    try:
        with urlopen(url + "/api/v1/health", timeout=2) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def _write_process_record(process: subprocess.Popen, port: int, url: str):
    """Write the same guarded record used by the PowerShell stop script."""
    service = psutil.Process(process.pid)
    launcher = psutil.Process(os.getpid())
    record = {
        "projectRoot": str(ROOT),
        "pid": process.pid,
        "port": port,
        "executablePath": service.exe(),
        "commandLine": subprocess.list2cmdline(service.cmdline()),
        "creationTimeUtc": datetime.fromtimestamp(service.create_time(), timezone.utc).isoformat(),
        "launcherPid": launcher.pid,
        "launcherCreationTimeUtc": datetime.fromtimestamp(launcher.create_time(), timezone.utc).isoformat(),
        "url": url,
    }
    state_dir = ROOT / "runtime" / "launcher"
    state_dir.mkdir(parents=True, exist_ok=True)
    target = state_dir / f"service-{port}.json"
    temporary = target.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)
    return record


def _clear_process_record(record):
    if not record:
        return
    target = ROOT / "runtime" / "launcher" / f"service-{record['port']}.json"
    try:
        current = json.loads(target.read_text(encoding="utf-8"))
        if current.get("pid") == record["pid"] and current.get("creationTimeUtc") == record["creationTimeUtc"]:
            target.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError):
        pass


def _wait_for_service_exit(process: subprocess.Popen, url: str) -> int:
    """Let Uvicorn shut down, then reap a process stuck after its port closes."""
    offline_since = None
    while process.poll() is None:
        if health(url):
            offline_since = None
        else:
            offline_since = offline_since or time.monotonic()
            if time.monotonic() - offline_since >= 8:
                process.terminate()
                try:
                    return process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return process.wait()
        time.sleep(0.5)
    return process.returncode or 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", "-Port", type=int, default=4174)
    parser.add_argument("--no-browser", "-NoBrowser", action="store_true")
    parser.add_argument("--data-dir", "-DataDirectory", type=Path)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("port must be between 1024 and 65535")
    url = f"http://127.0.0.1:{args.port}"
    if health(url):
        print(f"YuE2 已在运行：{url}", flush=True)
        if not args.no_browser and os.name == "nt":
            os.startfile(url)  # type: ignore[attr-defined]
        return 0

    environment = runtime_environment()
    command = [sys.executable, "-X", "utf8", "-u", "-m", "engine.service", "--port", str(args.port)]
    if args.data_dir:
        command.extend(["--data-dir", str(args.data_dir.resolve())])
    process = subprocess.Popen(command, cwd=ROOT, env=environment)
    record = None
    try:
        for _ in range(45):
            if process.poll() is not None:
                return process.returncode or 1
            if health(url):
                record = _write_process_record(process, args.port, url)
                print(f"YuE2 已启动：{url}", flush=True)
                print("后端正在当前终端运行。关闭此终端即可停止 YuE2。", flush=True)
                print("也可以使用 Ctrl+C 停止服务。", flush=True)
                if not args.no_browser and os.name == "nt":
                    os.startfile(url)  # type: ignore[attr-defined]
                return _wait_for_service_exit(process, url)
            time.sleep(0.4)
        print("服务尚未就绪；请查看上方后端日志。", file=sys.stderr, flush=True)
        process.terminate()
        return process.wait(timeout=10)
    except KeyboardInterrupt:
        process.terminate()
        try:
            return process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            return process.wait()
    finally:
        _clear_process_record(record)


if __name__ == "__main__":
    raise SystemExit(main())
