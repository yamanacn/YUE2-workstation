#requires -Version 7.0
[CmdletBinding()]
param([switch]$VerifyOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$manifestPath = Join-Path $projectRoot 'runtime/portable-runtime.json'
$pythonPath = Join-Path $projectRoot 'runtime/python312/python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw '未找到 YuE2 内置 Python 3.12 运行时；请先运行 runtime/build-portable.ps1。'
}
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
    throw '未找到便携运行时清单；请先运行 runtime/build-portable.ps1。'
}
$probe = & $pythonPath -s -X utf8 -c "import importlib.metadata as m,sys,torch; print(sys.version.split()[0]); print(torch.__version__); print(m.version('yue2-infer'))" 2>&1
if ($LASTEXITCODE) { $probe | Write-Host; throw '内置 Python 运行时探针失败。' }
Write-Host 'YuE2 内置 Python 3.12 运行时校验通过。'
Write-Host ($probe -join [Environment]::NewLine)
if ($VerifyOnly) { exit 0 }
Write-Host '这是完整便携运行时，无需安装 Python、uv、Git 或外部依赖。请直接运行根目录的 快速启动YuE2.cmd。'
