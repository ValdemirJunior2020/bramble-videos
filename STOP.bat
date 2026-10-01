@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "PID_DIR=%~dp0runtime\pids"

echo Stopping only processes started by this Bramble launcher...
for %%S in (frontend backend wangp chatterbox) do (
  if exist "%PID_DIR%\%%S.pid" (
    set /p BRAMBLE_PID=<"%PID_DIR%\%%S.pid"
    call taskkill /PID %%BRAMBLE_PID%% /T /F >nul 2>nul
    del /q "%PID_DIR%\%%S.pid" >nul 2>nul
    echo [STOPPED] %%S
  ) else (
    echo [SKIP] %%S was not started by this Bramble launch.
  )
)
echo Shared Ollama and any pre-existing services were left untouched.
pause
