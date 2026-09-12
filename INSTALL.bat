@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Bramble Videos - Install

set "LOG=%~dp0install.log"
if exist ".bramble-installed" del /q ".bramble-installed" >nul 2>nul

echo ============================================================
echo BRAMBLE VIDEOS - LOCAL INSTALLER
echo ============================================================
echo Install started %date% %time% > "%LOG%"
echo Folder: %CD% >> "%LOG%"

echo [1/8] Checking required programs...
where python >nul 2>nul
if errorlevel 1 goto :missing_python
where node >nul 2>nul
if errorlevel 1 goto :missing_node
where npm >nul 2>nul
if errorlevel 1 goto :missing_npm
where ffmpeg >nul 2>nul
if errorlevel 1 goto :missing_ffmpeg
where ffprobe >nul 2>nul
if errorlevel 1 goto :missing_ffprobe

echo [OK] Python
python --version
python --version >> "%LOG%" 2>&1
echo [OK] Node
node --version
node --version >> "%LOG%" 2>&1
echo [OK] npm
call npm --version
call npm --version >> "%LOG%" 2>&1
echo [OK] FFmpeg
ffmpeg -version | findstr /b "ffmpeg version"

echo.
echo [2/8] Checking environment file...
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [OK] Created .env from .env.example
) else (
  echo [SKIP] Existing .env kept untouched
)

echo.
echo [3/8] Preparing backend Python environment...
if exist "backend\.venv" if not exist "backend\.venv\Scripts\python.exe" (
  echo [WARN] Broken backend virtual environment found. Rebuilding it...
  rmdir /s /q "backend\.venv"
)
if not exist "backend\.venv\Scripts\python.exe" (
  python -m venv "backend\.venv" >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [SKIP] Backend virtual environment already exists
)
if not exist "backend\.venv\Scripts\python.exe" goto :fail

echo.
echo [4/8] Installing backend packages...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
"backend\.venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, pydantic, PIL" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
echo [OK] Backend packages verified

echo.
echo [5/8] Installing expressive Chatterbox voice service...
if exist "chatterbox_service\.venv" if not exist "chatterbox_service\.venv\Scripts\python.exe" (
  echo [WARN] Broken Chatterbox environment found. Rebuilding it...
  rmdir /s /q "chatterbox_service\.venv"
)
if not exist "chatterbox_service\.venv\Scripts\python.exe" (
  echo Creating Chatterbox Python environment...
  python -m venv "chatterbox_service\.venv" >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
)
"chatterbox_service\.venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
"chatterbox_service\.venv\Scripts\python.exe" -c "import chatterbox, fastapi, uvicorn" >nul 2>nul
if errorlevel 1 (
  echo Installing Chatterbox TTS. First install can take several minutes...
  "chatterbox_service\.venv\Scripts\python.exe" -m pip install -r "chatterbox_service\requirements.txt" >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo [ERROR] Chatterbox install failed. See install.log.
    goto :fail
  )
) else (
  echo [SKIP] Chatterbox packages already installed
)
"chatterbox_service\.venv\Scripts\python.exe" -c "import chatterbox, fastapi, uvicorn" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
echo [OK] Expressive voice service verified

echo.
echo [6/8] Installing frontend packages...
if exist "frontend\node_modules\.bin\vite.cmd" (
  echo [SKIP] Frontend packages already installed
) else (
  if exist "frontend\node_modules" rmdir /s /q "frontend\node_modules"
  pushd "frontend"
  echo Running npm install...
  call npm install >> "%LOG%" 2>&1
  set "NPM_RESULT=!ERRORLEVEL!"
  popd
  if not "!NPM_RESULT!"=="0" goto :fail
)
if not exist "frontend\node_modules\.bin\vite.cmd" goto :fail
echo [OK] Frontend packages verified

echo.
echo [7/8] Creating storage folders and checking local AI...
if not exist "storage" mkdir "storage"
if not exist "storage\assets" mkdir "storage\assets"
if not exist "storage\projects" mkdir "storage\projects"
if not exist "storage\uploads" mkdir "storage\uploads"
ffmpeg -hide_banner -encoders 2>nul | findstr /i "h264_amf" >nul
if errorlevel 1 (
  echo [INFO] AMD AMF not found in this FFmpeg build. CPU video fallback will be used.
) else (
  echo [OK] AMD AMF h264 encoder detected
)
where ollama >nul 2>nul
if errorlevel 1 (
  echo [INFO] Ollama was not found.
) else (
  ollama list | findstr /i "qwen3:8b" >nul
  if errorlevel 1 (echo [INFO] qwen3:8b is not installed. Run: ollama pull qwen3:8b) else (echo [OK] qwen3:8b found)
)

echo.
echo [8/8] Running code validation...
call TEST.bat /quiet >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
if not exist "backend\.venv\Scripts\python.exe" goto :fail
if not exist "chatterbox_service\.venv\Scripts\python.exe" goto :fail
if not exist "frontend\node_modules\.bin\vite.cmd" goto :fail

> ".bramble-installed" echo Installed %date% %time%
echo.
echo ============================================================
echo INSTALL COMPLETE - EVERYTHING VERIFIED
echo ============================================================
echo Backend Python     : FOUND
echo Chatterbox Voice   : FOUND
echo Frontend Vite      : FOUND
echo Marker             : .bramble-installed
echo.
echo Double-click START.bat.
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo [ERROR] INSTALLATION FAILED
echo ============================================================
echo Open this file for the real error:
echo %LOG%
if exist ".bramble-installed" del /q ".bramble-installed" >nul 2>nul
pause
exit /b 1

:missing_python
echo [ERROR] Python was not found in PATH.
pause
exit /b 1
:missing_node
echo [ERROR] Node.js was not found in PATH.
pause
exit /b 1
:missing_npm
echo [ERROR] npm was not found in PATH.
pause
exit /b 1
:missing_ffmpeg
echo [ERROR] FFmpeg was not found in PATH.
pause
exit /b 1
:missing_ffprobe
echo [ERROR] FFprobe was not found in PATH.
pause
exit /b 1
