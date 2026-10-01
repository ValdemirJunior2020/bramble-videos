@echo off
setlocal EnableExtensions
echo Stopping Bramble-owned local services...
for %%P in (5174 8010 8020) do (
  for /f "tokens=5" %%A in ('netstat -aon ^| findstr ":%%P " ^| findstr "LISTENING"') do (
    taskkill /PID %%A /F >nul 2>nul
  )
)
echo Bramble frontend, backend and WanGP bridge stopped.
echo Shared Ollama and Chatterbox were left running to avoid interrupting other local projects.
pause
