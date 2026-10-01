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
set "MIOPEN_FIND_MODE=FAST"

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

netstat -ano | findstr ":11434 " | findstr "LISTENING" >nul
if errorlevel 1 (
  where ollama >nul 2>nul
  if not errorlevel 1 start "Bramble Ollama" /min cmd /c "ollama serve"
)

netstat -ano | findstr ":%WANGP_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  echo Starting persistent WanGP API session...
  start "Bramble WanGP" /D "%~dp0backend" "%WANGP_PYTHON%" -m uvicorn wangp_bridge:app --host 127.0.0.1 --port %WANGP_PORT%
) else (
  echo [OK] WanGP bridge already running.
)

netstat -ano | findstr ":%CHATTERBOX_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "Bramble Chatterbox" /D "%~dp0chatterbox_service" cmd /k "set TTS_DEVICE=%TTS_DEVICE%&& set PYTHONUTF8=1&& set PYTHONIOENCODING=utf-8&& .\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port %CHATTERBOX_PORT%"
)

netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "Bramble Backend" /D "%~dp0backend" cmd /k "set PYTHONUTF8=1&& set PYTHONIOENCODING=utf-8&& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
)

netstat -ano | findstr ":%FRONTEND_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "Bramble Frontend" /D "%~dp0frontend" cmd /k "npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%"
)

timeout /t 8 /nobreak >nul
start "" http://127.0.0.1:%FRONTEND_PORT%
exit /b 0
