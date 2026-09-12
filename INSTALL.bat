@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bramble Videos - Install

set "LOG=%~dp0install.log"

echo ============================================================
echo BRAMBLE VIDEOS - LOCAL INSTALLER
echo ============================================================
echo Install started %date% %time% > "%LOG%"

echo [1/7] Checking required programs...
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
echo [OK] npm
call npm --version
echo [OK] FFmpeg
ffmpeg -version | findstr /b "ffmpeg version"

echo.
echo [2/7] Checking environment file...
if not exist ".env" (
  copy /y ".env.example" ".env" >nul
  echo [OK] Created .env from .env.example
) else (
  echo [SKIP] Existing .env kept untouched
)

echo.
echo [3/7] Preparing backend Python environment...
if exist "backend\.venv" if not exist "backend\.venv\Scripts\python.exe" (
  echo [WARN] Broken backend virtual environment found. Rebuilding it...
  rmdir /s /q "backend\.venv"
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo Creating backend virtual environment...
  python -m venv "backend\.venv" >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [SKIP] Backend virtual environment already exists
)

if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] Python virtual environment was not created correctly.
  goto :fail
)

echo.
echo [4/7] Installing backend packages...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :fail
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt"
if errorlevel 1 goto :fail

"backend\.venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, pydantic, PIL" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Backend package verification failed.
  goto :fail
)
echo [OK] Backend packages verified

echo.
echo [5/7] Installing frontend packages...
if exist "frontend\node_modules\.bin\vite.cmd" (
  echo [SKIP] Frontend packages already installed
) else (
  if exist "frontend\node_modules" (
    echo [WARN] Incomplete frontend node_modules found. Rebuilding it...
    rmdir /s /q "frontend\node_modules"
  )
  pushd "frontend"
  call npm install
  set "NPM_RESULT=%ERRORLEVEL%"
  popd
  if not "%NPM_RESULT%"=="0" goto :fail
)

if not exist "frontend\node_modules\.bin\vite.cmd" (
  echo [ERROR] Frontend package installation did not create Vite.
  goto :fail
)
echo [OK] Frontend packages verified

echo.
echo [6/7] Creating storage folders...
if not exist "storage" mkdir "storage"
if not exist "storage\assets" mkdir "storage\assets"
if not exist "storage\projects" mkdir "storage\projects"
if not exist "storage\uploads" mkdir "storage\uploads"

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
echo [7/7] Running code validation...
call TEST.bat /quiet
if errorlevel 1 (
  echo [ERROR] Validation failed. Installation is not being marked complete.
  goto :fail
)

if not exist "backend\.venv\Scripts\python.exe" goto :fail
if not exist "frontend\node_modules\.bin\vite.cmd" goto :fail

> ".bramble-installed" echo Installed %date% %time%

echo.
echo ============================================================
echo INSTALL COMPLETE - EVERYTHING VERIFIED
echo ============================================================
echo Double-click START.bat.
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo [ERROR] INSTALLATION FAILED
echo ============================================================
echo The installation was NOT marked complete.
echo Check the error above and install.log if needed.
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
