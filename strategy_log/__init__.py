"""strategy_log —— 每日策略数据台账。

把各策略每天跑出的核心信号/指标统一写入 SQLite，供后台统一查看与趋势分析。

存储位置：strategy_log/data.db（SQLite）
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DATA_DIR, "data.db")

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy    TEXT NOT NULL,              -- 策略名，如 gem_position
    run_date    TEXT NOT NULL,              -- 运行日期 YYYY-MM-DD
    run_at      TEXT NOT NULL,              -- 运行时间戳
    payload     TEXT NOT NULL               -- JSON 快照（完整指标字典）
);
CREATE INDEX IF NOT EXISTS idx_runs_strategy_date ON runs(strategy, run_date);
"""


def _conn() -> sqlite3.Connection:
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    return c


def init_db() -> None:
    with _lock:
        c = _conn()
        try:
            c.executescript(_SCHEMA)
            c.commit()
        finally:
            c.close()


def record(strategy: str, data: dict, run_date: str | None = None) -> int:
    """记录一次策略运行结果。

    strategy: 策略名（如 "gem_position"）
    data:     引擎返回的结构化字典（数值/字符串均可，自动 JSON 序列化）
    run_date: 运行日期，默认今天
    返回记录 id。
    """
    init_db()
    run_date = run_date or datetime.now().strftime("%Y-%m-%d")
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = json.dumps(_sanitize(data), ensure_ascii=False, default=str)
    with _lock:
        c = _conn()
        try:
            cur = c.execute(
                "INSERT INTO runs(strategy, run_date, run_at, payload) VALUES(?,?,?,?)",
                (strategy, run_date, run_at, payload),
            )
            c.commit()
            return cur.lastrowid
        finally:
            c.close()


def _sanitize(obj):
    """把不可 JSON 序列化的值（numpy 类型、None、嵌套 dict/list）规整。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, (int, float)):
        return obj
    # numpy 标量
    if hasattr(obj, "item"):
        try:
            return _sanitize(obj.item())
        except Exception:
            pass
    return obj


def list_strategies() -> list[str]:
    """所有记录过的策略名。"""
    init_db()
    c = _conn()
    try:
        rows = c.execute("SELECT DISTINCT strategy FROM runs ORDER BY strategy").fetchall()
        return [r["strategy"] for r in rows]
    finally:
        c.close()


def list_dates(strategy: str | None = None) -> list[str]:
    """所有运行日期（可按策略过滤）。"""
    init_db()
    c = _conn()
    try:
        if strategy:
            rows = c.execute(
                "SELECT DISTINCT run_date FROM runs WHERE strategy=? ORDER BY run_date",
                (strategy,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT DISTINCT run_date FROM runs ORDER BY run_date").fetchall()
        return [r["run_date"] for r in rows]
    finally:
        c.close()


def latest(strategy: str) -> dict | None:
    """某策略最新一次运行的快照。"""
    init_db()
    c = _conn()
    try:
        row = c.execute(
            "SELECT * FROM runs WHERE strategy=? ORDER BY run_date DESC, id DESC LIMIT 1",
            (strategy,),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        c.close()


def history(strategy: str, limit: int = 500) -> list[dict]:
    """某策略的历史快照（按日期升序）。"""
    init_db()
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM runs WHERE strategy=? ORDER BY run_date ASC, id ASC LIMIT ?",
            (strategy, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        c.close()


def series(strategy: str, metric: str, limit: int = 500) -> list[dict]:
    """提取某策略某个指标的时间序列（用于画趋势图）。

    指标用点号路径访问嵌套字典，如 "position_temp"、"components.pe"。
    返回 [{date, value}]，value 为数值时保留，否则转字符串。
    """
    init_db()
    c = _conn()
    try:
        rows = c.execute(
            "SELECT run_date, payload FROM runs WHERE strategy=? ORDER BY run_date ASC LIMIT ?",
            (strategy, limit),
        ).fetchall()
    finally:
        c.close()

    out = []
    for r in rows:
        payload = json.loads(r["payload"])
        val = _get_path(payload, metric)
        if val is None:
            continue
        out.append({"date": r["run_date"], "value": val})
    return out


def _get_path(obj: dict, path: str):
    """按点号路径取嵌套值。"""
    cur = obj
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["payload"] = json.loads(d["payload"]) if d.get("payload") else {}
    return d


def stats() -> dict:
    """台账概览：策略数、天数、记录数。"""
    init_db()
    c = _conn()
    try:
        total = c.execute("SELECT COUNT(*) n FROM runs").fetchone()["n"]
        strategies = c.execute("SELECT COUNT(DISTINCT strategy) n FROM runs").fetchone()["n"]
        days = c.execute("SELECT COUNT(DISTINCT run_date) n FROM runs").fetchone()["n"]
        return {"total": total, "strategies": strategies, "days": days}
    finally:
        c.close()
