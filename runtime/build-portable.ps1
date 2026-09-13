# Build a project-local Python 3.12 runtime from the already verified local env.
[CmdletBinding()]
param([switch]$Force,[switch]$VerifyOnly)

$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$runtimeRoot=[IO.Path]::GetFullPath($PSScriptRoot)
$destination=[IO.Path]::GetFullPath((Join-Path $runtimeRoot 'python312'))

function Read-VenvHome([string]$Venv){
    $cfg=Join-Path $Venv 'pyvenv.cfg'
    if(-not (Test-Path -LiteralPath $cfg -PathType Leaf)){throw "找不到虚拟环境配置：$cfg"}
    $line=Get-Content -LiteralPath $cfg -Encoding UTF8 | Where-Object {$_ -match '^home\s*=\s*(.+)$'} | Select-Object -First 1
    if(-not $line){throw "无法读取 Python 基础目录：$cfg"}
    return [IO.Path]::GetFullPath($Matches[1].Trim())
}

function Assert-InRuntime([string]$Path){
    $resolved=[IO.Path]::GetFullPath($Path)
    if(-not $resolved.StartsWith($runtimeRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){
        throw "拒绝操作运行时目录之外的路径：$resolved"
    }
}

function Copy-Tree([string]$Source,[string]$Target,[string]$Label){
    if(-not (Test-Path -LiteralPath $Source -PathType Container)){throw "缺少$Label：$Source"}
    New-Item -ItemType Directory -Path $Target -Force | Out-Null
    & robocopy $Source $Target /E /XJ /R:1 /W:1 /XD __pycache__ /NFL /NDL /NJH /NJS /NP | Out-Null
    if($LASTEXITCODE -gt 7){throw "$Label 复制失败（robocopy $LASTEXITCODE）"}
}

function Invoke-Probe([string]$Python){
    $probe=@'
import importlib.metadata as md
import json, platform, sys
import imageio_ffmpeg, numpy, scipy, soundfile, torch, torchaudio, transformers
import playwright
from yue2 import YuE2Pipeline
from transformers import AutoModel
print(json.dumps({
  "python": sys.version.split()[0],
  "platform": platform.platform(),
  "torch": torch.__version__,
  "cuda": torch.version.cuda,
  "cudaAvailable": torch.cuda.is_available(),
  "torchaudio": torchaudio.__version__,
  "transformers": transformers.__version__,
  "numpy": numpy.__version__,
  "scipy": scipy.__version__,
  "soundfile": soundfile.__version__,
  "ffmpeg": imageio_ffmpeg.get_ffmpeg_version(),
  "playwright": md.version("playwright"),
  "yue2": md.version("yue2-infer"),
}, ensure_ascii=False))
'@
    $output=& $Python -s -X utf8 -c $probe 2>&1
    if($LASTEXITCODE){$output | Write-Host;throw "便携 Python 导入探针失败（退出码 $LASTEXITCODE）"}
    return ($output -join "`n") | ConvertFrom-Json
}

$mainVenv=Join-Path $projectRoot '.venv'
$mainBase=Read-VenvHome $mainVenv
$mainBasePython=Join-Path $mainBase 'python.exe'
$mainPackages=Join-Path $mainVenv 'Lib/site-packages'
if(-not (Test-Path -LiteralPath $mainBasePython -PathType Leaf)){throw "找不到 Python 3.12 基础解释器：$mainBasePython"}
if(-not (Test-Path -LiteralPath $mainPackages -PathType Container)){throw "找不到主环境 site-packages：$mainPackages"}

if($VerifyOnly){
    $python=Join-Path $destination 'python.exe'
    if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw "便携 Python 不存在：$python"}
    $probe=Invoke-Probe $python
    $probe | ConvertTo-Json -Compress
    exit 0
}

if(Test-Path -LiteralPath $destination){
    if(-not $Force){throw "便携运行时已存在；如需重建请追加 -Force：$destination"}
    Assert-InRuntime $destination
    Remove-Item -LiteralPath $destination -Recurse -Force
}
New-Item -ItemType Directory -Path $destination -Force | Out-Null

Copy-Tree $mainBase $destination 'Python 3.12 基础运行时'
$portablePackages=Join-Path $destination 'Lib/site-packages'
Copy-Tree $mainPackages $portablePackages 'YuE2 与控制服务依赖'

# Editable installs and virtualenv hooks contain machine-specific paths.
Get-ChildItem -LiteralPath $portablePackages -Filter '*.pth' -File -ErrorAction SilentlyContinue | Remove-Item -Force
$yueSource=Join-Path $projectRoot 'vendor/yue2/src/yue2'
$yueDestination=Join-Path $portablePackages 'yue2'
if(Test-Path -LiteralPath $yueDestination){Assert-InRuntime $yueDestination;Remove-Item -LiteralPath $yueDestination -Recurse -Force}
Copy-Tree $yueSource $yueDestination 'YuE2 推理包源码'
$distInfo=Get-ChildItem -LiteralPath $mainPackages -Directory -Filter 'yue2_infer-*.dist-info' | Select-Object -First 1
if($distInfo){Copy-Tree $distInfo.FullName (Join-Path $portablePackages $distInfo.Name) 'YuE2 包元数据'}
$directUrl=Join-Path $portablePackages 'yue2_infer-0.1.6.dist-info/direct_url.json'
if(Test-Path -LiteralPath $directUrl){'{"url":"vendor/yue2"}' | Set-Content -LiteralPath $directUrl -Encoding UTF8}

$python=Join-Path $destination 'python.exe'
$probe=Invoke-Probe $python
$manifest=[ordered]@{
    schema=1
    builtAt=[DateTime]::UtcNow.ToString('O')
    pythonExe='runtime/python312/python.exe'
    pythonVersion=$probe.python
    torch=$probe.torch
    cuda=$probe.cuda
    torchaudio=$probe.torchaudio
    transformers=$probe.transformers
    numpy=$probe.numpy
    scipy=$probe.scipy
    soundfile=$probe.soundfile
    ffmpeg=$probe.ffmpeg
    playwright=$probe.playwright
    yue2=$probe.yue2
    sourceEnvironment='copied from the verified build environment; no external runtime path is required'
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runtimeRoot 'portable-runtime.json') -Encoding UTF8
$manifest | ConvertTo-Json -Compress
