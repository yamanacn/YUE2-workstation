# YuE2 本地引擎接入契约

核查日期：2026-09-10。状态：代码与产品契约核查完成；本文件不代表已运行模型。对应官方代码 revision `a621dcc003143844927ae7d2a1295d05f356336c`，包版本 `yue2-infer 0.1.6`。核查对象是本次下载的 `vendor/yue2` 源码及官方固定 revision 页面。执行环境、模型下载与真实 GPU 验收由主流程另行记录。

## 1. 最小落地方案

保留 `http://127.0.0.1:4174/`。开发期由现有 Vite 的 **server 和 preview 都设置 `/api` 代理**到 loopback Python 服务；打包期由 Python 在 4174 同源托管 `studio/dist/client` 与 `/api/v1`。更换服务进程前先确认 4174 所属进程及启动方式，不另开 origin 让原草稿看起来丢失。站点部署能力的 `.openai`、worker 与相关构建文件维持现有约定；远程 Sites 不应伪装能直接执行这台电脑上的模型。

Python 控制服务只负责轻量验证、SQLite、调度、文件读取与事件传递。模型推理在**单独工作子进程**中运行，最多一个活动任务。控制服务无需导入 torch 即可健康响应。进程启动用参数列表、项目内独立解释器、明确 cwd 与 UTF-8 环境；不得通过 PowerShell 字符串拼接歌词或路径。

每次提交持久化不可变快照后受理；任务进程从快照文件读取参数，以 JSON Lines 向控制服务报告事件，stderr 单独存运行日志。取消通过项目任务目录中的取消标志文件或专用 IPC 传入，读取须不阻塞采样回调。服务将事件写 SQLite 后才推送前端，浏览器重连以服务端记录为事实。页面关闭不结束后台推理。

## 2. 官方真实函数与参数

以下签名来自 `src/yue2/pipeline.py:121–397`，不是推测的 HTTP SDK：

```python
YuE2Pipeline(model_dir, vae_dir, *, device="auto", memory_budget_gib=24,
             backend="torch", generation_config=None, verify_hashes=True,
             vae_core_frames=None, quantization="none", offload_ar=False,
             progress=True)

YuE2Pipeline.from_pretrained(model="m-a-p/YuE2-3B", *, vae="m-a-p/YuE2-Vae",
    revision=None, vae_revision=None, local_files_only=False,
    token=None, cache_dir=None, progress=True, **kwargs)

pipe.plan(style=None, lyrics=None, *, tags=None, request=None,
          abc_sampling=None, cancelled=None, on_token=None, **kwargs)
pipe.generate_semantic(plan, *, sampling=None, cancelled=None, on_token=None)
pipe.synthesize(semantic, *, cancelled=None)
pipe.decode(latents, *, full=False, vae=None)
pipe.effective_config(request, abc_sampling=None, semantic_sampling=None)
pipe(style=None, lyrics=None, *, tags=None, abc_sampling=None,
     semantic_sampling=None, cancelled=None, on_token=None, **kwargs)
song.save_artifacts(directory)
song.save(path)  # only .flac or .wav
pipe.close()
```

`from_pretrained` 的初始化只解析/校验文件和 tokenizer；`_load_model()` 才加载主模型。因此成功创建 pipeline 不等于模型已驻留显存或真实推理通过。

请求与配置类型位于 `yue2.protocol`，不能假设从包顶层导出：

```python
SongRequest(style: str, lyrics: str, cot="full", seed=831001,
            abc=None, cfg_scale=None, id="song")
Sampling(temperature=1.0, top_p=0.95, top_k=100,
         repetition_penalty=1.2, penalty_window=50,
         min_tokens=200, max_tokens=9000)
GenerationConfig(abc=Sampling(.7,.9,30,1.005,100,32,4096),
                 semantic=Sampling(), ode_steps=32,
                 ode_method="midpoint", context=24576,
                 version="yue2-native-v1")
```

