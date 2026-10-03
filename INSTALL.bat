@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
title Bramble Videos - Install

rem Piper on Windows must read pt-BR text as UTF-8. These variables are also
rem inherited by every Python/Piper process launched by this installer.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

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
echo [WanGP] Preparing official WanGP AMD environment...
where git >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Git is required to install WanGP.
  goto :fail
)
set "WANGP_ROOT=%~dp0runtime\WanGP"
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do if /i "%%A"=="WANGP_ROOT" set "WANGP_ROOT=%%B"
)
if not "!WANGP_ROOT:~1,1!"==":" set "WANGP_ROOT=%~dp0!WANGP_ROOT!"
if not exist "runtime" mkdir "runtime"

set "AMD_GPU_NAME="
for /f "usebackq delims=" %%G in (`powershell -NoProfile -Command "$g=Get-CimInstance Win32_VideoController ^| Where-Object {$_.Name -match 'AMD|Radeon'} ^| Select-Object -First 1; if($g){$g.Name}"`) do set "AMD_GPU_NAME=%%G"
if not defined AMD_GPU_NAME (
  echo [ERROR] No AMD Radeon GPU was detected by Windows.
  goto :fail
)
echo [GPU] !AMD_GPU_NAME!
set "AMD_GFX1200=0"
echo !AMD_GPU_NAME! | findstr /i "9060" >nul && set "AMD_GFX1200=1"
if "!AMD_GFX1200!"=="1" echo [OK] RX 9060 XT = gfx1200 / RDNA 4

if not exist "!WANGP_ROOT!\shared\api.py" (
  echo Cloning official WanGP...
  git clone https://github.com/deepbeepmeep/Wan2GP.git "!WANGP_ROOT!" >> "%LOG%" 2>&1
  if errorlevel 1 goto :fail
) else (
  echo [SKIP] Existing WanGP source kept untouched
)

py -3.12 -V >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Current WanGP AMD Windows guidance requires Python 3.12.
  echo Install Python 3.12, then run INSTALL.bat again.
  goto :fail
)

pushd "!WANGP_ROOT!"

set "WANGP_PYTHON=!WANGP_ROOT!\env_venv\Scripts\python.exe"
set "WANGP_GFX1200_MARKER=!WANGP_ROOT!\.bramble-gfx1200-rocm7140-aug31"
set "WANGP_GFX1200_PIN=b2b1d230acafffe724bed833440bc10d1232a7a9"

if "!AMD_GFX1200!"=="1" (
  rem Temporary RX 9060 XT compatibility pin. Upstream WanGP issue #2272
  rem reports RDNA4 regressions after Aug 31. Keep Bramble current, but hold the
  rem embedded WanGP source at the last Aug 31 commit until upstream is fixed.
  echo [COMPAT] Pinning WanGP runtime to Aug 31 known-good RDNA4 source...
  git fetch origin >> "%LOG%" 2>&1
  if errorlevel 1 (
    popd
    echo [ERROR] Could not fetch WanGP compatibility revision.
    goto :fail
  )
  git checkout --detach !WANGP_GFX1200_PIN! >> "%LOG%" 2>&1
  if errorlevel 1 (
    popd
    echo [ERROR] Could not pin WanGP to the RDNA4 compatibility revision.
    goto :fail
  )
) else (
  rem Non-gfx1200 systems continue following current WanGP.
  git checkout main >> "%LOG%" 2>&1
  git pull --ff-only >> "%LOG%" 2>&1
)

