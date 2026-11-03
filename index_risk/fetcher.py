"""A 股宽基指数位置危险度评估 —— 统一数据采集模块。

用一张指数配置表驱动，支持任意宽基指数。数据源：

    1. 蛋卷基金 (danjuanfunds.com) —— 指数当前 PE/PB 及完整历史分位（权威）
    2. 新浪财经 (sina.com.cn)      —— 指数历史日 K（均线、回撤、量能）
    3. 乐咕乐股 (legulegu.com)     —— 全市场 PE（资金面温度）

相比之前 gem_risk / star_risk 的分立实现，本模块把"蛋卷估值 + 新浪 K 线"抽成
通用函数，新增指数只需在 INDEX_CONFIG 加一行配置。

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import datetime
import json
from typing import Dict, List

from gem_risk.fetcher import _get, FetchError, _num

# ---------------------------------------------------------------------------
# 指数配置表：新增指数只需加一行
#   code          指数代码
#   name          中文名
#   danjuan_code  蛋卷接口的 index_code
#   sina_symbol   新浪 K 线的 symbol
# ---------------------------------------------------------------------------
INDEX_CONFIG = {
    "399006": {
        "name": "创业板指",
        "danjuan_code": "SZ399006",
        "sina_symbol": "sz399006",
    },
    "000688": {
        "name": "科创50",
        "danjuan_code": "SH000688",
        "sina_symbol": "sh000688",
    },
    "399001": {
        "name": "深证成指",
        "danjuan_code": "SZ399001",
        "sina_symbol": "sz399001",
    },
    "000300": {
        "name": "沪深300",
        "danjuan_code": "SH000300",
        "sina_symbol": "sh000300",
    },
    "000016": {
        "name": "上证50",
        "danjuan_code": "SH000016",
        "sina_symbol": "sh000016",
    },
    "000905": {
        "name": "中证500",
        "danjuan_code": "SH000905",
        "sina_symbol": "sh000905",
    },
}


def _danjuan_items() -> List[dict]:
    """一次性拉取蛋卷全部指数估值（缓存于进程内）。"""
    global _DJ_CACHE
    if "_DJ_CACHE" in globals() and _DJ_CACHE is not None:
        return _DJ_CACHE
    url = "https://danjuanfunds.com/djapi/index_eva/dj"
    resp = _get(url, headers={"Referer": "https://danjuanfunds.com/"})
    data = resp.json()
    _DJ_CACHE = (data.get("data") or {}).get("items") or []
    return _DJ_CACHE


def fetch_valuation(code: str) -> Dict:
    """从蛋卷基金获取指数当前估值与完整历史分位。"""
    cfg = INDEX_CONFIG[code]
    for it in _danjuan_items():
        if it.get("index_code") == cfg["danjuan_code"]:
            return {
                "name": it.get("name", cfg["name"]),
                "pe_ttm": _num(it.get("pe")),
                "pb": _num(it.get("pb")),
                "pe_percentile": _num(it.get("pe_percentile")),
                "pb_percentile": _num(it.get("pb_percentile")),
                "roe": _num(it.get("roe")),
                "dividend_yield": _num(it.get("yeild")),
                "eva_type": it.get("eva_type"),
            }
    raise FetchError(f"蛋卷接口未找到 {cfg['name']} {cfg['danjuan_code']}")


def fetch_kline(code: str, days: int = 300) -> List[Dict]:
    """获取指数历史日 K 线（新浪），返回按日期升序的列表。"""
    cfg = INDEX_CONFIG[code]
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": cfg["sina_symbol"], "scale": "240", "ma": "no", "datalen": str(days)}
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


def fetch_market_pe_history() -> List[Dict]:
    """获取全市场（沪深A股）历史 PE。"""
    import akshare as ak

    df = ak.stock_market_pe_lg(symbol="沪深A股")
    return [
        {"date": str(r["日期"]), "pe": _num(r["市盈率"])}
        for _, r in df.iterrows()
    ]


def build_index_dataset(code: str) -> Dict:
    """整合单个指数的所有数据，输出与评分引擎对齐的 dataset 结构。"""
    cfg = INDEX_CONFIG[code]
    val = fetch_valuation(code)

    return {
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "index_code": code,
        "index_name": cfg["name"],
        "current": {
            "code": code,
            "name": val["name"],
            "pe_ttm": val["pe_ttm"],
            "pb": val["pb"],
        },
        "valuation_series": {"pe": [], "pb": []},
        "extra": {
            "pe_percentile": val["pe_percentile"],
            "pb_percentile": val["pb_percentile"],
            "roe": val["roe"],
            "dividend_yield": val["dividend_yield"],
            "eva_type": val["eva_type"],
        },
        "kline": fetch_kline(code),
        "market_pe": fetch_market_pe_history(),
    }


def build_all_datasets() -> Dict[str, Dict]:
    """一次构建所有已配置指数的数据集（用于对比看板）。"""
    return {code: build_index_dataset(code) for code in INDEX_CONFIG}
