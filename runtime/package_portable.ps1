# Assemble a self-contained YuE2 directory for a later one-click ZIP build.
[CmdletBinding()]
param([string]$Output='runtime/packages/YuE2-portable',[switch]$CheckOnly,[switch]$Force)

$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$outputPath=[IO.Path]::GetFullPath((Join-Path $projectRoot $Output))
$allowedRoot=[IO.Path]::GetFullPath((Join-Path $projectRoot 'runtime/packages'))
if(-not $outputPath.StartsWith($allowedRoot+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)){throw "便携包输出目录必须位于 runtime/packages：$outputPath"}

$files=@(
    '快速启动YuE2.cmd','启动YuE2.ps1','停止YuE2.ps1','README.md','engine/requirements-service.txt','runtime/portable-runtime.json',
    'runtime/requirements-resolved.txt','runtime/install-package.ps1','runtime/launch_visible.py','runtime/package_portable.ps1',
    'studio/dist/client/index.html'
)
$trees=@('engine','studio/dist/client','vendor/yue2/src','vendor/yue2/skills/yue2-music/scripts','vendor/yue2/licenses',
         'models/YuE2-3B','models/YuE2-Vae','models/MERT-v2-FullSong','models/SheetSage2','runtime/python312','runtime/playwright-browsers')
$excludedNames=@('test_*.py','*.pyc')

function Get-PortableFiles{
    $result=[System.Collections.Generic.List[object]]::new()
    foreach($relative in $files){
        $path=Join-Path $projectRoot $relative
        if(-not (Test-Path -LiteralPath $path -PathType Leaf)){throw "便携包缺少文件：$relative"}
        $result.Add([pscustomobject]@{Relative=$relative;Path=$path})
    }
    foreach($relative in $trees){
        $path=Join-Path $projectRoot $relative
        if(-not (Test-Path -LiteralPath $path -PathType Container)){throw "便携包缺少目录：$relative"}
        foreach($child in Get-ChildItem -LiteralPath $path -Recurse -File){
            $name=$child.Name
            if($child.Extension -eq '.pyc' -or $child.FullName -match '\\(__pycache__|node_modules|runtime\\cache)\\'){continue}
            if($relative -eq 'engine' -and $name -like 'test_*.py'){continue}
            $result.Add([pscustomobject]@{Relative=$child.FullName.Substring($projectRoot.Length+1).Replace('\','/');Path=$child.FullName})
        }
    }
    return $result | Sort-Object Relative -Unique
}

$items=@(Get-PortableFiles)
$bytes=($items | ForEach-Object {[int64](Get-Item -LiteralPath $_.Path).Length} | Measure-Object -Sum).Sum
if($CheckOnly){[pscustomobject]@{status='ready';files=$items.Count;bytes=[int64]$bytes;GiB=[math]::Round($bytes/1GB,2);output=$outputPath} | ConvertTo-Json -Compress;exit 0}
if(Test-Path -LiteralPath $outputPath){
    if(-not $Force){throw "输出目录已存在，拒绝覆盖：$outputPath"}
    Remove-Item -LiteralPath $outputPath -Recurse -Force
}
New-Item -ItemType Directory -Path $outputPath -Force | Out-Null
foreach($item in $items){
    $destination=Join-Path $outputPath $item.Relative
    New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
    Copy-Item -LiteralPath $item.Path -Destination $destination -Force
}
$manifest=[ordered]@{schema=1;createdAt=[DateTime]::UtcNow.ToString('O');files=[ordered]@{}}
foreach($item in $items){
    $hash=(Get-FileHash -LiteralPath (Join-Path $outputPath $item.Relative) -Algorithm SHA256).Hash.ToLowerInvariant()
    $size=[int64](Get-Item -LiteralPath (Join-Path $outputPath $item.Relative)).Length
    $manifest.files[$item.Relative]=[ordered]@{bytes=$size;sha256=$hash}
}
$manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $outputPath 'portable-package.json') -Encoding UTF8
[pscustomobject]@{status='created';files=$items.Count;bytes=[int64]$bytes;GiB=[math]::Round($bytes/1GB,2);output=$outputPath} | ConvertTo-Json -Compress
