@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Bramble Videos Launcher

echo ============================================================
echo BRAMBLE VIDEOS
echo Frontend : http://127.0.0.1:5173
echo Backend  : http://127.0.0.1:8000
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
  where ollama >nul 2>nul && start "Bramble Ollama" /min cmd /c "ollama serve"
) else echo [OK] Ollama already running

netstat -ano | findstr ":8188 " | findstr "LISTENING" >nul
if errorlevel 1 (
  if exist "%COMFYUI_PATH%\.venv\Scripts\python.exe" (
    echo Starting ComfyUI from %COMFYUI_PATH%
    start "Bramble ComfyUI" cmd /k "cd /d \"%COMFYUI_PATH%\" && .\.venv\Scripts\python.exe main.py --listen 127.0.0.1 --port 8188"
  ) else (
    echo [WARN] ComfyUI not found at %COMFYUI_PATH%
  )
) else echo [OK] ComfyUI already running

netstat -ano | findstr ":8000 " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "Bramble Backend" cmd /k "cd /d \"%~dp0backend\" && .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
) else echo [OK] Backend already running

netstat -ano | findstr ":5173 " | findstr "LISTENING" >nul
if errorlevel 1 (
  start "Bramble Frontend" cmd /k "cd /d \"%~dp0frontend\" && npm run dev -- --host 127.0.0.1 --port 5173"
) else echo [OK] Frontend already running

timeout /t 5 /nobreak >nul
start "" http://127.0.0.1:5173
exit /b 0
