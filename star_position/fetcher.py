"""科创板位置监控 —— 数据采集模块。

聚焦：判断科创50（000688）当前位置是「高位（危险）」还是「低位（可建仓）」。

数据源：
  1. 蛋卷基金 (danjuanfunds.com) — 科创50 当前 PE/PB + 完整历史分位（权威，
     乐咕/中证均无科创50 长历史估值，这是唯一可靠源）
  2. 新浪财经 — 科创50 历史日 K（价格分位 + 距高点回撤 + 均线）

网络说明：公司代理下东财不稳定，用 Session(trust_env=False) 直连。
数据仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

import datetime
import json
from typing import Dict, List, Optional

import requests

_SESSION = requests.Session()
_SESSION.trust_env = False

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}
_TIMEOUT = 25

STAR50_INDEX_CODE = "000688"
STAR50_DANJUAN_CODE = "SH000688"


class FetchError(RuntimeError):
    pass


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None


def _get(url, params=None, headers=None):
    h = {**_HEADERS, **(headers or {})}
    resp = _SESSION.get(url, params=params, headers=h, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# 1. 科创50 当前估值 + 历史分位（蛋卷基金）
# ---------------------------------------------------------------------------
def fetch_star50_valuation() -> Dict:
    """蛋卷基金：科创50 当前 PE/PB + 完整历史分位。"""
    url = "https://danjuanfunds.com/djapi/index_eva/dj"
    resp = _get(url, headers={"Referer": "https://danjuanfunds.com/"})
    data = resp.json()
    items = (data.get("data") or {}).get("items") or []
    for it in items:
        if it.get("index_code") == STAR50_DANJUAN_CODE:
            return {
                "name": it.get("name", "科创50"),
                "pe_ttm": _num(it.get("pe")),
                "pb": _num(it.get("pb")),
                "pe_percentile": _num(it.get("pe_percentile")),
                "pb_percentile": _num(it.get("pb_percentile")),
                "roe": _num(it.get("roe")),
                "dividend_yield": _num(it.get("yeild")),
                "eva_type": it.get("eva_type"),
            }
    raise FetchError(f"蛋卷接口未找到科创50 {STAR50_DANJUAN_CODE}")


# ---------------------------------------------------------------------------
# 2. 科创50 历史日 K（新浪）
# ---------------------------------------------------------------------------
def fetch_star50_kline(days: int = 6000) -> List[Dict]:
    """科创50 历史日 K（新浪），按日期升序。"""
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": "sh000688", "scale": "240", "ma": "no", "datalen": str(days)}
    resp = _get(url, params=params, headers={"Referer": "https://finance.sina.com.cn/"})
    raw = json.loads(resp.text)
    klines = []
    for r in raw:
        klines.append({
            "date": r["day"],
            "open": _num(r["open"]),
            "high": _num(r["high"]),
            "low": _num(r["low"]),
            "close": _num(r["close"]),
            "volume": _num(r["volume"]),
        })
    klines.sort(key=lambda x: x["date"])
    return klines


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def build_star50_dataset() -> Dict:
    """整合科创50 位置监控所需数据。"""
    return {
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "valuation": fetch_star50_valuation(),
        "kline": fetch_star50_kline(),
    }


if __name__ == "__main__":
    ds = build_star50_dataset()
    kl = ds["kline"]
    print(f"日K: {len(kl)} 条, {kl[0]['date']} ~ {kl[-1]['date']}, 最新 {kl[-1]['close']}")
    print(f"估值: {ds['valuation']}")