| 当前 UI 字段 | 官方参数 | 明确语义 |
|---|---|---|
| `draft.style` / `draft.lyrics` | `style` / `lyrics` | 保留中文、标点、换行；不追加提示词 |
| `draft.title` | 不送入提示词 | 服务端作品展示名；空值分配本地标题 |
| `snapshot.seed` | `seed=int(seed_string)` | HTTP/TS 全程十进制字符串；范围 `0 <= seed < 2**63` |
| `config.cot` | `cot` | `full`、`melody`、`off`；off 跳过规划 |
| `config.cfg` | `cfg_scale` | `auto` 映射 `None`；有效 full/melody=1.0，off=1.01 |
| `temperature` / `topP` / `topK` | `semantic_sampling` 中 `temperature` / `top_p` / `top_k` | UI 这些值仅配置 semantic，不改 ABC 采样 |
| `repetitionPenalty` / `maxTokens` | `semantic_sampling.repetition_penalty` / `max_tokens` | 最大 token 是预算，不能换算为完成百分比 |
| `odeSteps` | `GenerationConfig(ode_steps=...)` | 必须在本次 pipeline 配置中固定；不是 `SongRequest` 参数 |
| `count` / `seedMode` | 服务端展开批次 | 不传入 pipeline；1/2/4 首串行，固定种子不暗中随机 |
| run ID | `id` | ASCII UUID 等安全标识，不使用中文歌曲标题 |

最小调用示意（实际工作进程用下节的观测子类）：

```python
from yue2 import YuE2Pipeline
from yue2.protocol import GenerationConfig

pipe = YuE2Pipeline.from_pretrained(
    model=model_path, vae=vae_path, local_files_only=True,
    device="cuda", backend="torch", quantization="none",
    memory_budget_gib=profile["memory_budget_gib"],
    offload_ar=profile["offload_ar"],
    generation_config=GenerationConfig(ode_steps=c["odeSteps"]),
    progress=True,
)
try:
    song = pipe(style=d["style"], lyrics=d["lyrics"], id=run_id,
                cot=c["cot"], seed=int(seed_string),
                cfg_scale=None if c["cfg"] == "auto" else c["cfg"],
                semantic_sampling={"temperature": c["temperature"],
                    "top_p": c["topP"], "top_k": c["topK"],
                    "repetition_penalty": c["repetitionPenalty"],
                    "max_tokens": c["maxTokens"]},
                cancelled=is_cancelled, on_token=on_token)
    check_cancelled()
    # Atomically commit as described below; this is not yet a succeeded task.
    song.save_artifacts(staging_dir)
finally:
    pipe.close()
```

本轮验证锁定官方默认 `backend="torch"`（CUDA graph）、`memory_budget_gib=24`、`quantization="none"`。先运行明确标记为链路短探针的 `cot="off"`、semantic maxTokens=256、ODE=8，再运行 full、semantic maxTokens=9000、ODE=32 的完整歌曲验证；探针使用独立快照，不修改用户草稿默认值。`backend="torch-eager"` 仅为诊断备选，只有实际 CUDA graph 失败并保留失败记录后，才按独立的新 profile 协调尝试，不静默更换用户配置。不能因 OOM 自动减少 maxTokens、改 seed、改 CFG、量化或换解码器。`min_tokens=200` 意味着现有 UI 最小 maxTokens=200 与 semantic 默认兼容。ABC 预算仍是 4096。

服务端校验先于受理，包括所有数字有限值、整数不接受布尔值、枚举、正文、count、seed 溢出。SDK 会检查前缀+预算不超过 24576，规划后的确切前缀还需运行时验证，不许静默截断输入。服务端用官方 `Sampling` / `SongRequest` 的规则验证最终映射，UI 校验不能充当唯一防线。

## 3. 真实进度与取消边界

### 可直接使用的公开回调

