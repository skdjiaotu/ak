"""持仓数据模型与 JSON 持久化。

持仓字段：
    code      股票代码（如 sh600519 / sz000858）
    name      名称（可留空，行情返回时自动补全）
    cost      持仓成本价（元/股）
    shares    持仓数量（股）
    bought_at 买入日期（可选，YYYY-MM-DD）
    note      备注（可选）

存储：portfolio/data.json，增删改查均由本模块负责，保证读写一致性。
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime

DATA_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(DATA_DIR, "data.json")

_lock = threading.Lock()

FIELDS = ("code", "name", "cost", "shares", "bought_at", "note")


def _normalize_code(code: str) -> str:
    """把用户输入的各种代码写法归一成 新浪 代码格式 sh600519 / sz000858 / bj..."""
    code = (code or "").strip().lower()
    if not code:
        return ""
    # 已经是带前缀的
    if code[:2] in ("sh", "sz", "bj"):
        return code
    # 纯数字，按规则推断市场
    digits = "".join(ch for ch in code if ch.isdigit())
    if digits.startswith(("6", "9", "5")):
        return "sh" + digits
    if digits.startswith(("0", "3", "1", "2")):
        return "sz" + digits
    if digits.startswith(("4", "8")):
        return "bj" + digits
    return digits


def load() -> list[dict]:
    """读取全部持仓，返回列表。"""
    if not os.path.exists(DATA_PATH):
        return []
    with _lock:
        try:
            with open(DATA_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                return []
            return data
        except (json.JSONDecodeError, OSError):
            return []


def _save(data: list[dict]) -> None:
    with _lock:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def add(item: dict) -> dict:
    """新增一笔持仓。code 归一化，校验数值。返回规范化后的记录。"""
    code = _normalize_code(item.get("code", ""))
    if not code:
        raise ValueError("股票代码不能为空")

    cost = float(item.get("cost", 0) or 0)
    shares = float(item.get("shares", 0) or 0)
    if cost <= 0:
        raise ValueError("成本价必须大于 0")
    if shares <= 0:
        raise ValueError("持仓数量必须大于 0")

    rec = {
        "code": code,
        "name": (item.get("name") or "").strip(),
        "cost": round(cost, 4),
        "shares": round(shares, 2),
        "bought_at": (item.get("bought_at") or "").strip(),
        "note": (item.get("note") or "").strip(),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    data = load()
    # 同一代码已存在则更新
    for i, r in enumerate(data):
        if r.get("code") == code:
            data[i] = rec
            _save(data)
            return rec
    data.append(rec)
    _save(data)
    return rec


def update(code: str, item: dict) -> dict | None:
    """更新指定代码的持仓。返回更新后的记录，不存在则返回 None。"""
    code = _normalize_code(code)
    data = load()
    for i, r in enumerate(data):
        if r.get("code") == code:
            merged = dict(r)
            for k in FIELDS:
                if k in item and item[k] is not None:
                    merged[k] = item[k]
            merged["code"] = code
            merged["cost"] = round(float(merged.get("cost", 0) or 0), 4)
            merged["shares"] = round(float(merged.get("shares", 0) or 0), 2)
            merged["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            data[i] = merged
            _save(data)
            return merged
    return None


def remove(code: str) -> bool:
    """删除指定代码的持仓。返回是否删除成功。"""
    code = _normalize_code(code)
    data = load()
    new = [r for r in data if r.get("code") != code]
    if len(new) == len(data):
        return False
    _save(new)
    return True


def clear() -> int:
    """清空全部持仓，返回删除条数。"""
    data = load()
    n = len(data)
    _save([])
    return n
