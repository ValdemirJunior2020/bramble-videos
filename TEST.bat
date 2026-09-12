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

echo [TEST] Compiling backend...
"backend\.venv\Scripts\python.exe" -m compileall -q "backend\app"
if errorlevel 1 goto :fail

echo [TEST] Running backend tests from backend folder...
pushd "backend"
".venv\Scripts\python.exe" -m pytest -q "tests"
set "PYTEST_RESULT=%ERRORLEVEL%"
popd
if not "%PYTEST_RESULT%"=="0" goto :fail

echo [TEST] Building frontend...
pushd "frontend"
call npm run build
set "NPM_RESULT=%ERRORLEVEL%"
popd
if not "%NPM_RESULT%"=="0" goto :fail

echo.
echo ALL BRAMBLE TESTS PASSED.
if "%QUIET%"=="0" pause
exit /b 0

:fail
echo.
echo TEST FAILED. See the error above.
if "%QUIET%"=="0" pause
exit /b 1
