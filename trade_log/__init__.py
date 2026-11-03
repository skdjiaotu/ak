"""trade_log —— 交易日志台账。

记录每次交易（买入/卖出）的原因与复盘，用于事后总结交易纪律。

存储：trade_log/data.db（SQLite）
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
CREATE TABLE IF NOT EXISTS trades (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL,          -- 股票代码（归一化后）
    name        TEXT DEFAULT '',        -- 名称
    direction   TEXT NOT NULL,          -- buy 买入 / sell 卖出
    trade_date  TEXT NOT NULL,          -- 交易日期 YYYY-MM-DD
    price       REAL NOT NULL,          -- 成交价
    shares      REAL NOT NULL,          -- 数量（股）
    amount      REAL NOT NULL,          -- 金额 = price * shares
    reason      TEXT DEFAULT '',        -- 交易原因（核心）
    review      TEXT DEFAULT '',        -- 事后复盘
    tags        TEXT DEFAULT '[]',      -- 标签（JSON 数组）
    note        TEXT DEFAULT '',        -- 备注
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_date ON trades(trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_code ON trades(code);
"""

DIRECTIONS = ("buy", "sell")
DIRECTION_CN = {"buy": "买入", "sell": "卖出"}


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


def _normalize_code(code: str) -> str:
    code = (code or "").strip().lower()
    if not code:
        return ""
    if code[:2] in ("sh", "sz", "bj"):
        return code
    digits = "".join(ch for ch in code if ch.isdigit())
    if digits.startswith(("6", "9", "5")):
        return "sh" + digits
    if digits.startswith(("0", "3", "1", "2")):
        return "sz" + digits
    if digits.startswith(("4", "8")):
        return "bj" + digits
    return digits


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except json.JSONDecodeError:
        d["tags"] = []
    d["direction_cn"] = DIRECTION_CN.get(d["direction"], d["direction"])
    return d


def add(item: dict) -> dict:
    """新增一笔交易。"""
    init_db()
    code = _normalize_code(item.get("code", ""))
    if not code:
        raise ValueError("股票代码不能为空")
    direction = item.get("direction", "buy")
    if direction not in DIRECTIONS:
        raise ValueError("方向必须是 buy 或 sell")
    price = float(item.get("price", 0) or 0)
    shares = float(item.get("shares", 0) or 0)
    if price <= 0:
        raise ValueError("成交价必须大于 0")
    if shares <= 0:
        raise ValueError("数量必须大于 0")
    trade_date = item.get("trade_date") or datetime.now().strftime("%Y-%m-%d")
    tags = item.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    amount = round(price * shares, 2)

    with _lock:
        c = _conn()
        try:
            cur = c.execute(
                """INSERT INTO trades(code, name, direction, trade_date, price, shares,
                   amount, reason, review, tags, note, created_at, updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (code, (item.get("name") or "").strip(), direction, trade_date,
                 price, shares, amount, (item.get("reason") or "").strip(),
                 (item.get("review") or "").strip(), json.dumps(tags, ensure_ascii=False),
                 (item.get("note") or "").strip(), now, now),
            )
            c.commit()
            rid = cur.lastrowid
        finally:
            c.close()
    return get(rid)


def get(trade_id: int) -> dict | None:
    init_db()
    c = _conn()
    try:
        row = c.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        c.close()


def update(trade_id: int, item: dict) -> dict | None:
    """更新一笔交易。"""
    init_db()
    existing = get(trade_id)
    if existing is None:
        return None
    merged = dict(existing)
    for k in ("code", "name", "direction", "trade_date", "price", "shares",
              "reason", "review", "note"):
        if k in item and item[k] is not None:
            merged[k] = item[k]
    if "tags" in item and item["tags"] is not None:
        tags = item["tags"]
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        merged["tags"] = tags
    merged["code"] = _normalize_code(merged.get("code", ""))
    if merged["direction"] not in DIRECTIONS:
        raise ValueError("方向必须是 buy 或 sell")
    merged["price"] = float(merged["price"])
    merged["shares"] = float(merged["shares"])
    merged["amount"] = round(merged["price"] * merged["shares"], 2)
    merged["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tags = merged.get("tags") or []
    if isinstance(tags, list):
        tags_json = json.dumps(tags, ensure_ascii=False)
    else:
        tags_json = "[]"

    with _lock:
        c = _conn()
        try:
            c.execute(
                """UPDATE trades SET code=?, name=?, direction=?, trade_date=?, price=?,
                   shares=?, amount=?, reason=?, review=?, tags=?, note=?, updated_at=?
                   WHERE id=?""",
                (merged["code"], merged.get("name", ""), merged["direction"],
                 merged["trade_date"], merged["price"], merged["shares"],
                 merged["amount"], merged.get("reason", ""), merged.get("review", ""),
                 tags_json, merged.get("note", ""), merged["updated_at"], trade_id),
            )
            c.commit()
        finally:
            c.close()
    return get(trade_id)


def remove(trade_id: int) -> bool:
    init_db()
    with _lock:
        c = _conn()
        try:
            cur = c.execute("DELETE FROM trades WHERE id=?", (trade_id,))
            c.commit()
            return cur.rowcount > 0
        finally:
            c.close()


def list_all(limit: int = 500, offset: int = 0) -> list[dict]:
    init_db()
    c = _conn()
    try:
        rows = c.execute(
            "SELECT * FROM trades ORDER BY trade_date DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        c.close()


def stats() -> dict:
    """交易统计：笔数、买入/卖出笔数、总买入金额、总卖出金额、净额。"""
    init_db()
    c = _conn()
    try:
        total = c.execute("SELECT COUNT(*) n FROM trades").fetchone()["n"]
        buy = c.execute("SELECT COUNT(*) n FROM trades WHERE direction='buy'").fetchone()["n"]
        sell = c.execute("SELECT COUNT(*) n FROM trades WHERE direction='sell'").fetchone()["n"]
        buy_amt = c.execute(
            "SELECT COALESCE(SUM(amount),0) a FROM trades WHERE direction='buy'").fetchone()["a"]
        sell_amt = c.execute(
            "SELECT COALESCE(SUM(amount),0) a FROM trades WHERE direction='sell'").fetchone()["a"]
        return {
            "total": total,
            "buy": buy,
            "sell": sell,
            "buy_amount": round(buy_amt, 2),
            "sell_amount": round(sell_amt, 2),
            "net_amount": round(sell_amt - buy_amt, 2),
        }
    finally:
        c.close()