- `plan`、`generate_semantic`、`__call__` 接受 `on_token(phase, token)`，phase 为 `abc` 或 `semantic`。每个实际输出 token 恰好一次，包含结束 token，不包含 prompt、外部 ABC 和额外 CFG 分支。回调异常向外传播。来源：`sampling.py:119–125`、`pipeline.py:233–253`、官方 `test_progress_integration.py`。
- `cancelled()` 在 torch AR prefill 前及每个 token 循环开头检查；**模型加载和单次 prefill 内不能及时中止**。NAR 在每个 chunk prefill 前、每个 midpoint step 开始以及中点处检查。抛 `InterruptedError`。来源：`sampling.py:68–107`、`nar.py:170–194,245–259`。
- `pipe.synthesize` 没有公开 `on_progress` 参数；`pipe.decode` 没有公开 `on_progress` 或 `cancelled` 参数。`progress` 仅接受 bool，不能传 callback。不能写 `pipe(..., progress_callback=...)`。

### 建议的窄适配

自有 `ObservedPipeline(YuE2Pipeline)` 覆盖 `_status(self, label, *, total=None, unit=None)` context manager。它返回具备 `advance(count=1)`、`update(completed,total=None)`、`finish(status="completed")` 的 stage 对象。保留 `self.progress=True`：官方 NAR/VAE 只有该值为真时才接内部回调。不修改 vendor 数学路径、不解析终端字符串。

此 `_status` 是**私有适配点**，必须锁定 revision 并用官方 CPU 假模型测试模式验证接口；不能宣传为 SDK 公共事件协议。初始化时 `_status` 已被调用，因此 emitter/cancel 状态须在 `super().__init__` 前就绪。`from_pretrained` 中的 resolving progress 与最终 `Progress.complete` 仍写 stderr，不应误认为 JSON。

建议保留 pipeline 原生 `__call__`，确保 `SongResult` 的有效配置、权重身份与 request identity 与官方一致；使用阶段方法的薄包装维护 UI 主阶段，`_status` 提供细分 detail 和计数：

| 官方 label | UI 主阶段 / detail | 分母 |
|---|---|---|
| Verifying model files | `checking` | 未知 |
| Loading model | 当前 planning/generating_tokens/synthesizing 的加载 detail，或初次 `loading` | 未知 |
| Planning score | `planning` | 未知，实际输出 token 计数 |
| Generating song | `generating_tokens` | 未知，实际输出 token 计数 |
| Synthesizing audio | `synthesizing` | 所有 chunks × ODE steps，内部报告 |
| Loading audio decoder | `decoding`，detail=加载音频解码器 | 未知 |
| Decoding audio | `decoding` | 实际 tiled chunks |
| 保存及校验文件（应用自有） | `finalizing` | 未知 |

勿将二次模型加载从 synthesizing 强制倒退回 checking。当前 domain 没有 `loading`；可新增，也可用已有 checking/detail 表示初次加载。token 单一计数来源：若通过公开 `on_token` 计数，则 `_status.advance` 不再额外累加同一 UI 计数；若由 `_status` 计数则公开回调仅做旁路记录。

NAR 内部 `on_progress(completed,total)` 在每个 midpoint step **提交后**运行，GPU 可能尚未完成，该阶段成功须以方法返回及 CPU 数据传输完成为准。VAE `decode_tiled(..., on_progress=...)` 在每个 crop 拷贝后报告；本 pipeline `output_device="cpu"`。来源：`nar.py:172–176,193–195`、`modeling_vae.py:539–578`。

让自有 stage 的 `update` 在 **Decoding audio** 回调边界检查取消标志并抛 `InterruptedError`，即可在 tile 间取消；这属于窄适配实现的取消能力，非公开 `decode(cancelled=...)`。`decode` 的 finally 会把模型放回 CPU 并清缓存。解码器加载内、单个 tile 内和磁盘完整性校验内仍不可保证立即取消。也在每个应用阶段前后显式检查取消。

取消语义：queued 直接终止；活动任务先持久化 `cancelling` 并发信号，worker 捕获 `InterruptedError` 且退出/释放后，控制服务才确认 `cancelled`。只收到按钮点击不能当取消成功。意外退出标 `interrupted`；普通 SDK 错误标 `failed`。取消后若 worker 未及时退出，显示“等待当前计算结束”；不要把超时等同成功。需要强制终止时单独记录 forced/interrupted，不能谎称协作取消。

## 4. HTTP 与事件 schema（应用新定义，非官方 SDK）

