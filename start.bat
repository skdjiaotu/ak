@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在启动个人投资管理后台（前后端分离）...
echo.

.venv\Scripts\python.exe start.py

echo.
echo 按任意键关闭本窗口（会保留后台服务进程）。
pause >nul
