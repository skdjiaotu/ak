@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在停止前后端服务...
.venv\Scripts\python.exe start.py --stop
echo.
pause >nul
