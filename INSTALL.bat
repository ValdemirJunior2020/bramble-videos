@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bramble Videos - Install

echo ============================================================
echo BRAMBLE VIDEOS - LOCAL INSTALLER
echo ============================================================

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
  python -m venv backend\.venv
  if errorlevel 1 goto :fail
) else (
  echo [SKIP] Backend virtual environment already exists
)

call backend\.venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 goto :fail_active
python -m pip install -r backend\requirements.txt
if errorlevel 1 goto :fail_active
deactivate

if exist "frontend\node_modules" (
  echo [SKIP] frontend\node_modules already exists
) else (
  pushd frontend
  call npm install
  if errorlevel 1 (
    popd
    goto :fail
  )
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
  echo [INFO] h264_amf is not present in this FFmpeg build.
  echo [INFO] Bramble Videos will use CPU video encoding until an FFmpeg build with AMD AMF is installed.
) else (
  echo [OK] AMD AMF h264 encoder detected - final video rendering can use your Radeon GPU.
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
echo Running quick code validation...
call TEST.bat /quiet
if errorlevel 1 (
  echo [WARN] Installation completed, but the validation step reported an error.
  echo Run TEST.bat again to see the details.
)

echo.
echo INSTALL COMPLETE.
echo Double-click START.bat.
pause
exit /b 0

:fail_active
deactivate
:fail
echo.
echo [ERROR] Installation failed. Read the error above.
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