统一前缀 `/api/v1`；只绑定 loopback。已有 origin 的 same-origin 请求通过代理访问，不需浏览器持有模型路径或密钥。变更接口检查 Origin，允许缺失 Origin 的受控本地 CLI；不要为任意跨站来源开放凭据。歌词放 JSON body。

| 请求 | 结果 |
|---|---|
| `GET /health` | 进程/依赖/文件就绪分开，GPU 数据缺失为 null，绝不仅凭进程 alive 返回 modelLoaded |
| `GET /state` | 完整服务端 runs/tracks、queuePaused、当前 eventCursor；客户端重连权威快照 |
| `POST /batches` | `{requestId,draft,resolvedSeeds?:string[],parentRunId?:string,parentTrackId?:string,attemptOf?:string}`；201 新批次，200 同幂等请求重放，409 同ID不同内容 |
| `GET /batches/by-request/{requestId}` | 提交超时后的受理查询，404 明确未找到；使用同 requestId 重发仍保证去重 |
| `POST /runs/{id}/cancel` | 202 cancelling；已终止幂等返回终态，不能取消后又成功提交作品 |
| `POST /runs/{id}/retry` | 新 requestId 的原快照/原 seed 重试；原失败记录保留；SDK配置改变不算同一次重试 |
| `PATCH /queue` | `{paused:bool}` 仅控制后续启动，落库 |
| `PATCH /tracks/{id}` | `{title?,favorite?,removed?}` 展示/收藏/软移除，不能改快照/母版 |
| `GET /tracks/{id}/audio` | 通过 track ID 查应用管理的母版，支持 Range/HEAD、正确 `audio/flac` |
| `GET /runs/{id}/artifacts` | 白名单工件元数据，不能让浏览器任意读本机路径 |
| `GET /runs/{id}/logs` | 当前任务日志，必要大小限制 |
| `GET /events?after={cursor}` | SSE，持久 event seq 作为 id，支持 Last-Event-ID 与补发；也可先用 1秒轮询 state 替代 SSE |

最小事件形状：

```ts
type EngineEvent = {
  schemaVersion: 1;
  seq: number;                  // service-global, persisted, monotonic
  at: string;                  // UTC ISO string
  type: 'run.updated' | 'track.created' | 'track.updated' | 'queue.updated' | 'engine.updated';
  runId?: string;
  data: object;                // authoritative full record or documented patch
};
type Progress = {
  phase: string;
  detail?: string;
  completed: number | null;
  total: number | null;        // null for AR, loading and finalizing
  unit: 'tokens' | 'steps' | 'chunks' | null;
  elapsedSeconds: number;      // run and stage elapsed should be distinct fields if both shown
  counting: 'emitted' | 'submitted' | 'copied' | null;
};
```

stderr 文本用于日志。worker stdout 仅协议 NDJSON；第三方意外 stdout 必须重定向到 stderr，或使用严格前缀帧并拒绝非协议行，不能把脏输出当事件。事件节流建议每 200–500ms 发送最新计数，阶段/终态立即发送；不必每 token fsync SQLite。取消读取独立于浏览器连接，SSE 断连不取消任务。

## 5. 本地持久化与原型数据兼容

建议 `runtime/studio.sqlite3` 保存 batches、immutable snapshots、runs、tracks、events、queue 状态。一次 transaction 插入幂等请求、已解析 seed、全部子任务。任务快照至少包括原始 Draft、actual seed、提交时间、runtime='local-yue2'、模型/VAE路径与revision/identity、backend/量化/offload/预算/输出根、adapter与SDK版本。已受理任务不读取当前可变设置。

文件使用 `runtime/runs/{uuid}/snapshot.json`、`worker.log`、`cancel.request`，正式工件放该 run 下的 `artifacts/`。先写全新的 `artifacts.partial/`，调用官方 `save_artifacts`、`verify_result`、soundfile 读取元数据并检验非空/有限时长/48k双声道，然后在同卷改名到不存在的 `artifacts/`。成功记录与 Track 在 SQLite 同 transaction 提交。保存失败只产生 failed run，不产生正式可播放 Track。保留 partial 诊断信息并在 UI 记录其用途；清理只能针对本任务自有临时路径。

