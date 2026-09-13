@echo off
chcp 65001 >nul
setlocal
set "ROOT=%~dp0"
set "YUE2_PYTHON=%ROOT%runtime\python312\python.exe"
set "YUE2_LAUNCHER=%ROOT%runtime\launch_visible.py"

if not exist "%YUE2_PYTHON%" (
  echo YuE2 internal Python runtime is missing: "%YUE2_PYTHON%"
  pause
  exit /b 1
)

rem Prefer a Windows Terminal tab, with a normal visible console fallback.
where wt.exe >nul 2>nul
if not errorlevel 1 (
  wt.exe new-tab --title "YuE2 后端" "%YUE2_PYTHON%" -s -X utf8 -u "%YUE2_LAUNCHER%" %*
  exit /b 0
)

"%YUE2_PYTHON%" -s -X utf8 -u "%YUE2_LAUNCHER%" %*
if errorlevel 1 pause
endlocal
