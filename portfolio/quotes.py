"""实时行情获取 —— 新浪行情接口批量拉取。

新浪 hq.sinajs.cn 单次可查多只股票，字段（GBK 编码，逗号分隔）：
  0 名称
  1 今开
  2 昨收
  3 现价（最新成交价）
  4 最高
  5 最低
  6 买一价
  7 卖一价
  8 成交量（股）
  9 成交额（元）
  ...
  30 日期
  31 时间

据此计算：涨跌幅、涨跌额、市值、浮动盈亏等。
"""

from __future__ import annotations

import re

import requests

SINA_URL = "https://hq.sinajs.cn/list="
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://finance.sina.com.cn",
}

_INDEX_PREFIX = {"sh000", "sz399", "sh000001", "sh000300", "sz399001", "sz399006"}


def _is_index(code: str) -> bool:
    return code.startswith(("sh000", "sz399"))


def fetch_quotes(codes: list[str]) -> dict[str, dict]:
    """批量拉取实时行情。返回 {code: quote}，失败的代码不在结果中。"""
    codes = [c for c in codes if c]
    if not codes:
        return {}
    result: dict[str, dict] = {}
    session = requests.Session()
    session.trust_env = False
    # 分批，每批 80 只，避免 URL 过长
    for i in range(0, len(codes), 80):
        batch = codes[i:i + 80]
        try:
            r = session.get(SINA_URL + ",".join(batch), headers=HEADERS, timeout=15)
            r.encoding = "gbk"
            result.update(_parse(r.text))
        except requests.RequestException:
            continue
    return result


def _parse(text: str) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for m in re.finditer(r'hq_str_(\w+)="([^"]*)"', text):
        code, raw = m.group(1), m.group(2)
        if not raw:
            continue
        parts = raw.split(",")
        if len(parts) < 32:
            continue
        try:
            name = parts[0]
            open_ = float(parts[1])
            prev_close = float(parts[2])
            price = float(parts[3])
            high = float(parts[4])
            low = float(parts[5])
            volume = float(parts[8])          # 股
            amount = float(parts[9])          # 元
            date = parts[30]
            time_ = parts[31]
        except (ValueError, IndexError):
            continue

        if price <= 0:
            continue

        change = price - prev_close
        pct = (change / prev_close * 100) if prev_close else 0.0
        out[code] = {
            "code": code,
            "name": name,
            "price": round(price, 3),
            "prev_close": round(prev_close, 3),
            "open": round(open_, 3),
            "high": round(high, 3),
            "low": round(low, 3),
            "change": round(change, 3),
            "pct": round(pct, 2),
            "volume": volume,
            "amount": amount,
            "date": date,
            "time": time_,
            "is_index": _is_index(code),
        }
    return out


def enrich_positions(positions: list[dict]) -> dict:
    """给持仓列表补充行情与盈亏字段，并计算汇总。

    返回 { "positions": [...], "summary": {...} }
    """
    codes = [p["code"] for p in positions]
    quotes = fetch_quotes(codes)

    rows = []
    total_cost = 0.0
    total_value = 0.0
    for p in positions:
        q = quotes.get(p["code"])
        cost = float(p["cost"])
        shares = float(p["shares"])
        cost_amount = cost * shares
        total_cost += cost_amount
        if q is None:
            rows.append({
                **p,
                "price": None,
                "pct": None,
                "market_value": round(cost_amount, 2),
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "weight": None,
                "quote_ok": False,
            })
            total_value += cost_amount
            continue
        price = q["price"]
        mv = price * shares
        pnl = mv - cost_amount
        pnl_pct = (pnl / cost_amount * 100) if cost_amount else 0.0
        total_value += mv
        rows.append({
            **p,
            "name": p.get("name") or q["name"],
            "price": price,
            "pct": q["pct"],
            "change": q["change"],
            "market_value": round(mv, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "weight": None,  # 权重后面统一算
            "quote_ok": True,
            "quote_date": q["date"],
        })

    total_pnl = total_value - total_cost
    total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0

    for r in rows:
        if total_value > 0 and r["quote_ok"]:
            r["weight"] = round(r["market_value"] / total_value * 100, 2)

    # 当日盈亏（按昨收到现价的变动 × 股数）
    day_pnl = 0.0
    for r in rows:
        if r.get("quote_ok"):
            day_pnl += (r.get("change") or 0.0) * float(r["shares"])

    summary = {
        "total_cost": round(total_cost, 2),
        "total_value": round(total_value, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "day_pnl": round(day_pnl, 2),
        "count": len(positions),
    }
    return {"positions": rows, "summary": summary}
