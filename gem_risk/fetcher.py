"""
创业板位置危险度评估 —— 数据采集模块。

从多个公开数据源采集创业板指数相关的估值、技术、情绪/资金数据：

数据源：
    1. 国证指数官网 (cnindex.com.cn)   — 创业板指当前 PE（官方权威）
    2. 乐咕乐股 (legulegu.com)         — 创业板50 历史 PE/PB 序列（算分位）
    3. 新浪财经 (sina.com.cn)          — 创业板指历史日 K（算均线乖离、回撤、成交额）
    4. 乐咕乐股                         — 全市场 PE（算股债性价比 ERP）

网络说明：
    公司代理网络下东方财富 push 系列接口不稳定，故本模块优先使用新浪 + 国证 + 乐咕乐股
    等稳定数据源，并通过 Session(trust_env=False) 绕过系统代理直连。

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# 基础配置
# ---------------------------------------------------------------------------
_SESSION = requests.Session()
_SESSION.trust_env = False  # 绕过系统代理，直连更稳定

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}
_TIMEOUT = 25

# 创业板指（399006）与创业板50（399673）固定代码
GEM_INDEX_CODE = "399006"
GEM50_INDEX_CODE = "399673"


class FetchError(RuntimeError):
    """数据抓取失败异常。"""


def _get(url: str, params: dict = None, headers: dict = None, encoding: str = None):
    """GET 请求，返回 Response 或抛 FetchError。"""
    h = {**_HEADERS, **(headers or {})}
    try:
        resp = _SESSION.get(url, params=params, headers=h, timeout=_TIMEOUT)
        resp.raise_for_status()
        if encoding:
            resp.encoding = encoding
        return resp
    except requests.RequestException as e:
        raise FetchError(f"网络请求失败: {url} — {e}") from e


# ---------------------------------------------------------------------------
# 1. 创业板指当前估值（国证指数官网）
# ---------------------------------------------------------------------------
def fetch_gem_current_valuation() -> Dict:
    """获取创业板指当前 PE 滚动、收盘点位、涨跌幅、成交额（国证官方）。

    国证接口字段（小写）：indexcode/indexname/closeingPoint/percent/
    peDynamic/volume/amount/totalMarketValue/freeMarketValue
    数值单位：volume 需 /1e5（万手），amount/marketValue 需 /1e8（亿元）。
    """
    url = "https://www.cnindex.com.cn/index/indexList"
    params = {"channelCode": "-1", "rows": "2000", "pageNum": "1"}
    resp = _get(url, params=params, headers={"Referer": "https://www.cnindex.com.cn/"})

    data = resp.json()
    items = (data.get("data") or {}).get("rows") or []

    for it in items:
        code = str(it.get("indexcode") or "")
        if code == GEM_INDEX_CODE:
            return {
                "code": GEM_INDEX_CODE,
                "name": it.get("indexname") or "创业板指",
                "close": _num(it.get("closeingPoint")),
                "change_pct": _num(it.get("percent")),
                "pe_ttm": _num(it.get("peDynamic")),
                "pe_static": _num(it.get("peStatic")),
                "pb": _num(it.get("pb")),
                # 成交额：原始单位元，转亿元
                "turnover": _num(it.get("amount")) / 1e8,
                "total_mv": _num(it.get("totalMarketValue")) / 1e8,
                "float_mv": _num(it.get("freeMarketValue")) / 1e8,
            }
    raise FetchError(f"国证指数接口未找到创业板指 {GEM_INDEX_CODE}")


# ---------------------------------------------------------------------------
# 2. 创业板50 历史 PE/PB 序列（乐咕乐股，经 akshare）
# ---------------------------------------------------------------------------
def fetch_gem50_pe_pb_history() -> Dict[str, list]:
    """获取创业板50 的历史 PE（滚动）与 PB 序列，用于估值分位。

    注：创业板指(399006) 与创业板50(399673) 高度相关，用创业板50 的历史
    估值序列近似创业板指的估值分位（乐咕乐股不直接提供创业板指）。
    """
    import akshare as ak

    result = {}
    try:
        pe_df = ak.stock_index_pe_lg(symbol="创业板50")
        # 列：日期, 指数, 等权静态市盈率, 静态市盈率, 静态市盈率中位数,
        #     等权滚动市盈率, 滚动市盈率, 滚动市盈率中位数
        result["pe"] = [
            {"date": str(r["日期"]), "pe": _num(r["滚动市盈率"])}
            for _, r in pe_df.iterrows()
        ]
    except Exception as e:
        raise FetchError(f"乐咕乐股创业板50 PE 获取失败: {e}") from e

    try:
        pb_df = ak.stock_index_pb_lg(symbol="创业板50")
        pb_col = next((c for c in pb_df.columns if "市净率" in c and "中位" not in c and "等权" not in c), None)
        if pb_col is None:
            pb_col = pb_df.columns[-1]
        result["pb"] = [
            {"date": str(r["日期"]), "pb": _num(r[pb_col])}
            for _, r in pb_df.iterrows()
        ]
    except Exception:
        result["pb"] = []  # PB 可选，失败不阻断

    return result


# ---------------------------------------------------------------------------
# 3. 创业板指历史日 K（新浪财经）
# ---------------------------------------------------------------------------
def fetch_gem_kline(days: int = 300) -> List[Dict]:
    """获取创业板指历史日 K 线（新浪），返回按日期升序的列表。

    每条：{date, open, high, low, close, volume}
    """
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": "sz399006", "scale": "240", "ma": "no", "datalen": str(days)}
    resp = _get(url, params=params, headers={"Referer": "https://finance.sina.com.cn/"})

    import json
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
# 4. 全市场 PE（乐咕乐股，用于股债性价比 ERP）
# ---------------------------------------------------------------------------
def fetch_market_pe_history() -> List[Dict]:
    """获取全市场（沪深A股）历史 PE，用于计算股债性价比。"""
    import akshare as ak

    df = ak.stock_market_pe_lg(symbol="沪深A股")
    return [
        {"date": str(r["日期"]), "pe": _num(r["市盈率"])}
        for _, r in df.iterrows()
    ]


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _num(v) -> float:
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def build_gem_dataset() -> Dict:
    """整合所有创业板数据，返回结构化数据集。"""
    dataset = {
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "current": fetch_gem_current_valuation(),
        "gem50_valuation": fetch_gem50_pe_pb_history(),
        "kline": fetch_gem_kline(),
        "market_pe": fetch_market_pe_history(),
    }
    return dataset
