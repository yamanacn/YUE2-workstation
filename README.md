# YuE2 Workstation

[English](README_EN.md) · [官方 YuE2-3B 模型](https://huggingface.co/m-a-p/YuE2-3B/tree/main) · [官方 YuE2 项目](https://github.com/multimodal-art-projection/YuE)

面向 Windows 的本地 YuE2 音乐工作站源码。提供歌词与风格生成、快速/高级创作、ABC 乐谱编辑、参考音频转谱、纯音乐处理、作品队列、导出，以及可选的 Qwen/DeepSeek AI 助手。

> 本仓库面向开发者，只包含源代码、构建脚本和文档。模型权重、Python 虚拟环境、内置 Python、浏览器运行时、用户作品和 API Key 均不在 Git 仓库中。

## 主要功能

- 使用歌词、风格描述和可选 ABC 乐谱生成完整歌曲
- 快速创作与高级创作相互隔离
- 参考音频转为可编辑 ABC，支持旋律或旋律与和弦
- 纯音乐模式会把 Vocal 旋律安全转换到器乐声部
- 本地任务队列、取消、重试、恢复、播放和 FLAC/WAV 导出
- AI 风格、歌词和 ABC 助手，支持 Qwen3.8-Flash 与 DeepSeek-Flash

## 环境要求

- Windows 10/11 64 位
- NVIDIA GPU，支持 BF16；建议 24 GB 显存
- 建议至少 24 GB 系统内存和 25 GB 可用磁盘空间
- Python 3.12 x64
- PowerShell 7
- Node.js 20+ 与 npm
- Git

官方 YuE2 文档以 Linux、Python 3.10+ 和 24 GB NVIDIA GPU 为基准。本项目的已验证环境为 Python 3.12.12、PyTorch 2.10、CUDA 13.0。

## 开发环境安装

```powershell
git clone https://github.com/yamanacn/YUE2-workstation.git
cd YUE2-workstation
pwsh -File runtime/setup-dev.ps1 -DownloadModels -InstallBrowser -BuildFrontend
```

只安装代码依赖时运行：

```powershell
pwsh -File runtime/setup-dev.ps1
```

## 模型下载与放置

基础生成必须准备：

| 本地目录 | 官方模型库 | 用途 |
|---|---|---|
| `models/YuE2-3B/` | [m-a-p/YuE2-3B](https://huggingface.co/m-a-p/YuE2-3B/tree/main) | 乐谱规划与音乐语义生成 |
| `models/YuE2-Vae/` | [m-a-p/YuE2-Vae](https://huggingface.co/m-a-p/YuE2-Vae/tree/main) | 48 kHz 立体声音频解码 |

参考音频转谱还需要：

| 本地目录 | 官方模型库 | 用途 |
|---|---|---|
| `models/MERT-v2-FullSong/` | [m-a-p/MERT-v2-FullSong](https://huggingface.co/m-a-p/MERT-v2-FullSong/tree/main) | 音频特征编码 |
| `models/SheetSage2/` | [m-a-p/SheetSage2](https://huggingface.co/m-a-p/SheetSage2/tree/main) | 音频转 ABC/MIDI/五线谱 |

推荐下载固定 revision：

```powershell
.\.venv\Scripts\python.exe runtime\download_all_models.py
```

也可以使用 Hugging Face CLI：

```powershell
hf download m-a-p/YuE2-3B --local-dir models/YuE2-3B
hf download m-a-p/YuE2-Vae --local-dir models/YuE2-Vae
hf download m-a-p/MERT-v2-FullSong --local-dir models/MERT-v2-FullSong
hf download m-a-p/SheetSage2 --local-dir models/SheetSage2
```

正确目录结构：

```text
models/
├─ YuE2-3B/
│  ├─ config.json
│  ├─ generation_config.json
│  ├─ model.safetensors
│  ├─ qwen.tiktoken
│  ├─ weights_manifest.json
│  └─ yue2_generation_config.json
├─ YuE2-Vae/
│  ├─ config.json
│  ├─ model.safetensors
│  └─ weights_manifest.json
├─ MERT-v2-FullSong/
│  ├─ config.json
│  └─ model.safetensors
└─ SheetSage2/
   ├─ config.json
   ├─ model.safetensors
   └─ 模型库中的 Python、处理器和排版资源
```

不要多套一层目录。正确位置是 `models/YuE2-3B/model.safetensors`，不是 `models/YuE2-3B/YuE2-3B/model.safetensors`。

## 构建与启动

```powershell
cd studio
npm ci
npm run build
cd ..
pwsh -File .\启动YuE2-dev.ps1
```

也可以双击 `启动开发环境.cmd`。终端必须保持打开；关闭终端或按 `Ctrl+C` 会停止本地服务。默认地址：<http://127.0.0.1:4174/>。

源码仓库中的 快速启动YuE2.cmd 和 启动YuE2.ps1 是给完整便携包使用的发布入口；开发者请使用 启动开发环境.cmd 或 启动YuE2-dev.ps1。

## AI 助手与隐私

Qwen3.8-Flash 和 DeepSeek-Flash 是可选功能。密钥可在任意风格、歌词或 ABC 助手窗口配置，按 provider 全局生效，只保存在本机 `data/assistant-config.json`。只有提交 AI Chat 时，对应文本才会传给所选服务商；本地音乐生成不依赖这些 API。

## 本地数据

- 数据库：`data/studio.sqlite3`
- 生成工件和音频：`data/runs/<runId>/`
- 缓存：`runtime/cache/`
- 草稿：本地地址对应的浏览器本地存储

这些目录均被 Git 忽略。备份作品时，请在服务停止后备份整个 `data/`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest engine.test_chat engine.test_reference_files engine.test_instrumental engine.test_performance
cd studio
npx tsc --noEmit
npm run build
npm run test:sites
```

## 许可证与归属

- 本项目源码：Apache License 2.0，见 [LICENSE](LICENSE)
- YuE2 推理源码：Apache License 2.0，见 [vendor/yue2/LICENSE](vendor/yue2/LICENSE)
- YuE2 模型权重：CC BY-NC 4.0，见 [MODEL_LICENSE.md](MODEL_LICENSE.md)
- 第三方实现与依赖：见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)

模型权重不包含在本仓库中。代码许可证不会覆盖模型权重许可证。

## 上游项目

- YuE2：<https://github.com/multimodal-art-projection/YuE>
- YuE2-3B：<https://huggingface.co/m-a-p/YuE2-3B/tree/main>
- 项目页：<https://map-yue2.github.io/>

本项目是基于 YuE2 构建的独立工作站，不代表上游官方桌面应用。