文件改名和 DB 不是真正跨资源事务：若服务在改名之后落库之前崩溃，启动恢复需找到完整工件并核验，再按 durable commit 记录决定完成或标待恢复，不能重跑已生成结果。推荐写 `commit.json` 包含 runId、request身份、工件哈希，帮助恢复；一份母版只能对应该 run 的结果身份。

官方默认保存 `audio.flac` (PCM_24)、`semantic.npy`、`latent.npy`、`request.json`、`config.json`、计划文件与 `result.json`。音频长度取实际 `soundfile.info`/`song.audio`，不是现有硬编码 203.52。`song.truncated` 是 `{"abc": bool, "semantic": bool}`，不能用 `bool(song.truncated)` 判断，因为 dict 永远非空；使用 `any(song.truncated.values())`。可播放但触顶作为 succeeded+warning。

现有原型必须适配的点：

- `localStorage['yue2-silver-mist-v1']` 包含用户草稿、demo tracks/runs，保留原键与其已有数据，不启动静默迁移。草稿继续原 origin 保存。服务端 local runs/tracks 单独获取并展示，以 runtime/source 明确区分。
- 当前 `Snapshot.runtime` 固定 `'demo'`、`Track.audioKind` 仅 `'official-demo'|'local'`。新增 `'local-yue2'` / `'generated'` 等明确类型；`'local'` 仍指手动关联 blob 文件。不要用生成记录冒充 official-demo，也不要给服务端音频套用 blob 丢失逻辑。
- 当前 `trackFromRun()` 固定返回官方 `tonight-awake.mp3`，真实成功路径必须彻底绕过它。`recoverState()` 把所有 local audio 标 missing、把 active run 标 interrupted，只允许处理旧浏览器 demo 状态；服务端运行记录必须以 API 为准，刷新不能把活动任务标中断。
- App 的 setTimeout 演示队列不得推进真实 run。提交真实任务、取消、暂停、重试全部以 API 回读状态为准。断网留 pending requestId，禁止生成第二个 requestId 自动重试。
- 当前 App 自动保存会清除 `audioKind==='local'` URL；生成母版使用持久 `/api/v1/tracks/{id}/audio` URL，独立于 blob。原始导出文件扩展名由服务端 mime/metadata 决定，不能继续默认 mp3。
- 当前 `exportWav` 在浏览器转换为 48k/16-bit，属于显式转换。原始导出优先直接下载官方生成 FLAC，WAV 可用已核实编码器另转，并明确位深；不把 FLAC 数据命名 `.mp3`。
- theme 键与用户外观偏好原样保留。后台新作品不能自动抢播放器、替换左侧草稿或强制跳动列表。

服务重启：上次 active/cancelling 且无确证完成的任务标 interrupted；queued 保持 queued 并暂停后续启动。用户从页面刷新重连不是服务重启，不触发这套恢复。重试保留 attemptOf，重新生成保留 parentTrackId，避免当前混用 parentId 导致不可判定关系。

## 6. Windows 与资源风险的已核查依据