if "!AMD_GFX1200!"=="1" (
  rem RX 9060 XT compatibility stack: Windows + gfx1200 + ROCm 7.14.0.
  rem ROCm 7.14.1/10.0.0 have current RDNA4 kernel regressions during real
  rem model workloads even when simple GPU smoke tests pass.
  if not exist "!WANGP_GFX1200_MARKER!" (
    echo [REPAIR] Building WanGP specifically for RX 9060 XT / gfx1200...
    powershell -NoProfile -Command "$c=Get-NetTCPConnection -LocalPort 8020 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1; if($c){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$c.OwningProcess) -ErrorAction SilentlyContinue; if($p -and $p.CommandLine -match 'wangp_bridge:app'){Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue; Start-Sleep -Milliseconds 700}}"
    if exist "env_venv" rmdir /s /q "env_venv"
    py -3.12 -m venv "env_venv" >> "%LOG%" 2>&1
    if errorlevel 1 (
      popd
      echo [ERROR] Could not create WanGP Python 3.12 environment.
      goto :fail
    )
    set "WANGP_PYTHON=!WANGP_ROOT!\env_venv\Scripts\python.exe"
    "!WANGP_PYTHON!" -m pip install --upgrade pip >> "%LOG%" 2>&1
    if errorlevel 1 (
      popd
      goto :fail
    )
    echo Installing known-good ROCm 7.14.0 / PyTorch 2.12 gfx1200 wheels...
    "!WANGP_PYTHON!" -m pip install --index-url https://repo.amd.com/rocm/whl-multi-arch/ "torch[device-gfx1200]==2.12.0+rocm7.14.0" "torchvision[device-gfx1200]==0.27.0+rocm7.14.0" "torchaudio==2.11.0+rocm7.14.0" >> "%LOG%" 2>&1
    if errorlevel 1 (
      popd
      echo [ERROR] gfx1200 ROCm PyTorch installation failed. See install.log.
      goto :fail
    )
    "!WANGP_PYTHON!" -m pip install -r requirements.txt >> "%LOG%" 2>&1
    if errorlevel 1 (
      popd
      echo [ERROR] WanGP dependencies failed to install. See install.log.
      goto :fail
    )
    "!WANGP_PYTHON!" -m pip install fastapi uvicorn >> "%LOG%" 2>&1
    if errorlevel 1 (
      popd
      goto :fail
    )
  ) else (
    echo [SKIP] Verified Bramble gfx1200 ROCm environment marker found
  )
) else (
  if not exist "env_venv\Scripts\python.exe" (
    echo Running WanGP official automatic installer for the detected AMD GPU...
    py -3.12 setup.py install --env venv --auto >> "%LOG%" 2>&1
    if errorlevel 1 (
      popd
      echo [ERROR] WanGP official AMD auto-install failed. See install.log.
      goto :fail
    )
  ) else (
    echo [SKIP] WanGP active environment already exists
  )
  set "WANGP_PYTHON=!WANGP_ROOT!\env_venv\Scripts\python.exe"
  "!WANGP_PYTHON!" -m pip install fastapi uvicorn >> "%LOG%" 2>&1
  if errorlevel 1 (
    popd
    goto :fail
  )
)

if not exist "!WANGP_PYTHON!" (
  popd
  echo [ERROR] WanGP environment was not created.
  goto :fail
)

