#requires -Version 7.0
[CmdletBinding()]
param(
    [ValidateRange(1024,65535)][int]$Port = 4174,
    [switch]$NoBrowser,
    [switch]$ValidateOnly,
    [switch]$VisibleTerminal,
    [string]$DataDirectory
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$pythonPath = Join-Path $projectRoot 'runtime/python312/python.exe'
$env:YUE2_PORTABLE = '1'
$env:PYTHONNOUSERSITE = '1'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONPATH = $null
$env:PYTHONHOME = $null
$env:YUE2_CACHE = Join-Path $projectRoot 'runtime/cache/yue2'
$env:HF_HOME = Join-Path $projectRoot 'runtime/cache/huggingface'
$env:HF_HUB_CACHE = Join-Path $projectRoot 'runtime/cache/huggingface/hub'
$env:HF_MODULES_CACHE = Join-Path $projectRoot 'runtime/cache/huggingface/modules'
$env:TRANSFORMERS_CACHE = Join-Path $projectRoot 'runtime/cache/huggingface/transformers'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $projectRoot 'runtime/playwright-browsers'
$baseUrl = "http://127.0.0.1:$Port"
$stateDir = Join-Path $projectRoot 'runtime/launcher'
$statePath = Join-Path $stateDir "service-$Port.json"

function Get-ServiceHealth {
    try { return Invoke-RestMethod "$baseUrl/api/v1/health" -TimeoutSec 2 } catch { return $null }
}
function Get-Listener {
    return @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}
function Get-OwnedProcess([int]$ProcessId) {
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $info -or
        $info.CommandLine -notmatch '(?i)(?:^|\s)-m\s+engine\.service(?:\s|$)' -or
        $info.CommandLine -notmatch "(?:^|\s)--port(?:\s+|=)$Port(?:\s|`$)") { return $null }
    if ($info.ExecutablePath -ine $pythonPath) { return $null }
    return $info
}
function Save-ProcessRecord($Info) {
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    $record = @{projectRoot=$projectRoot; pid=[int]$Info.ProcessId; port=$Port;
        executablePath=$Info.ExecutablePath; commandLine=$Info.CommandLine;
        creationTimeUtc=$Info.CreationDate.ToUniversalTime().ToString('O'); url=$baseUrl}
    $launcher = if ($Info.ExecutablePath -ieq $pythonPath) { $Info } else {
        Get-CimInstance Win32_Process -Filter "ProcessId = $($Info.ParentProcessId)"
    }
    $record.launcherPid = [int]$launcher.ProcessId
    $record.launcherCreationTimeUtc = $launcher.CreationDate.ToUniversalTime().ToString('O')
    $temporary = "$statePath.tmp"
    $record | ConvertTo-Json | Set-Content -LiteralPath $temporary -Encoding utf8
    Move-Item -LiteralPath $temporary -Destination $statePath -Force
}

