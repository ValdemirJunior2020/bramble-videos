@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Bramble Videos - Tests

if not exist "backend\.venv\Scripts\python.exe" (
  echo [ERROR] Run INSTALL.bat first.
  pause
  exit /b 1
)

call backend\.venv\Scripts\activate.bat
python -m compileall -q backend\app || goto :fail
python -m pytest -q backend\tests || goto :fail
deactivate

pushd frontend
call npm run build || (popd & goto :fail)
popd

echo.
echo ALL BRAMBLE TESTS PASSED.
pause
exit /b 0

:fail
echo.
echo TEST FAILED. See the error above.
pause
exit /b 1
