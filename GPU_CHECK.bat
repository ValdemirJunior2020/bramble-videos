@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "QUIET=0"
if /i "%~1"=="/quiet" set "QUIET=1"
set "WANGP_ROOT=%~dp0runtime\WanGP"
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do if /i "%%A"=="WANGP_ROOT" set "WANGP_ROOT=%%B"
)
if not "%WANGP_ROOT:~1,1%"==":" set "WANGP_ROOT=%~dp0%WANGP_ROOT%"
set "WANGP_PYTHON=%WANGP_ROOT%\env_venv\Scripts\python.exe"

echo ------------------------------------------------------------
echo BRAMBLE WANGP / AMD GPU CHECK
echo ------------------------------------------------------------
powershell -NoProfile -Command "$g=Get-CimInstance Win32_VideoController | Where-Object {$_.Name -match 'AMD|Radeon'} | Select-Object -First 1; if($g){Write-Host '[GPU]' $g.Name; Write-Host '[Driver]' $g.DriverVersion; if($g.Name -match '9060'){Write-Host '[Architecture] gfx1200 / RDNA 4'}}else{Write-Host '[WARN] No AMD Radeon GPU detected'}"

where clinfo >nul 2>nul
if errorlevel 1 (echo [clinfo] Not found in PATH.) else (echo [clinfo gfx targets] & clinfo 2>nul | findstr /i "gfx")

echo [WanGP root] %WANGP_ROOT%
if exist "%WANGP_ROOT%\shared\api.py" (echo [OK] WanGP source detected.) else (echo [WARN] WanGP source missing.)
if exist "%WANGP_PYTHON%" (
  "%WANGP_PYTHON%" -c "import sys,torch; print('[Python]',sys.version.split()[0]); print('[PyTorch]', torch.__version__); print('[ROCm/HIP]', getattr(torch.version,'hip',None)); print('[GPU available]', torch.cuda.is_available()); print('[Device]', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU ONLY'); p=torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None; print('[Architecture]',getattr(p,'gcnArchName','') if p else ''); print('[VRAM GB]', round(p.total_memory/1024**3,1) if p else 0)"
) else (
  echo [WARN] WanGP Python environment missing: %WANGP_PYTHON%
)

where ffmpeg >nul 2>nul
if errorlevel 1 (echo [FFmpeg] Not found in PATH.) else (ffmpeg -version 2>nul | findstr /b /c:"ffmpeg version")
ffmpeg -hide_banner -encoders 2>nul | findstr /i "h264_amf" >nul
if errorlevel 1 (echo [FFmpeg] h264_amf unavailable - libx264 fallback will be used.) else (echo [OK] FFmpeg h264_amf available.)
where ollama >nul 2>nul
if errorlevel 1 (echo [Ollama] Not found.) else (echo [Ollama] Installed.)
echo ------------------------------------------------------------
if "%QUIET%"=="0" pause
exit /b 0
