@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Bramble Videos Launcher

set "FRONTEND_PORT=5174"
set "BACKEND_PORT=8010"
set "CHATTERBOX_PORT=8001"
set "TTS_DEVICE=auto"
set "COMFYUI_PATH=C:\Users\nobody\Documents\comfy\ComfyUI"

if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="COMFYUI_PATH" set "COMFYUI_PATH=%%B"
    if /i "%%A"=="TTS_DEVICE" set "TTS_DEVICE=%%B"
  )
)

echo ============================================================
echo BRAMBLE VIDEOS
echo Frontend   : http://127.0.0.1:%FRONTEND_PORT%
echo Backend    : http://127.0.0.1:%BACKEND_PORT%
echo Chatterbox : http://127.0.0.1:%CHATTERBOX_PORT%
echo ComfyUI    : http://127.0.0.1:8188
echo Ollama     : http://127.0.0.1:11434
echo GPU mode   : automatic GPU when available
echo ============================================================

set "NEEDS_INSTALL=0"
if not exist "backend\.venv\Scripts\python.exe" set "NEEDS_INSTALL=1"
if not exist "chatterbox_service\.venv\Scripts\python.exe" set "NEEDS_INSTALL=1"
if not exist "frontend\node_modules\.bin\vite.cmd" set "NEEDS_INSTALL=1"

if "!NEEDS_INSTALL!"=="1" (
  echo Bramble is not fully installed. Running INSTALL.bat now...
  call "%~dp0INSTALL.bat"
  if errorlevel 1 (
    echo [ERROR] Automatic installation failed.
    pause
    exit /b 1
  )
)

echo.
echo Checking GPU acceleration...
if exist "%~dp0GPU_CHECK.bat" call "%~dp0GPU_CHECK.bat" /quiet

netstat -ano | findstr ":11434 " | findstr "LISTENING" >nul
if errorlevel 1 (
  where ollama >nul 2>nul
  if not errorlevel 1 start "Bramble Ollama" /min cmd /c "ollama serve"
) else (
  echo [OK] Ollama already running - GPU is selected automatically when supported
)

netstat -ano | findstr ":8188 " | findstr "LISTENING" >nul
if errorlevel 1 (
  if exist "%COMFYUI_PATH%\.venv\Scripts\python.exe" (
    echo Starting your existing ComfyUI environment from %COMFYUI_PATH%
    start "Bramble ComfyUI" /D "%COMFYUI_PATH%" cmd /k ".\.venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188"
  ) else (
    echo [WARN] ComfyUI is not running and was not found at %COMFYUI_PATH%
  )
) else (
  echo [OK] Your existing ComfyUI is already running - leaving it untouched
)

netstat -ano | findstr ":%CHATTERBOX_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  if exist "chatterbox_service\.venv\Scripts\python.exe" (
    echo Starting Bramble expressive voice service with TTS_DEVICE=%TTS_DEVICE%...
    start "Bramble Chatterbox" /D "%~dp0chatterbox_service" cmd /k "set TTS_DEVICE=%TTS_DEVICE%&& .\.venv\Scripts\python.exe -m uvicorn app:app --host 127.0.0.1 --port %CHATTERBOX_PORT%"
  ) else (
    echo [WARN] Chatterbox is not installed. Run INSTALL.bat.
  )
) else (
  echo [OK] Chatterbox already running on %CHATTERBOX_PORT% - reusing it
  echo [INFO] If it was started before this GPU update, close that Chatterbox window once and run START.bat again.
)

netstat -ano | findstr ":%BACKEND_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "Bramble Backend" /D "%~dp0backend" cmd /k ".\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port %BACKEND_PORT%"
) else (
  echo [OK] Bramble backend already running on %BACKEND_PORT%
)

netstat -ano | findstr ":%FRONTEND_PORT% " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "Bramble Frontend" /D "%~dp0frontend" cmd /k "npm run dev -- --host 127.0.0.1 --port %FRONTEND_PORT%"
) else (
  echo [OK] Bramble frontend already running on %FRONTEND_PORT%
)

timeout /t 7 /nobreak >nul
start "" http://127.0.0.1:%FRONTEND_PORT%
exit /b 0
