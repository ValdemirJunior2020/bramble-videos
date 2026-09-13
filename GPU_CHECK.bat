@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "QUIET=0"
if /i "%~1"=="/quiet" set "QUIET=1"
set "COMFYUI_PATH=C:\Users\nobody\Documents\comfy\ComfyUI"
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="COMFYUI_PATH" set "COMFYUI_PATH=%%B"
  )
)

echo ------------------------------------------------------------
echo BRAMBLE GPU CHECK
echo ------------------------------------------------------------

powershell -NoProfile -Command "$g=Get-CimInstance Win32_VideoController | Where-Object {$_.Name -match 'AMD|Radeon'} | Select-Object -First 1; if($g){Write-Host '[GPU] ' $g.Name}else{Write-Host '[WARN] No AMD Radeon GPU detected by Windows'}"

if exist "%COMFYUI_PATH%\.venv\Scripts\python.exe" (
  echo [ComfyUI] Checking PyTorch GPU backend...
  "%COMFYUI_PATH%\.venv\Scripts\python.exe" -c "import torch; print('[ComfyUI] torch:', torch.__version__); print('[ComfyUI] HIP:', getattr(torch.version,'hip',None)); print('[ComfyUI] GPU available:', torch.cuda.is_available()); print('[ComfyUI] device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU ONLY')" 2>nul
  "%COMFYUI_PATH%\.venv\Scripts\python.exe" -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" 2>nul
  if errorlevel 1 (
    echo [WARN] ComfyUI Python cannot currently see a GPU compute device.
    echo [WARN] Images will be CPU-bound until the ComfyUI environment has AMD ROCm-enabled PyTorch.
  ) else (
    echo [OK] ComfyUI GPU acceleration is available.
  )
) else (
  echo [WARN] ComfyUI Python was not found at %COMFYUI_PATH%\.venv\Scripts\python.exe
)

if exist "chatterbox_service\.venv\Scripts\python.exe" (
  echo [Chatterbox] Checking PyTorch GPU backend...
  "chatterbox_service\.venv\Scripts\python.exe" -c "import torch; print('[Chatterbox] torch:', torch.__version__); print('[Chatterbox] HIP:', getattr(torch.version,'hip',None)); print('[Chatterbox] GPU available:', torch.cuda.is_available()); print('[Chatterbox] device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU fallback')" 2>nul
) else (
  echo [WARN] Chatterbox environment not installed.
)

ffmpeg -hide_banner -encoders 2>nul | findstr /i "h264_amf" >nul
if errorlevel 1 (
  echo [Video] CPU encoder fallback - h264_amf not found in this FFmpeg build.
) else (
  echo [OK] Video export can use AMD AMF h264 hardware encoding.
)

where ollama >nul 2>nul
if errorlevel 1 (
  echo [Ollama] Not found in PATH.
) else (
  echo [Ollama] Installed. Ollama automatically selects supported GPU acceleration.
)

echo ------------------------------------------------------------
if "%QUIET%"=="0" pause
exit /b 0
