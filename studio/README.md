# YuE2 Music Studio — 银白 / 沉浸黑

采用用户选定的银白方案及后续提供的 Suno 黑色参考实现的本地交互界面。顶部太阳/月亮按钮或设置中的界面偏好可切换主题，并自动记住选择。

## 本地预览

开发：`npm run dev -- --host 127.0.0.1 --port 5174`

开发期 `/api` 代理到 `http://127.0.0.1:8767`；Vite dev 和 preview 均已配置。正式本地模式由项目 Python 服务在 `127.0.0.1:4174` 同源托管 `dist/client` 与 `/api/v1`。服务启停与真实推理验收由项目根目录流程负责。

## 当前能力

- 标题、歌词、风格与参数输入；草稿自动保存。
- 真实本机队列：服务端轮询、幂等提交、取消确认、暂停后续任务、保留种子重试。
- 独立保留演示队列，切换模式后原演示数据继续可用。
- 作品搜索、收藏、排序、展开、重命名、复用、移除与撤销。
- 本机生成 FLAC 与官方示例分开标识；播放、波形、进度、音量、静音、原格式下载和 WAV 转换。
- 本地音频重新定位；键盘与减少动态效果支持。

前端已实现真实 API 接入。服务可达时首次默认“本机生成”；断连为 offline 并保留上次已确认快照。主动选择演示后，健康轮询不会强行切换模式。控制服务、依赖、模型文件、GPU 工作进程和模型加载分别显示。完整浏览器到真实 GPU 的验收以项目根目录记录为准。

原 `yue2-silver-mist-v1` 继续保存草稿和演示记录，主题键保持原样。真实作品与任务来自服务端，绝不保存到该演示数据库。`yue2-workspace-mode-v1` 仅保存模式偏好；`yue2-live-pending-v1` 保存尚未确认的提交及 requestId。提交响应丢失或刷新后先查询受理情况，再使用相同请求继续提交。

## 检查

`npx tsc --noEmit`

`node --experimental-strip-types --test tests/state.test.mjs tests/engine-api.test.mjs`

`npm run build`

视觉基准：`../design-review/selected-silver-mist.png`。记录：[design-qa.md](design-qa.md)。

## 素材

- 乳白玻璃、沙丘、雪岭、石纹与背景由内置 ImageGen 单独生成，并压缩为 WebP。源图位于 `../design-review/asset-sources/`。
- 字体：本地打包 Noto Serif SC Variable（OFL）；系统无衬线回退。
- 图标：Phosphor Icons。
- 试听：YuE2 官方《今晚不眠》示例（早期检查点）。原始来源、时长与 SHA256 见 `public/audio/source.json`。演示作品的标题与歌词不对应这段音频。

## 文件结构

- `src/App.tsx`：工作台、表单、真实操作与独立演示调度。
- `src/engine-api.ts`：相对路径 API、错误传播与提交幂等恢复。
- `src/use-engine.ts`：一秒间隔轮询、服务端权威状态与模式偏好。
- `src/components.tsx`：播放器、波形、抽屉和作品菜单。
- `src/domain.ts`：类型、请求快照、种子和状态转换。
- `src/audio.ts`：单一媒体状态、真实波形与 WAV 编码。
- `src/styles.css`：选定方案的材质、布局与响应式样式。
- `qa/`：视觉对照和状态证据。

官方模型与 Python worker 由项目 `engine/` 实现。本目录保留 Product Design 的构建与托管模板文件，尚未公开部署。
