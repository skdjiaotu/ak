"""一键启动脚本 —— 同时拉起后端 API 与前端 Vite。

用法：
    .venv/Scripts/python.exe start.py          # 启动前后端两个进程
    .venv/Scripts/python.exe start.py --stop   # 停止所有相关进程

功能：
    1. 自动清理占用 8765 / 5173 端口的残留进程
    2. 后台启动后端（portfolio.server，端口 8765）
    3. 后台启动前端（frontend 的 vite dev，端口 5173）
    4. 首次运行自动安装前端依赖（npm install）
    5. 打印访问地址
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

BACKEND_PORT = 8765
FRONTEND_PORT = 5173

# Windows 下让子进程脱离父进程生命周期（否则父脚本退出后子进程会被回收）
_DETACH = getattr(subprocess, "DETACHED_PROCESS", 0)
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
_CREATIONFLAGS = _DETACH | _NEW_GROUP


def _find_pids(port: int) -> list[str]:
    """查找占用指定端口的 PID 列表（Windows）。"""
    pids = []
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, timeout=15,
        ).stdout.decode("gbk", errors="ignore")
        for line in out.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                pids.append(parts[-1])
    except Exception:
        pass
    return pids


def _kill(port: int) -> None:
    """终止占用指定端口的进程。"""
    for pid in _find_pids(port):
        try:
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True, timeout=10)
            print(f"  已清理端口 {port} 的残留进程 (PID {pid})")
        except Exception:
            pass


def _start_backend() -> subprocess.Popen:
    """启动后端。"""
    cmd = [str(PYTHON), "-m", "portfolio.server", str(BACKEND_PORT)]
    return subprocess.Popen(
        cmd, cwd=str(ROOT),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_CREATIONFLAGS,
    )


def _start_frontend() -> subprocess.Popen:
    """启动前端（首次先装依赖）。"""
    node_modules = FRONTEND_DIR / "node_modules"
    if not node_modules.exists():
        print("  首次运行，正在安装前端依赖（npm install，可能需要几分钟）...")
        subprocess.run(["npm", "install"], cwd=str(FRONTEND_DIR), check=True)

    npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
    cmd = [npm_cmd, "run", "dev"]
    return subprocess.Popen(
        cmd, cwd=str(FRONTEND_DIR),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=_CREATIONFLAGS,
    )


def _wait_port(port: int, timeout: int = 30) -> bool:
    """等待端口就绪。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _find_pids(port):
            return True
        time.sleep(0.5)
    return False


def start() -> None:
    print("=" * 56)
    print("  个人投资管理后台 · 一键启动")
    print("=" * 56)

    if not PYTHON.exists():
        print("❌ 未找到虚拟环境 .venv，请先创建。")
        sys.exit(1)

    # 1. 清理端口
    print("\n[1/4] 清理残留进程...")
    _kill(BACKEND_PORT)
    _kill(FRONTEND_PORT)
    time.sleep(1)

    # 2. 启动后端
    print(f"[2/4] 启动后端 API（端口 {BACKEND_PORT}）...")
    _start_backend()

    # 3. 启动前端
    print(f"[3/4] 启动前端 Vite（端口 {FRONTEND_PORT}）...")
    _start_frontend()

    # 4. 等待就绪
    print("[4/4] 等待服务就绪...")
    backend_ok = _wait_port(BACKEND_PORT)
    frontend_ok = _wait_port(FRONTEND_PORT)

    print()
    if backend_ok:
        print(f"  ✅ 后端 API : http://127.0.0.1:{BACKEND_PORT}  (文档 http://127.0.0.1:{BACKEND_PORT}/docs)")
    else:
        print(f"  ⚠️  后端未在 {BACKEND_PORT} 就绪，请检查日志")
    if frontend_ok:
        print(f"  ✅ 前端页面 : http://localhost:{FRONTEND_PORT}")
    else:
        print(f"  ⚠️  前端未在 {FRONTEND_PORT} 就绪，请检查日志")

    print()
    print("  请在浏览器打开上面的「前端页面」地址使用。")
    print("  停止服务：关闭本窗口，或运行 `.venv/Scripts/python.exe start.py --stop`")
    print("=" * 56)


def stop() -> None:
    print("正在停止前后端服务...")
    _kill(BACKEND_PORT)
    _kill(FRONTEND_PORT)
    print("已停止。")


if __name__ == "__main__":
    if "--stop" in sys.argv:
        stop()
    else:
        start()
