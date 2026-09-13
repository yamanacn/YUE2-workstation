#requires -Version 7.0
[CmdletBinding()]
param([ValidateRange(1024,65535)][int]$Port = 4174, [switch]$ValidateOnly)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$statePath = Join-Path $projectRoot "runtime/launcher/service-$Port.json"
$pythonPath = Join-Path $projectRoot 'runtime/python312/python.exe'
$baseUrl = "http://127.0.0.1:$Port"
function Test-ServiceAlive {
    try {
        $health = Invoke-RestMethod "$baseUrl/api/v1/health" -TimeoutSec 2
        return $health.service -eq 'yue2-studio' -and $health.apiVersion -eq 1
    } catch { return $false }
}
try {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) {
        if (Test-ServiceAlive) { throw '服务仍在运行但缺少本项目状态记录；拒绝停止未知进程。' }
        Write-Host 'YuE2 服务已退出；没有需要停止的进程。'
        exit 0
    }
    try { $record = Get-Content -LiteralPath $statePath -Raw -Encoding utf8 -ErrorAction Stop | ConvertFrom-Json }
    catch [System.Management.Automation.ItemNotFoundException] {
        if (Test-ServiceAlive) { throw '服务仍在运行但状态记录在读取时丢失；拒绝停止未知进程。' }
        Write-Host 'YuE2 服务已退出；没有需要停止的进程。'
        exit 0
    }
    if ($record.projectRoot -ine $projectRoot -or $record.port -ne $Port) { throw '进程记录与本项目不符。' }
    $info = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$record.pid)" -ErrorAction SilentlyContinue
    if (-not $info) { Write-Host '记录的后台进程已退出。'; exit 0 }
    $launcher = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$record.launcherPid)" -ErrorAction SilentlyContinue
    if (-not $launcher -or $launcher.ExecutablePath -ine $pythonPath -or
        $launcher.CreationDate.ToUniversalTime().Ticks -ne ([datetime]$record.launcherCreationTimeUtc).ToUniversalTime().Ticks -or
        ($info.ProcessId -ne $launcher.ProcessId -and $info.ParentProcessId -ne $launcher.ProcessId)) {
        throw '本项目 Python 启动进程身份或父子关系不符；拒绝停止。'
    }
    if ($info.ExecutablePath -ine $record.executablePath -or $info.CommandLine -cne $record.commandLine -or
        $info.CreationDate.ToUniversalTime().Ticks -ne ([datetime]$record.creationTimeUtc).ToUniversalTime().Ticks -or
        $info.CommandLine -notmatch '(?i)(?:^|\s)-m\s+engine\.service(?:\s|$)' -or
        $info.CommandLine -notmatch "(?:^|\s)--port(?:\s+|=)$Port(?:\s|`$)") {
        throw '进程身份或创建时间已改变；拒绝停止。'
    }
    $owners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
    if ($owners.Count -ne 1 -or $owners[0] -ne $record.pid) { throw '端口监听进程与记录不一致；拒绝停止。' }
    $health = Invoke-RestMethod "$baseUrl/api/v1/health" -TimeoutSec 3
    if ($health.service -ne 'yue2-studio' -or $health.apiVersion -ne 1 -or
        $health.projectRoot -ine $projectRoot -or $health.pid -ne $record.pid) { throw '无法确认 YuE2 服务身份；拒绝停止。' }
    if ($ValidateOnly) { Write-Host '服务身份、创建时间、命令行和端口检查通过；未请求停止。'; exit 0 }
    # The backend must atomically reject shutdown when any job is active or queued.
    try {
        $null = Invoke-RestMethod "$baseUrl/api/v1/shutdown" -Method Post -ContentType 'application/json' -Body '{}' -TimeoutSec 5
    } catch {
        if ([int]$_.Exception.Response.StatusCode -eq 409) { throw '仍有排队或运行中的任务。请等待完成，或在界面取消任务后再停止。' }
        throw "安全退出接口未成功；未强制结束后台。$($_.Exception.Message)"
    }
    for ($attempt = 0; $attempt -lt 40; $attempt++) {
        $current = Get-CimInstance Win32_Process -Filter "ProcessId = $([int]$record.pid)" -ErrorAction SilentlyContinue
        if (-not $current -or $current.CreationDate.ToUniversalTime().Ticks -ne ([datetime]$record.creationTimeUtc).ToUniversalTime().Ticks) {
            Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
            Write-Host 'YuE2 后台已安全退出。'
            exit 0
        }
        Start-Sleep -Milliseconds 250
    }
    throw '已发送安全退出请求，但进程尚未退出。保留进程记录；未强制结束后台。'
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
