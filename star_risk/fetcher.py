"""科创50（000688）位置危险度评估 —— 数据采集模块。

数据源（避开不稳定的东方财富 push 系列）：
    1. 蛋卷基金 (danjuanfunds.com) —— 科创50 当前 PE/PB 及**完整历史分位**（权威）
    2. 新浪财经 (sina.com.cn)      —— 科创50 历史日 K（均线、回撤、量能）
    3. 乐咕乐股 (legulegu.com)     —— 全市场 PE（资金面温度）

输出 dataset 结构与 gem_risk 包一致（current / kline / valuation_series / market_pe），
可直接复用 gem_risk.engine 的评分逻辑。

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import datetime
import json
from typing import Dict, List

import requests

# 复用 gem_risk 的基础请求封装
from gem_risk.fetcher import _get, FetchError, _num

# 科创50 指数代码
STAR50_INDEX_CODE = "000688"
STAR50_DANJUAN_CODE = "SH000688"


# ---------------------------------------------------------------------------
# 1. 科创50 当前估值 + 历史分位（蛋卷基金）
# ---------------------------------------------------------------------------
def fetch_star50_valuation() -> Dict:
    """从蛋卷基金获取科创50 当前估值与历史分位。"""
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
                "pe_over_history": _num(it.get("pe_over_history")),
                "pb_over_history": _num(it.get("pb_over_history")),
            }
    raise FetchError(f"蛋卷接口未找到科创50 {STAR50_DANJUAN_CODE}")


# ---------------------------------------------------------------------------
# 2. 科创50 历史日 K（新浪财经）
# ---------------------------------------------------------------------------
def fetch_star50_kline(days: int = 300) -> List[Dict]:
    """获取科创50 历史日 K 线（新浪），返回按日期升序的列表。"""
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
# 3. 全市场 PE（乐咕乐股，资金面温度）
# ---------------------------------------------------------------------------
def fetch_market_pe_history() -> List[Dict]:
    """获取全市场（沪深A股）历史 PE。"""
    import akshare as ak

    df = ak.stock_market_pe_lg(symbol="沪深A股")
    return [
        {"date": str(r["日期"]), "pe": _num(r["市盈率"])}
        for _, r in df.iterrows()
    ]


# ---------------------------------------------------------------------------
# 整合
# ---------------------------------------------------------------------------
def build_star50_dataset() -> Dict:
    """整合科创50 所有数据，输出与 gem_risk 一致的 dataset 结构。"""
    val = fetch_star50_valuation()

    dataset = {
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "index_code": STAR50_INDEX_CODE,
        "index_name": "科创50",
        # 与 gem_risk.engine 对齐的结构
        "current": {
            "code": STAR50_INDEX_CODE,
            "name": val["name"],
            "pe_ttm": val["pe_ttm"],
            "pb": val["pb"],
        },
        # 估值历史序列：蛋卷只给分位不给序列，这里用分位直接承载
        # engine 里 pe_percentile 由 current 直读（见下方 extra）
        "valuation_series": {"pe": [], "pb": []},
        # 直接把蛋卷的分位塞进 extra，engine 会优先用 current 里的分位
        "extra": {
            "pe_percentile": val["pe_percentile"],
            "pb_percentile": val["pb_percentile"],
            "roe": val["roe"],
            "dividend_yield": val["dividend_yield"],
            "eva_type": val["eva_type"],
            "pe_over_history": val["pe_over_history"],
            "pb_over_history": val["pb_over_history"],
        },
        "kline": fetch_star50_kline(),
        "market_pe": fetch_market_pe_history(),
    }
    return dataset
