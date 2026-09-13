#requires -Version 7.0
[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port=4174,[switch]$NoBrowser)

$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath($PSScriptRoot)
$python=Join-Path $projectRoot '.venv/Scripts/python.exe'
if(-not (Test-Path -LiteralPath $python -PathType Leaf)){throw 'Missing .venv. Run runtime/setup-dev.ps1 first.'}
if(-not (Test-Path -LiteralPath (Join-Path $projectRoot 'studio/dist/client/index.html'))){throw 'Missing frontend build. Run npm ci and npm run build in studio.'}
$required=@('models/YuE2-3B/model.safetensors','models/YuE2-Vae/model.safetensors')
$missing=@($required|Where-Object{-not (Test-Path -LiteralPath (Join-Path $projectRoot $_) -PathType Leaf)})
if($missing.Count){throw "Missing model files:`n$($missing -join "`n")`nSee README.md#模型下载与放置。"}
$optional=@('models/MERT-v2-FullSong/model.safetensors','models/SheetSage2/model.safetensors')
$missingOptional=@($optional|Where-Object{-not (Test-Path -LiteralPath (Join-Path $projectRoot $_) -PathType Leaf)})
if($missingOptional.Count){Write-Warning 'Sheet transcription is unavailable until MERT-v2-FullSong and SheetSage2 are installed.'}
$env:YUE2_PYTHON=$python
$env:YUE2_PORTABLE=$null
Set-Location -LiteralPath $projectRoot
$arguments=@('--port',"$Port")
if($NoBrowser){$arguments+='--no-browser'}
& $python -X utf8 -u runtime/launch_visible.py @arguments
exit $LASTEXITCODE