echo Verifying WanGP shared.api, pinned ROCm build and a real GPU kernel...
set "TORCH_ROCM_AOTRITON_ENABLE_EXPERIMENTAL=0"
set "AMD_GFX1200_VERIFY=!AMD_GFX1200!"
"!WANGP_PYTHON!" -c "import os,torch, torch.nn.functional as F; from shared.api import init; print('torch',torch.__version__); print('hip',getattr(torch.version,'hip',None)); print('gpu',torch.cuda.is_available()); print('device',torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'); assert '+rocm' in torch.__version__, 'CPU/non-ROCm PyTorch installed'; assert torch.cuda.is_available(), 'ROCm GPU unavailable'; assert (os.environ.get('AMD_GFX1200_VERIFY','0')!='1') or torch.__version__.startswith('2.12.0+rocm7.14.0'), 'RX 9060 XT requires pinned PyTorch 2.12.0+rocm7.14.0'; torch.backends.cuda.enable_flash_sdp(False); torch.backends.cuda.enable_mem_efficient_sdp(False); torch.backends.cuda.enable_math_sdp(True); x=torch.randn((256,256),device='cuda'); y=x@x; q=torch.randn((1,8,128,64),device='cuda',dtype=torch.float16); z=F.scaled_dot_product_attention(q,q,q); torch.cuda.synchronize(); print('matmul-smoke',float(y[0,0])); print('math-sdpa-smoke',tuple(z.shape));" >> "%LOG%" 2>&1
if errorlevel 1 (
  if exist "!WANGP_GFX1200_MARKER!" del /q "!WANGP_GFX1200_MARKER!" >nul 2>nul
  popd
  echo [ERROR] WanGP ROCm GPU kernel test failed. See install.log.
  goto :fail
)
if "!AMD_GFX1200!"=="1" > "!WANGP_GFX1200_MARKER!" echo gfx1200 rocm7.14.0 torch2.12 aug31-wangp verified %date% %time%
popd
echo [OK] Official WanGP AMD environment and real GPU kernel verified

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
echo [4/8] Installing backend packages and Brazilian Portuguese voice...
"backend\.venv\Scripts\python.exe" -m pip install --upgrade pip >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
"backend\.venv\Scripts\python.exe" -m pip install -r "backend\requirements.txt" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
"backend\.venv\Scripts\python.exe" -c "import fastapi, uvicorn, httpx, pydantic, PIL" >> "%LOG%" 2>&1
if errorlevel 1 goto :fail
if not exist "backend\.venv\Scripts\piper.exe" (
  echo [ERROR] Piper TTS was not installed correctly.
  goto :fail
)
if not exist "storage" mkdir "storage"
if not exist "storage\voices" mkdir "storage\voices"
if not exist "storage\voices\piper" mkdir "storage\voices\piper"

if not exist "storage\voices\piper\pt_BR-faber-medium.onnx" (
  echo Downloading Brazilian Portuguese pt-BR voice. This happens only once...
  "backend\.venv\Scripts\python.exe" -m piper.download_voices --data-dir "storage\voices\piper" pt_BR-faber-medium >> "%LOG%" 2>&1
  if errorlevel 1 (
    echo [ERROR] Brazilian Portuguese voice download failed. See install.log.
    goto :fail
  )
) else (
  echo [SKIP] Brazilian Portuguese voice model already downloaded
)

if not exist "storage\voices\piper\pt_BR-faber-medium.onnx" (
  echo [ERROR] Brazilian Portuguese .onnx voice file is missing after download.
  goto :fail
)
if not exist "storage\voices\piper\pt_BR-faber-medium.onnx.json" (
  echo [ERROR] Brazilian Portuguese voice config is missing after download.
  goto :fail
)

echo Testing Brazilian Portuguese voice with accented UTF-8 text...
> "storage\voices\piper\ptbr-test.txt" echo Esta é uma voz em português brasileiro. Coração, crianças, paciência e atenção.
type "storage\voices\piper\ptbr-test.txt" | "backend\.venv\Scripts\piper.exe" --model "storage\voices\piper\pt_BR-faber-medium.onnx" --config "storage\voices\piper\pt_BR-faber-medium.onnx.json" --output_file "storage\voices\piper\ptbr-install-test.wav" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo [ERROR] Brazilian Portuguese UTF-8 voice test failed. See install.log.
  goto :fail
)
if not exist "storage\voices\piper\ptbr-install-test.wav" (
  echo [ERROR] Brazilian Portuguese voice test did not create audio.
  goto :fail
)
del /q "storage\voices\piper\ptbr-install-test.wav" >nul 2>nul
del /q "storage\voices\piper\ptbr-test.txt" >nul 2>nul
echo [OK] Backend packages and pt-BR voice verified in UTF-8 mode

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
if not exist "backend\.venv\Scripts\piper.exe" goto :fail
if not exist "storage\voices\piper\pt_BR-faber-medium.onnx" goto :fail
if not exist "storage\voices\piper\pt_BR-faber-medium.onnx.json" goto :fail
if not exist "frontend\node_modules\.bin\vite.cmd" goto :fail

> ".bramble-installed" echo Installed %date% %time%
echo.
echo ============================================================
echo INSTALL COMPLETE - EVERYTHING VERIFIED
echo ============================================================
echo Backend Python     : FOUND
echo PT-BR Piper Voice  : FOUND
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
