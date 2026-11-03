"""创业板位置评估 —— 数据采集模块。

聚焦单一目标：判断创业板指当前处于历史「高位（危险）」还是「低位（可建仓）」。

数据源：
  1. 新浪财经 — 创业板指历史日 K（价格分位 + 距高点回撤 + 均线）
  2. 乐咕乐股 — 创业板50 历史 PE/PB 序列（估值分位，经 akshare）
  3. 国证指数 — 创业板指当前官方 PE/PB（权威当前值）

网络说明：公司代理下东财不稳定，优先新浪 + 国证 + 乐咕，Session(trust_env=False) 直连。

数据仅供研究参考，不构成投资建议。
"""

from __future__ import annotations

import datetime
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

GEM_INDEX_CODE = "399006"


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


# ---------------------------------------------------------------------------
# 1. 创业板指历史日 K（新浪）
# ---------------------------------------------------------------------------
def fetch_gem_kline(days: int = 6000) -> List[Dict]:
    """创业板指历史日 K（新浪），按日期升序。每条 {date,open,high,low,close,volume}。"""
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": "sz399006", "scale": "240", "ma": "no", "datalen": str(days)}
    resp = _SESSION.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
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
# 2. 创业板50 历史 PE/PB（乐咕乐股）
# ---------------------------------------------------------------------------
def fetch_gem50_pe_pb_history() -> Dict[str, list]:
    """创业板50 历史 PE/PB 序列（用于估值分位，与创业板指高度相关）。"""
    import akshare as ak

    result = {}
    try:
        pe_df = ak.stock_index_pe_lg(symbol="创业板50")
        result["pe"] = [
            {"date": str(r["日期"]), "pe": _num(r["滚动市盈率"])}
            for _, r in pe_df.iterrows()
        ]
    except Exception as e:
        raise FetchError(f"创业板50 PE 获取失败: {e}") from e

    try:
        pb_df = ak.stock_index_pb_lg(symbol="创业板50")
        pb_col = next((c for c in pb_df.columns
                       if "市净率" in c and "中位" not in c and "等权" not in c), None)
        if pb_col is None:
            pb_col = pb_df.columns[-1]
        result["pb"] = [
            {"date": str(r["日期"]), "pb": _num(r[pb_col])}
            for _, r in pb_df.iterrows()
        ]
    except Exception:
        result["pb"] = []
    return result


# ---------------------------------------------------------------------------
# 3. 创业板指当前估值（国证官方）
# ---------------------------------------------------------------------------
def fetch_gem_current_valuation() -> Dict:
    """创业板指当前 PE/PB/收盘点位（国证官网）。"""
    url = "https://www.cnindex.com.cn/index/indexList"
    params = {"channelCode": "-1", "rows": "2000", "pageNum": "1"}
    resp = _SESSION.get(url, params=params,
                        headers={**_HEADERS, "Referer": "https://www.cnindex.com.cn/"},
                        timeout=_TIMEOUT)
    resp.raise_for_status()
    items = (resp.json().get("data") or {}).get("rows") or []
    for it in items:
        if str(it.get("indexcode") or "") == GEM_INDEX_CODE:
            return {
                "name": it.get("indexname") or "创业板指",
                "close": _num(it.get("closeingPoint")),
                "pe_ttm": _num(it.get("peDynamic")),
                "pb": _num(it.get("pb")),
                "change_pct": _num(it.get("percent")),
            }
    raise FetchError(f"国证未找到创业板指 {GEM_INDEX_CODE}")


# ---------------------------------------------------------------------------
# 统一入口
# ---------------------------------------------------------------------------
def build_gem_dataset() -> Dict:
    """整合创业板位置评估所需数据。"""
    return {
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kline": fetch_gem_kline(),
        "valuation": fetch_gem50_pe_pb_history(),
        "current": fetch_gem_current_valuation(),
    }


if __name__ == "__main__":
    ds = build_gem_dataset()
    kl = ds["kline"]
    print(f"日K: {len(kl)} 条, {kl[0]['date']} ~ {kl[-1]['date']}, 最新 {kl[-1]['close']}")
    print(f"当前估值: {ds['current']}")
    print(f"PE序列 {len(ds['valuation'].get('pe', []))} 期, PB {len(ds['valuation'].get('pb', []))} 期")
