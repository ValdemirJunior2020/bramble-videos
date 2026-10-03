@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Bramble Videos Launcher

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "FRONTEND_PORT=5174"
set "BACKEND_PORT=8010"
set "CHATTERBOX_PORT=8001"
set "WANGP_PORT=8020"
set "TTS_DEVICE=auto"
set "WANGP_ROOT=%~dp0runtime\WanGP"
set "WANGP_MEMORY_PROFILE=4"
set "WANGP_ATTENTION=sdpa"
set "MIOPEN_FIND_MODE=FAST"
set "PID_DIR=%~dp0runtime\pids"

if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="WANGP_ROOT" set "WANGP_ROOT=%%B"
    if /i "%%A"=="WANGP_MEMORY_PROFILE" set "WANGP_MEMORY_PROFILE=%%B"
    if /i "%%A"=="WANGP_ATTENTION" set "WANGP_ATTENTION=%%B"
    if /i "%%A"=="TTS_DEVICE" set "TTS_DEVICE=%%B"
  )
)
if not "%WANGP_ROOT:~1,1%"==":" set "WANGP_ROOT=%~dp0%WANGP_ROOT%"
set "WANGP_PYTHON=%WANGP_ROOT%\env_venv\Scripts\python.exe"
if not exist "%PID_DIR%" mkdir "%PID_DIR%"

echo ============================================================
echo BRAMBLE VIDEOS - WANGP CINEMATIC STUDIO
echo Frontend   : http://127.0.0.1:%FRONTEND_PORT%
echo Backend    : http://127.0.0.1:%BACKEND_PORT%
echo WanGP      : http://127.0.0.1:%WANGP_PORT%
echo Chatterbox : http://127.0.0.1:%CHATTERBOX_PORT%
echo Ollama     : http://127.0.0.1:11434
echo ============================================================

set "NEEDS_INSTALL=0"
if not exist "backend\.venv\Scripts\python.exe" set "NEEDS_INSTALL=1"
if not exist "chatterbox_service\.venv\Scripts\python.exe" set "NEEDS_INSTALL=1"
if not exist "frontend\node_modules\.bin\vite.cmd" set "NEEDS_INSTALL=1"
if not exist "%WANGP_PYTHON%" set "NEEDS_INSTALL=1"
if not exist "%WANGP_ROOT%\shared\api.py" set "NEEDS_INSTALL=1"
if "!NEEDS_INSTALL!"=="1" (
  echo Bramble is not fully installed. Running INSTALL.bat...
  call "%~dp0INSTALL.bat"
  if errorlevel 1 exit /b 1
)

rem After a git pull, do not reuse stale Bramble Python processes that still
rem have old code loaded in memory. Restart only listeners whose command line
rem identifies them as this Bramble backend / WanGP bridge. Shared services are untouched.
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %WANGP_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$c.OwningProcess) -ErrorAction SilentlyContinue; if($p -and $p.CommandLine -match 'uvicorn.+wangp_bridge:app'){Write-Host '[RESTART] Stale Bramble WanGP bridge'; Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 700}}"
powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort %BACKEND_PORT% -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$c.OwningProcess) -ErrorAction SilentlyContinue; if($p -and $p.CommandLine -match 'uvicorn.+app.main:app'){Write-Host '[RESTART] Stale Bramble backend'; Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 700}}"

rem Ollama is shared. Start it only if absent, and never claim ownership of it.
netstat -ano | findstr ":11434 " | findstr "LISTENING" >nul
if errorlevel 1 (
  where ollama >nul 2>nul
  if not errorlevel 1 start "Bramble Ollama" /min cmd /c "ollama serve"
)

netstat -ano | findstr ":%WANGP_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  echo Starting persistent WanGP API session...
  powershell -NoProfile -Command "$p=Start-Process -FilePath '%WANGP_PYTHON%' -ArgumentList '-m','uvicorn','wangp_bridge:app','--host','127.0.0.1','--port','%WANGP_PORT%' -WorkingDirectory '%~dp0backend' -WindowStyle Minimized -PassThru; Set-Content -Path '%PID_DIR%\wangp.pid' -Value $p.Id"
) else (
  echo [OK] WanGP bridge already running - reusing it and not taking ownership.
  if exist "%PID_DIR%\wangp.pid" del /q "%PID_DIR%\wangp.pid" >nul 2>nul
)

netstat -ano | findstr ":%CHATTERBOX_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  powershell -NoProfile -Command "$p=Start-Process -FilePath '%~dp0chatterbox_service\.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','app:app','--host','127.0.0.1','--port','%CHATTERBOX_PORT%' -WorkingDirectory '%~dp0chatterbox_service' -WindowStyle Minimized -PassThru; Set-Content -Path '%PID_DIR%\chatterbox.pid' -Value $p.Id"
) else (
  echo [OK] Chatterbox already running - reusing it and not taking ownership.
  if exist "%PID_DIR%\chatterbox.pid" del /q "%PID_DIR%\chatterbox.pid" >nul 2>nul
)

netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  powershell -NoProfile -Command "$p=Start-Process -FilePath '%~dp0backend\.venv\Scripts\python.exe' -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','%BACKEND_PORT%' -WorkingDirectory '%~dp0backend' -WindowStyle Minimized -PassThru; Set-Content -Path '%PID_DIR%\backend.pid' -Value $p.Id"
) else (
  echo [OK] Bramble backend already running - reusing it and not taking ownership.
  if exist "%PID_DIR%\backend.pid" del /q "%PID_DIR%\backend.pid" >nul 2>nul
)

netstat -ano | findstr ":%FRONTEND_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  powershell -NoProfile -Command "$p=Start-Process -FilePath 'cmd.exe' -ArgumentList '/c','npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%' -WorkingDirectory '%~dp0frontend' -WindowStyle Minimized -PassThru; Set-Content -Path '%PID_DIR%\frontend.pid' -Value $p.Id"
) else (
  echo [OK] Bramble frontend already running - reusing it and not taking ownership.
  if exist "%PID_DIR%\frontend.pid" del /q "%PID_DIR%\frontend.pid" >nul 2>nul
)

timeout /t 8 /nobreak >nul
start "" http://127.0.0.1:%FRONTEND_PORT%
exit /b 0
