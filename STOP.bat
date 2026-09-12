@echo off
for %%P in (5174 8010) do (
  for /f "tokens=5" %%A in ('netstat -aon ^| findstr ":%%P " ^| findstr "LISTENING"') do taskkill /PID %%A /F >nul 2>nul
)
echo Bramble frontend/backend stopped. Ollama and ComfyUI were left running so your other working projects are not interrupted.
pause
