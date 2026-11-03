"""A 股恐慌指数（已实现波动率版）—— 数据采集与计算模块。

原理（对标美股 VIX 的"已实现波动率"近似）：
    VIX 衡量市场对未来 30 天波动的恐慌预期。A 股无官方 VIX，用
    "20 日已实现波动率（年化）"作为恐慌指数的近似代理：

        日收益率  r_t = ln(P_t / P_{t-1})
        20 日波动率 σ_20 = std(r) * √252

    σ 越高，市场短期波动越大，情绪越恐慌。

数据源：
    新浪财经 (sina.com.cn) —— 沪深300(000300) 历史日 K（约 3 年）

支持对比多个指数（沪深300 / 上证指数 / 创业板指），看哪块更恐慌。

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import datetime
import json
import math
from typing import Dict, List, Tuple

from gem_risk.fetcher import _get, FetchError, _num

# 可对比的指数（新浪 symbol）
INDEX_SYMBOLS = {
    "沪深300": "sh000300",
    "上证指数": "sh000001",
    "创业板指": "sz399006",
    "科创50": "sh000688",
    "深证成指": "sz399001",
}


# ---------------------------------------------------------------------------
# 数据抓取
# ---------------------------------------------------------------------------
def fetch_kline(symbol: str, days: int = 800) -> List[Dict]:
    """获取指数历史日 K（新浪），返回按日期升序列表。"""
    url = "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
    params = {"symbol": symbol, "scale": "240", "ma": "no", "datalen": str(days)}
    resp = _get(url, params=params, headers={"Referer": "https://finance.sina.com.cn/"})

    raw = json.loads(resp.text)
    klines = []
    for r in raw:
        klines.append({
            "date": r["day"],
            "close": _num(r["close"]),
        })
    klines.sort(key=lambda x: x["date"])
    return klines


# ---------------------------------------------------------------------------
# 恐慌指数计算
# ---------------------------------------------------------------------------
def _log_returns(closes: List[float]) -> List[float]:
    """计算对数日收益率序列。"""
    return [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]


def realized_volatility(closes: List[float], window: int = 20) -> float:
    """计算 window 日已实现波动率（年化）。"""
    if len(closes) < window + 1:
        return 0.0
    returns = _log_returns(closes)[-window:]
    if not returns:
        return 0.0
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance) * math.sqrt(252)


def compute_vix(klines: List[Dict], window: int = 20) -> Dict:
    """基于日 K 计算恐慌指数，返回完整结果。

    返回：
        {
            "name": 指数名,
            "close": 最新收盘,
            "current_vol": 当前 20 日年化波动率,
            "vol_series": [{date, vol}...] 滚动波动率序列,
            "percentile": 当前波动率的历史分位(0~1),
            "vol_min/max/mean": 历史波动率统计,
        }
    """
    closes = [k["close"] for k in klines]
    dates = [k["date"] for k in klines]

    current_vol = realized_volatility(closes, window)

    # 滚动波动率序列
    vol_series = []
    for i in range(window, len(closes)):
        v = realized_volatility(closes[: i + 1], window)
        vol_series.append({"date": dates[i], "vol": v})

    vols = [v["vol"] for v in vol_series if v["vol"] > 0]
    if vols:
        percentile = sum(1 for v in vols if v < current_vol) / len(vols)
        vol_min, vol_max = min(vols), max(vols)
        vol_mean = sum(vols) / len(vols)
    else:
        percentile, vol_min, vol_max, vol_mean = 0.5, 0.0, 0.0, 0.0

    return {
        "close": closes[-1] if closes else 0,
        "current_vol": current_vol,
        "vol_series": vol_series,
        "percentile": percentile,
        "vol_min": vol_min,
        "vol_max": vol_max,
        "vol_mean": vol_mean,
        "history_len": len(vol_series),
    }


def panic_level(current_vol: float, percentile: float) -> Tuple[str, str]:
    """根据当前波动率与历史分位，给出恐慌等级与解读。"""
    # 用分位为主判断（相对历史），波动率绝对值为辅
    if percentile >= 0.9:
        level = "🔴 极度恐慌"
        desc = "波动率处于历史 90% 以上分位，市场情绪极度恐慌，短期剧烈波动。"
    elif percentile >= 0.7:
        level = "🟠 恐慌"
        desc = "波动率处于历史 70%~90% 分位，市场明显恐慌，需警惕回撤风险。"
    elif percentile >= 0.4:
        level = "🟡 中性"
        desc = "波动率处于历史中位，市场情绪平稳，属正常波动区间。"
    elif percentile >= 0.15:
        level = "🟢 平静"
        desc = "波动率处于历史低位，市场情绪平静/偏乐观。"
    else:
        level = "🔵 极度平静"
        desc = "波动率处于历史极低位，市场极度平静（注意：低波动往往伴随变盘）。"
    return level, desc


def build_vix_dataset(index_name: str = "沪深300") -> Dict:
    """构建指定指数的恐慌指数数据集。"""
    symbol = INDEX_SYMBOLS[index_name]
    klines = fetch_kline(symbol)
    vix = compute_vix(klines)
    vix["name"] = index_name
    vix["symbol"] = symbol
    vix["fetched_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return vix
