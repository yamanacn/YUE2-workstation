@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
where pwsh.exe >nul 2>nul
if errorlevel 1 (
  echo PowerShell 7 is required. Run: pwsh -File .\启动YuE2-dev.ps1
  pause
  exit /b 1
)
pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%ROOT%启动YuE2-dev.ps1"
if errorlevel 1 pause
endlocal