# Serialize concurrent double-clicks without stopping or claiming another listener.
$mutex = [Threading.Mutex]::new($false, "Local\YuE2StudioLauncher$Port")
$locked = $false
try {
    $locked = $mutex.WaitOne(0)
    if (-not $locked) { throw '另一个启动操作正在进行，请稍后再试。' }
    $listeners = Get-Listener
    if ($listeners.Count) {
        $owners = @($listeners.OwningProcess | Sort-Object -Unique)
        $health = Get-ServiceHealth
        $owned = if ($owners.Count -eq 1) { Get-OwnedProcess $owners[0] } else { $null }
        if ($health.service -ne 'yue2-studio' -or $health.apiVersion -ne 1 -or -not $owned -or
            $health.projectRoot -ine $projectRoot -or $health.pid -ne $owners[0]) {
            throw "端口 $Port 已被其他服务占用。请手动处理占用，或使用 -Port 指定其他端口。没有停止任何进程。"
        }
        if (-not $ValidateOnly) { Save-ProcessRecord $owned }
        Write-Host "YuE2 已在运行：$baseUrl"
        if (-not $NoBrowser -and -not $ValidateOnly) { Start-Process $baseUrl }
        exit 0
    }
    $required = @('runtime/python312/python.exe','runtime/portable-runtime.json','engine/service.py','studio/dist/client/index.html',
        'models/YuE2-3B/config.json','models/YuE2-3B/model.safetensors','models/YuE2-3B/qwen.tiktoken',
        'models/YuE2-3B/weights_manifest.json','models/YuE2-Vae/config.json',
        'models/YuE2-Vae/model.safetensors','models/YuE2-Vae/weights_manifest.json')
    $missing = @($required | Where-Object {
        $candidate = Join-Path $projectRoot $_
        -not (Test-Path -LiteralPath $candidate -PathType Leaf) -or (Get-Item -LiteralPath $candidate).Length -eq 0
    })
    if ($missing.Count) { throw "启动依赖缺失或为空：`n$($missing -join "`n")`n请先完成环境安装、模型下载和前端构建。" }
    if ($ValidateOnly) { Write-Host '启动依赖与端口检查通过；未启动服务或加载模型。'; exit 0 }
    New-Item -ItemType Directory -Path $stateDir -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $stdout = Join-Path $stateDir "service-$Port-$stamp.stdout.log"
    $stderr = Join-Path $stateDir "service-$Port-$stamp.stderr.log"
    $arguments = @('-X','utf8','-u','-m','engine.service','--port',"$Port")
    if ($DataDirectory) {
        $resolvedData = [IO.Path]::GetFullPath($DataDirectory, $projectRoot)
        if ($resolvedData.Contains('"')) { throw '数据目录不能包含双引号。' }
        $arguments += @('--data-dir', ('"' + $resolvedData + '"'))
    }
    $startParameters = @{
        FilePath = $pythonPath
        ArgumentList = $arguments
        WorkingDirectory = $projectRoot
        PassThru = $true
    }
    if ($VisibleTerminal) {
        # Keep the service attached to the launcher console so closing the
        # visible terminal also closes the backend process tree.
        $startParameters.NoNewWindow = $true
    } else {
        $startParameters.WindowStyle = 'Hidden'
        $startParameters.RedirectStandardOutput = $stdout
        $startParameters.RedirectStandardError = $stderr
    }
    $process = Start-Process @startParameters
    $info = Get-OwnedProcess $process.Id
    if (-not $info) { throw "无法核验启动进程，请检查日志：$stderr" }
    Save-ProcessRecord $info
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        $process.Refresh()
        if ($process.HasExited) { throw "服务启动失败（退出码 $($process.ExitCode)），请检查：$stderr" }
        $health = Get-ServiceHealth
        if ($health.service -eq 'yue2-studio' -and $health.apiVersion -eq 1 -and
            $health.projectRoot -ieq $projectRoot) {
            $listeners = Get-Listener
            $server = Get-OwnedProcess $health.pid
            if ($server -and ($server.ProcessId -eq $process.Id -or $server.ParentProcessId -eq $process.Id) -and
                @($listeners | Where-Object OwningProcess -eq $health.pid).Count -gt 0) {
                Save-ProcessRecord $server
                $ready = $true; break
            }
        }
        Start-Sleep -Milliseconds 400
    }
    if (-not $ready) { throw "服务尚未就绪；未强制结束进程。日志：$stderr" }
    Write-Host "YuE2 已启动：$baseUrl"
    if (-not $NoBrowser) { Start-Process $baseUrl }
    if ($VisibleTerminal) {
        Write-Host '后端正在当前终端运行。关闭此终端即可停止 YuE2。'
        Write-Host '也可以使用 Ctrl+C 停止服务。'
        try { Wait-Process -Id ([int]$health.pid) -ErrorAction Stop } catch [Microsoft.PowerShell.Commands.ProcessCommandException] { }
    } else {
        Write-Host "关闭网页后后台继续运行。停止时运行：停止YuE2.ps1 -Port $Port"
        Write-Host "日志：$stdout"
    }
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
} finally {
    if ($locked) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
