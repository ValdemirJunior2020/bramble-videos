@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bramble Videos - Tests
set "QUIET=0"
if /i "%~1"=="/quiet" set "QUIET=1"

if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] Run INSTALL.bat first.
  if "%QUIET%"=="0" pause
  exit /b 1
)

call backend\.venv\Scripts\activate.bat
python -m compileall -q backend\app
if errorlevel 1 goto :fail_active
python -m pytest -q backend\tests
if errorlevel 1 goto :fail_active
deactivate

pushd frontend
call npm run build
if errorlevel 1 (
  popd
  goto :fail
)
popd

echo.
echo ALL BRAMBLE TESTS PASSED.
if "%QUIET%"=="0" pause
exit /b 0

:fail_active
deactivate
:fail
echo.
echo TEST FAILED. See the error above.
if "%QUIET%"=="0" pause
exit /b 1
