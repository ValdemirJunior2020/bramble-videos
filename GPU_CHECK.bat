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
if exist "%WANGP_ROOT%\.git" for /f "delims=" %%C in ('git -C "%WANGP_ROOT%" rev-parse HEAD 2^>nul') do echo [WanGP commit] %%C
if exist "%WANGP_PYTHON%" (
  set "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=0"
  "%WANGP_PYTHON%" -c "import sys,torch,torch.nn.functional as F; print('[Python]',sys.version.split()[0]); print('[PyTorch]', torch.__version__); print('[Expected for RX 9060 XT] gfx1200 / PyTorch 2.12.0+rocm7.14.0'); print('[ROCm/HIP]', getattr(torch.version,'hip',None)); print('[GPU available]', torch.cuda.is_available()); print('[Device]', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU ONLY'); p=torch.cuda.get_device_properties(0) if torch.cuda.is_available() else None; print('[Architecture]',getattr(p,'gcnArchName','') if p else ''); print('[VRAM GB]', round(p.total_memory/1024**3,1) if p else 0); torch.backends.cuda.enable_flash_sdp(False); torch.backends.cuda.enable_mem_efficient_sdp(False); torch.backends.cuda.enable_math_sdp(True); x=torch.randn((128,128),device='cuda') if torch.cuda.is_available() else None; y=x@x if x is not None else None; q=torch.randn((1,4,64,64),device='cuda',dtype=torch.float16) if x is not None else None; z=F.scaled_dot_product_attention(q,q,q) if q is not None else None; torch.cuda.synchronize() if z is not None else None; print('[GPU matmul smoke]', 'PASS' if y is not None else 'SKIPPED'); print('[Math SDPA smoke]', 'PASS' if z is not None else 'SKIPPED')"
  if errorlevel 1 echo [ERROR] GPU kernel smoke failed - WanGP ROCm environment needs repair.
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
