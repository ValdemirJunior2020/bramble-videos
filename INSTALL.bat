@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bramble Videos - Install

echo ============================================================
echo BRAMBLE VIDEOS - LOCAL INSTALLER
echo ============================================================

where python >nul 2>nul || (echo [ERROR] Python was not found in PATH.& pause & exit /b 1)
where node >nul 2>nul || (echo [ERROR] Node.js was not found in PATH.& pause & exit /b 1)
where npm >nul 2>nul || (echo [ERROR] npm was not found in PATH.& pause & exit /b 1)
where ffmpeg >nul 2>nul || (echo [ERROR] FFmpeg was not found in PATH.& pause & exit /b 1)
where ffprobe >nul 2>nul || (echo [ERROR] FFprobe was not found in PATH.& pause & exit /b 1)

echo [OK] Python
python --version
echo [OK] Node
node --version
echo [OK] FFmpeg
ffmpeg -version | findstr /b "ffmpeg version"

if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [OK] Created .env from .env.example
) else (
  echo [SKIP] Existing .env kept untouched
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating backend virtual environment...
  python -m venv backend\.venv || (pause & exit /b 1)
) else (
  echo [SKIP] Backend virtual environment already exists
)

call backend\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install -r backend\requirements.txt || (pause & exit /b 1)
deactivate

if exist "frontend\node_modules" (
  echo [SKIP] frontend\node_modules already exists
) else (
  pushd frontend
  call npm install || (popd & pause & exit /b 1)
  popd
)

if not exist storage mkdir storage
if not exist storage\assets mkdir storage\assets
if not exist storage\projects mkdir storage\projects
if not exist storage\uploads mkdir storage\uploads

echo.
echo Checking AMD hardware video encoder...
ffmpeg -hide_banner -encoders 2>nul | findstr /i "h264_amf" >nul
if errorlevel 1 (
  echo [INFO] h264_amf not present in this FFmpeg build. CPU video fallback will work.
) else (
  echo [OK] AMD AMF h264 encoder detected - final rendering can use your Radeon GPU.
)

echo.
where ollama >nul 2>nul
if errorlevel 1 (
  echo [INFO] Ollama was not found. Install it before using AI scene planning.
) else (
  ollama list | findstr /i "qwen3:8b" >nul
  if errorlevel 1 (
    echo [INFO] qwen3:8b is not installed. Run: ollama pull qwen3:8b
  ) else (
    echo [OK] qwen3:8b found
  )
)

echo.
echo INSTALL COMPLETE.
echo Double-click START.bat.
pause
