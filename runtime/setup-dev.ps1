#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$PythonPath,
    [switch]$DownloadModels,
    [switch]$InstallBrowser,
    [switch]$BuildFrontend
)

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
Set-Location -LiteralPath $projectRoot

if (-not $PythonPath) {
    $launcher = Get-Command py -ErrorAction SilentlyContinue
    if ($launcher) {
        & $launcher.Source -3.12 -c 'import sys; print(sys.version)'
        if ($LASTEXITCODE) { throw 'Python 3.12 is not available through py.exe.' }
        & $launcher.Source -3.12 -m venv .venv
    } else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) { throw 'Python 3.12 was not found. Install it or pass -PythonPath.' }
        $version = & $python.Source -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
        if ($version -ne '3.12') { throw "Expected Python 3.12, found $version. Pass -PythonPath to a 3.12 executable." }
        & $python.Source -m venv .venv
    }
} else {
    $resolved = [IO.Path]::GetFullPath($PythonPath, $projectRoot)
    & $resolved -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
    if ($LASTEXITCODE) { throw 'The selected interpreter is not Python 3.12.' }
    & $resolved -m venv .venv
}
if ($LASTEXITCODE) { throw 'Could not create .venv.' }

$venvPython = Join-Path $projectRoot '.venv/Scripts/python.exe'
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install torch==2.10.0+cu130 torchaudio==2.10.0+cu130 --index-url https://download.pytorch.org/whl/cu130
& $venvPython -m pip install -r engine/requirements-dev.txt
& $venvPython -m pip install --no-deps -e vendor/yue2
if ($LASTEXITCODE) { throw 'Python dependency installation failed.' }

if ($InstallBrowser) {
    & $venvPython -m playwright install chromium
    if ($LASTEXITCODE) { throw 'Playwright Chromium installation failed.' }
}
if ($DownloadModels) {
    & $venvPython runtime/download_all_models.py
    if ($LASTEXITCODE) { throw 'Model download failed.' }
}
if ($BuildFrontend) {
    if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw 'npm was not found.' }
    Push-Location studio
    try { npm ci; if ($LASTEXITCODE) { throw 'npm ci failed.' }; npm run build; if ($LASTEXITCODE) { throw 'Frontend build failed.' } }
    finally { Pop-Location }
}

Write-Host 'Development environment is ready.'
Write-Host 'Next: pwsh -File ./启动YuE2-dev.ps1'