- 官方 README/generation guide 明确起点是 Linux、Python 3.12、BF16 NVIDIA、24GB 显存。这不证明 Windows 一定失败，但 Windows/较低可用显存运行必须以本机结果单独验收。
- 可安装性与推理能力分开：pyproject 允许 Python >=3.10，核心依赖 torch 2.10.0 等；fast 额外依赖 vllm 0.19.0 和 triton 3.6.0。`fast.py:210–241` 直接调用 `os.killpg`、POSIX 进程组并 selector 监听管道，首版原生 Windows 不选 vllm。
- `memory_budget_gib` 并不检测其他程序占用；实现按总显存限制本进程预算并预留 2GiB (`pipeline.py:159–165`)。当前剩余约 8GB 是调度输入，不能仅因为设备总量大就宣称准备好；检查 free memory 并清楚报告。不要停止其他用户程序。本核查子任务没有启动推理。
- `offload_ar=True` 是官方可记录选项，但它在 NAR prefill 之后卸载部分 AR 权重，不能当成保证 8GB 跑完整歌曲的万能开关。量化 fp8 在 NAR 前恢复，亦不能仅按 AR 权重大小保证全流程显存。
- 官方 storage 多处 `read_text()/write_text()` 没写 encoding；含中文 JSON 在 Windows 默认编码环境存在差异。工作子进程设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8` 并使用 `python -X utf8 -u`，自有文件全部 explicit UTF-8。中文文件夹用 pathlib，不把 shell locale 当编码契约。
- 模型/VAE整体 SHA 校验是大文件IO，health 路由不可每秒重算，也不能让取消 UI 在等待哈希时宣称立即释放。profile 校验结果绑定文件身份/时间，正式任务记录实际 weights identity。

## 7. 验收步骤

1. 无 GPU 的契约检查：官方 signatures、UI参数映射、seed最大值/递增溢出、重复 requestId、取消队列项、重试记录、进程崩溃恢复、结果文件校验失败、服务断连重连。实际 token/step callbacks 用官方测试的 CPU fake patterns 验证，明确不等于音质与GPU通过。
2. 先记录原 origin localStorage 值；启动服务/代理后确认草稿文字、样例收藏/移除和主题未丢失。health 明确显示依赖/文件/设备/加载状态。
3. 获准资源条件满足后，使用新建完整中文短歌词、固定 seed、明确预算与设置，记录 submitted snapshot，开始一首真实歌曲。观察 token 增长/真实阶段切换，修改草稿不改变正在运行快照。
4. 真实输出须存在 `audio.flac`、有效 result manifest、实际时长/48k/双声道，并完成试听；记录日志、耗时、显存、truncated flags。若只完成短截断 smoke，明确叫链路烟测，不宣称整首成功。
5. 页面直接试听与下载原始 FLAC；拖动播放进度验证 Range。生成结束不自动播放；检验下载文件 SHA 与母版一致，WAV转换单独校验。
6. 再测一个真实运行取消边界，确保界面先 cancelling、worker退出/释放后才 cancelled。解码单 tile 等待是已知边界；不编造完成百分比。
7. 服务重启确认作品仍可播放、等待队列暂停、意外中断保留；新增作品收藏/重命名/软移除重启持久。旧 demo 与真实作品来源在详情/导出始终清楚。

## 8. 固定来源

- [官方固定代码树](https://github.com/multimodal-art-projection/YuE/tree/a621dcc003143844927ae7d2a1295d05f356336c)
- [pipeline.py](https://github.com/multimodal-art-projection/YuE/blob/a621dcc003143844927ae7d2a1295d05f356336c/src/yue2/pipeline.py)
- [protocol.py](https://github.com/multimodal-art-projection/YuE/blob/a621dcc003143844927ae7d2a1295d05f356336c/src/yue2/protocol.py)
- [sampling.py](https://github.com/multimodal-art-projection/YuE/blob/a621dcc003143844927ae7d2a1295d05f356336c/src/yue2/sampling.py)
- [nar.py](https://github.com/multimodal-art-projection/YuE/blob/a621dcc003143844927ae7d2a1295d05f356336c/src/yue2/nar.py)
- [modeling_vae.py](https://github.com/multimodal-art-projection/YuE/blob/a621dcc003143844927ae7d2a1295d05f356336c/src/yue2/modeling_vae.py)
- [storage.py](https://github.com/multimodal-art-projection/YuE/blob/a621dcc003143844927ae7d2a1295d05f356336c/src/yue2/storage.py)
- [generation guide](https://github.com/multimodal-art-projection/YuE/blob/a621dcc003143844927ae7d2a1295d05f356336c/docs/generation.md)
- [官方进度契约测试](https://github.com/multimodal-art-projection/YuE/blob/a621dcc003143844927ae7d2a1295d05f356336c/tests/test_progress_integration.py)

项目设计依据：`01_YuE2_Music_Studio_PRD.md` FR-01–13、6.1–6.3；`02_YuE2_Music_Studio_组件与交互规范.md` C08/C09、R03/R08、S01/S03/S07；当前实现 `studio/src/domain.ts`、`audio.ts`、`App.tsx`。上述 API/数据库/适配层是建议契约，未在本只读核查子任务实施。
