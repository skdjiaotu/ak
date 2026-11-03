"""创业板位置评估 —— 分析引擎。

核心：把创业板指当前位置（价格 + 估值 + 距高点）合成一个「位置温度」，
映射为 5 档信号 + 仓位建议。

位置温度越高 = 越接近历史高位 = 越危险（应减仓）；
位置温度越低 = 越接近历史低位 = 越便宜（可建仓）。

构成（三项各 0~100，越高越危险，加权汇总）：
  1. 价格分位（40%）：当前点位在历史日收盘中的分位
     — 近 5 年分位为主，全历史分位为辅
  2. 估值分位（40%）：PE-TTM 历史分位（PB 辅助）
  3. 距高点回撤（20%）：离近 5 年高点 / 历史高点的距离，回撤越深越"低位"
"""

from __future__ import annotations

from typing import Dict, List, Optional


def _percentile_rank(values: List[float], current: float) -> float:
    """current 在 values 中的分位（0~1，越高越靠上/越贵）。"""
    if not values:
        return 0.5
    less = sum(1 for v in values if v < current)
    return less / len(values)


def _ma(values: List[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


# ---------------------------------------------------------------------------
# 位置温度计算
# ---------------------------------------------------------------------------
def assess_position(ds: Dict) -> Dict:
    kl = ds["kline"]
    val = ds.get("valuation") or {}
    cur = ds.get("current") or {}

    closes = [k["close"] for k in kl if k["close"]]
    latest = closes[-1] if closes else None
    last_date = kl[-1]["date"] if kl else None

    # ---- 1. 价格分位 ----
    # 近 5 年（约 1250 交易日）与全历史
    closes_5y = closes[-1250:] if len(closes) >= 1250 else closes
    price_pct_5y = _percentile_rank(closes_5y, latest) if latest else None
    price_pct_all = _percentile_rank(closes, latest) if latest else None
    # 综合价格分位：近5年为主（更能反映中期位置）
    price_pct = price_pct_5y

    # ---- 2. 估值分位 ----
    pe_series = [r["pe"] for r in val.get("pe", []) if r["pe"] and r["pe"] > 0]
    pb_series = [r["pb"] for r in val.get("pb", []) if r["pb"] and r["pb"] > 0]

    cur_pe = cur.get("pe_ttm")
    cur_pb = cur.get("pb")
    # 当前 PE 优先用国证官方值，缺失则用乐咕最新
    if not cur_pe and pe_series:
        cur_pe = pe_series[-1]
    if not cur_pb and pb_series:
        cur_pb = pb_series[-1]

    pe_pct = _percentile_rank(pe_series, cur_pe) if (cur_pe and pe_series) else None
    pb_pct = _percentile_rank(pb_series, cur_pb) if (cur_pb and pb_series) else None

    # ---- 3. 距高点回撤 ----
    high_5y = max(closes_5y) if closes_5y else None
    high_all = max(closes) if closes else None
    dd_from_5y = (latest / high_5y - 1) if (latest and high_5y) else None
    dd_from_all = (latest / high_all - 1) if (latest and high_all) else None

    # ---- 技术均线（辅助参考）----
    ma60 = _ma(closes, 60)
    ma250 = _ma(closes, 250)
    above_ma60 = (latest > ma60) if (latest and ma60) else None
    above_ma250 = (latest > ma250) if (latest and ma250) else None

    # ---- 合成位置温度（0~100，越高越危险）----
    # 价格分位直接 ×100；估值分位 ×100；回撤转"危险度"：回撤越浅越危险
    components = {}
    if price_pct is not None:
        components["price"] = price_pct * 100
    if pe_pct is not None:
        components["pe"] = pe_pct * 100
    if dd_from_5y is not None:
        # 回撤 0%（新高）→ 危险 100；回撤 -50% → 危险 0（线性）
        components["drawdown"] = max(0.0, min(100.0, (1 + dd_from_5y) * 100))

    weights = {"price": 0.40, "pe": 0.40, "drawdown": 0.20}
    temp = 0.0
    wsum = 0.0
    for k, w in weights.items():
        if k in components:
            temp += components[k] * w
            wsum += w
    position_temp = temp / wsum if wsum else None

    # ---- 5 档信号 + 仓位建议 ----
    signal, advice, suggest_pos = _to_signal(position_temp)

    return {
        "latest": latest,
        "last_date": last_date,
        "price_pct_5y": price_pct_5y,
        "price_pct_all": price_pct_all,
        "pe_ttm": cur_pe,
        "pe_pct": pe_pct,
        "pb": cur_pb,
        "pb_pct": pb_pct,
        "pe_series_len": len(pe_series),
        "high_5y": high_5y,
        "high_all": high_all,
        "dd_from_5y": dd_from_5y,
        "dd_from_all": dd_from_all,
        "ma60": ma60,
        "ma250": ma250,
        "above_ma60": above_ma60,
        "above_ma250": above_ma250,
        "components": components,
        "position_temp": position_temp,
        "signal": signal,
        "advice": advice,
        "suggest_pos": suggest_pos,
    }


def _to_signal(temp: Optional[float]):
    """位置温度 → 5 档信号 + 仓位建议。"""
    if temp is None:
        return "数据不足", "无法判定", None
    if temp >= 80:
        return ("高风险 🔴", "已接近历史高位，估值贵、追高风险大，建议轻仓或空仓，"
                "切勿追高；已有持仓可考虑分批止盈。", 0.2)
    if temp >= 60:
        return ("偏高风险 🟠", "位置偏高，估值不便宜，建议降低仓位、控制风险，"
                "反弹减仓为主，不轻易加仓。", 0.4)
    if temp >= 40:
        return ("中性 🟡", "位置居中，估值中性，可维持现有仓位，"
                "等待更明确的低估或高估信号再行动。", 0.6)
    if temp >= 20:
        return ("偏低位置 🟢", "位置偏低，估值开始具备吸引力，"
                "可分批建仓、逢低布局。", 0.8)
    return ("低位区域 🟢", "处于历史低位，估值便宜，"
            "适合逐步建立仓位、越跌越买，但仍需控制节奏、留足子弹。", 1.0)


def build_position_series(kl: List[Dict], window: int = 1250) -> Dict:
    """生成用于可视化的历史序列（近 window 日）。

    返回 {dates, closes, pct}：pct 为每日收盘在近5年滚动分位（近似位置）。
    """
    closes = [k["close"] for k in kl]
    dates = [k["date"] for k in kl]
    n = len(closes)
    start = max(0, n - window)
    dates = dates[start:]
    closes = closes[start:]

    # 滚动分位：简化用"当日收盘在整段近5年序列的分位"（近似，非严格滚动）
    pcts = []
    win = closes[:]
    for i in range(len(closes)):
        pcts.append(_percentile_rank(win, closes[i]) * 100)
    return {"dates": dates, "closes": closes, "pct": pcts}
