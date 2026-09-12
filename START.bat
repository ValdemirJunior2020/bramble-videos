@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Bramble Videos Launcher

set "FRONTEND_PORT=5174"
set "BACKEND_PORT=8010"

echo ============================================================
echo BRAMBLE VIDEOS
echo Frontend : http://127.0.0.1:%FRONTEND_PORT%
echo Backend  : http://127.0.0.1:%BACKEND_PORT%
echo ComfyUI  : http://127.0.0.1:8188
echo Ollama   : http://127.0.0.1:11434
echo ============================================================

if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] Run INSTALL.bat first.
  pause
  exit /b 1
)
if not exist "frontend\node_modules" (
  echo [ERROR] Run INSTALL.bat first.
  pause
  exit /b 1
)

set "COMFYUI_PATH=C:\Users\nobody\Documents\comfy\ComfyUI"
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="COMFYUI_PATH" set "COMFYUI_PATH=%%B"
  )
)

netstat -ano | findstr ":11434 " | findstr "LISTENING" >nul
if errorlevel 1 (
  where ollama >nul 2>nul
  if not errorlevel 1 start "Bramble Ollama" /min cmd /c "ollama serve"
) else (
  echo [OK] Ollama already running
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

timeout /t 5 /nobreak >nul
start "" http://127.0.0.1:%FRONTEND_PORT%
exit /b 0
