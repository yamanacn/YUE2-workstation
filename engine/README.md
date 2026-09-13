# YuE2 本地控制服务

使用项目内 `runtime/python312/python.exe`（Python 3.12.12）。服务默认绑定 `127.0.0.1:8767`；最终 `--port 4174` 同时托管 `studio/dist/client`。同一 data 目录只允许一个服务，单服务串行运行独立 GPU 子进程。

```powershell
& 'E:/项目/YuE2/runtime/python312/python.exe' -X utf8 -u -m engine.service --port 8767
# 正式入口，由主流程完成前端验收后切换
& 'E:/项目/YuE2/runtime/python312/python.exe' -X utf8 -u -m engine.service --port 4174
```

命令工作目录为 `E:/项目/YuE2`。可用 `--data-dir` 指定隔离数据目录。正式数据默认 `data/studio.sqlite3`、`data/runs/<uuid>/`。每次受理保存不可变草稿/实际种子/profile/模型身份；每任务 worker 从 snapshot.json 读取。模型 profile 固定 `torch-eager / 24 GiB / none / offload=false`，不自动降级。

安全停止使用 `POST /api/v1/shutdown`，JSON body `{}`。存在任何排队或活动任务返回 409；空闲返回 202 后正常停止。直接结束服务时会请求当前任务取消，等待计算边界；25 秒后仍未退出会终止 worker，记录异常中断。下次启动对无完整提交证据的活动任务标记 interrupted，并暂停后续队列。完整 artifacts + commit.json 可重新核验后恢复成功，不重复推理。

## 导入已验证本机工件

```powershell
& 'E:/项目/YuE2/runtime/python312/python.exe' -X utf8 -m engine.service import-artifacts 'E:/项目/YuE2/runtime/validation/20260910T101357909707Z-full-torch-eager/artifacts' --title '平常的一天 · 本机验证'
```

导入复制完整官方工件，验证 result manifest、request/config/weights identity、文件 hash 和 FLAC 全样本；通过后同卷改名并提交作品。源目录保留，导入来源另写 import-source.json。导入按结果 identity 幂等，导入后队列暂停，须在界面明确恢复后启动新任务。

## HTTP 补充

基础路由与字段遵循 `integration-decisions.md`。首版使用一秒 `/api/v1/state` 轮询，不实现 SSE。写接口必须 `Content-Type: application/json`，Origin 允许本机同源及 4174/5173/8767 开发代理。

- health 额外包含 `service:'yue2-studio'`、`apiVersion:1`、`projectRoot`、`pid`。`modelLoaded` 只由 worker 实际模型加载报告决定；孤儿 worker 仍持锁时为 `null`，表示未知。运行时 status=busy；空闲显存不足为 resource_wait，仍可排队。
- cancel 返回完整 Run：活动 202/cancelling，queued 200/cancelled。活动取消最终确认在 worker 退出后发生。
- retry body `{requestId}`，新批次单首，保留原种子与 attemptOf；POST batches 新批次 201，幂等重放 200，同 ID 不同 body 为 409。
- PATCH queue 返回 `{paused,queuePaused}`；PATCH tracks 返回完整 Track。
- logs 返回 `{runId,log,truncated}`，最多最后 128 KiB；artifacts 只返回白名单元数据 `{runId,artifacts:[{name,bytes,sha256}]}`。
- `/tracks/{id}/audio` 提供原始 PCM24 FLAC、Range/HEAD；路径只由 trackId 映射，不能传本地文件路径。

## 验证

```powershell
& runtime/python312/python.exe -X utf8 -m unittest engine.test_service -v
& runtime/python312/python.exe -X utf8 -m engine.check_http --base http://127.0.0.1:8767
```

CPU 测试 worker 必须由测试代码显式 test_mode=True 且隔离数据目录启动；HTTP 没有选择 fake worker 的入口。CPU 测试证明控制流程，不证明 GPU 推理或音质。引擎真实进度由官方私有 `_status` 窄适配读取，执行前检查固定 vendor revision 和代码洁净；不修改官方数学路径。

新增依赖锁见 `requirements-service.txt`，测试 HTTP 客户端见 `requirements-test.txt`。引擎依赖沿用 runtime/setup-report.md 的已验收环境。
