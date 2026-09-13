# 已锁定的本机集成决策

## 运行

- 已实测的本机默认：torch-eager，memory_budget_gib=24，quantization=none，offload_ar=false。不使用默认torch CUDA graph：Windows wheel强制Flash算子失败有实测记录。
- Python为项目 .venv/Scripts/python.exe。代码/权重revision沿用 runtime/setup-report.md。
- 控制服务与GPU子进程分离；每任务新子进程，结束后释放本任务GPU；一次只运行一个。
- 数据库/正式任务写入 data/studio.sqlite3、data/runs/。runtime/保存安装和验证记录，不混同可清理缓存与正式作品。
- 初始服务测试监听127.0.0.1:8767；最终由服务同源托管前端到4174。生产端口由主Agent验收后切换。开发Vite可代理/api。

## HTTP契约

以 interface-research.md 的 /api/v1 路由为准。先用1秒轮询 GET /state（支持ETag/seq可选），SSE非首个验收的硬依赖。

GET /health 返回至少：
```
{ok, status:'ready'|'busy'|'unavailable'|'resource_wait',
 dependenciesReady, modelsReady, modelLoaded, workerActive,
 profile:{backend, memoryBudgetGiB, modelName, decoderName, modelRevision, vaeRevision},
 device:{name,totalMiB,freeMiB}|null, reason?:string}
```
服务在线、文件齐备、worker活动和模型已加载分别报告。启动任务的资源门槛要真实检查。运行期间因本任务占用造成free下降，不得把服务误报为离线。

GET /state 返回：
```
{runs:LiveRun[], tracks:LiveTrack[], queuePaused:boolean, eventCursor:number}
```

Run与Track以现有studio/src/domain.ts为基础，保持camelCase字段：
- Run：id、batchId、snapshot、state、stageStarted(epoch ms)、created(epoch ms)、elapsed(seconds)、error?、parentId?、attemptOf?；增加progress {phase,detail?,completed,total,unit,elapsedSeconds}。
- snapshot：draft、seed(十进制字符串)、submittedAt(ISO)、runtime:'local-yue2'、requestId；可附固定profile、model identities。
- Track：id、title、version、style、lyrics、artwork（默认/assets/opal-glass.webp）、duration(实际秒)、created(ISO)、favorite、removed、runId、snapshot、audioUrl（/api/v1/tracks/{id}/audio）、audioKind:'generated'、audioFormat:'flac'、sampleRate、channels、subtype、missing、warning?、sourceTitle（本机生成标识）。
- state仍采用现有queued/checking/planning/generating_tokens/synthesizing/decoding/finalizing/cancelling/cancelled/succeeded/failed/interrupted；模型加载用progress.detail，不凭前端计时猜。
- 不返回音频之外任意路径文件；工件访问只允许任务目录白名单。

POST /batches 返回 {requestId,batchId,runs:LiveRun[],replayed:boolean}，按requestId幂等。POST /runs/id/retry 同样返回新批次。错误用 {detail:string, code?:string}，不可把失败包成成功空数组。

## 前端

- 同一4174 origin，原草稿、主题和演示记录保留原localStorage键，不自动迁移/覆盖。
- live runs/tracks 来自服务端并独立维护；模式live/demo/offline明确。API正常时初次默认live，用户明确选择demo后不被轮询强制切回。
- 用户刷新不会把服务端活动任务标为interrupted；只有服务重启恢复流程做此判断。
- 真实状态不走demo setTimeout或trackFromRun。类型新增local-yue2/generated，原local仍指浏览器文件关联。
- 播放、重命名/收藏/软移除/恢复、取消、重试、暂停必须调用真实接口并读回。
- 原格式导出按audioFormat/mime选FLAC，绝不把FLAC命名为MP3。
- 模式和任务来源清楚；新增真实结果不抢草稿、滚动或播放。长seed不可转Number。

## 集成样例

可将已验证完整产物 runtime/validation/20260910T101357909707Z-full-torch-eager/artifacts 通过内部导入命令复制校验入data并建真实记录。保留原验证目录，明确为本机验证歌曲。不是把官方demo数据改标为真实。

验收时可从该真实作品的“再生成一版”发起单个真实任务，验证浏览器到worker闭环而不覆盖用户当前草稿。另用短请求验证真实取消。音质与歌词准确性不从数值检查推断。
