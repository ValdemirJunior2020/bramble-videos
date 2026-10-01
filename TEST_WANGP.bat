@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "WANGP_ROOT=%~dp0runtime\WanGP"
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do if /i "%%A"=="WANGP_ROOT" set "WANGP_ROOT=%%B"
)
if not "%WANGP_ROOT:~1,1%"==":" set "WANGP_ROOT=%~dp0%WANGP_ROOT%"
set "WANGP_PYTHON=%WANGP_ROOT%\wan2gp-env\Scripts\python.exe"
if not exist "%WANGP_PYTHON%" (
  echo [ERROR] WanGP environment is missing. Run INSTALL.bat first.
  pause
  exit /b 1
)
set "WANGP_ROOT=%WANGP_ROOT%"
"%WANGP_PYTHON%" "%~dp0backend\wangp_smoke.py"
if errorlevel 1 (
  echo.
  echo WANGP SMOKE TEST FAILED.
  pause
  exit /b 1
)
echo.
echo WANGP SMOKE TEST PASSED.
pause
