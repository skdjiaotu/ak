"""科创板位置监控 —— 分析引擎。

与 gem_position 对称：把科创50 当前位置（价格 + 估值 + 距高点）合成「位置温度」，
映射 5 档信号 + 仓位建议。

关键差异（科创板特有）：
  科创50 存在「跌了但没变便宜」的陷阱——价格回撤深，但 PE 仍处高分位
  （半导体成分股盈利恶化，ROE 仅 6%）。因此本引擎对「价格低位 + 估值高位」
  的背离场景显式警示，避免把技术超跌误判为估值便宜。

位置温度构成（各 0~100，越高越危险）：
  1. 价格分位（35%）：当前点位在历史日收盘中的分位
  2. 估值分位（45%）：PE-TTM 历史分位（蛋卷直接给，PB 辅助）——科创板权重更高
  3. 距高点回撤（20%）：离历史高点的距离
"""

from __future__ import annotations

from typing import Dict, List, Optional


def _percentile_rank(values: List[float], current: float) -> float:
    if not values:
        return 0.5
    less = sum(1 for v in values if v < current)
    return less / len(values)


def _ma(values: List[float], n: int) -> Optional[float]:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def assess_position(ds: Dict) -> Dict:
    kl = ds["kline"]
    val = ds.get("valuation") or {}

    closes = [k["close"] for k in kl if k["close"]]
    latest = closes[-1] if closes else None
    last_date = kl[-1]["date"] if kl else None

    # ---- 1. 价格分位（近5年/全历史，科创50 2020年才上市，全历史即近6年）----
    price_pct_all = _percentile_rank(closes, latest) if latest else None
    # 近 3 年（约 750 交易日）更能反映中期位置
    closes_3y = closes[-750:] if len(closes) >= 750 else closes
    price_pct_3y = _percentile_rank(closes_3y, latest) if latest else None
    price_pct = price_pct_3y

    # ---- 2. 估值分位（蛋卷直接给完整历史分位）----
    pe_pct = val.get("pe_percentile")
    pb_pct = val.get("pb_percentile")
    cur_pe = val.get("pe_ttm")
    cur_pb = val.get("pb")
    roe = val.get("roe")

    # ---- 3. 距高点回撤 ----
    high_all = max(closes) if closes else None
    dd_from_all = (latest / high_all - 1) if (latest and high_all) else None

    # ---- 均线结构 ----
    ma60 = _ma(closes, 60)
    ma250 = _ma(closes, 250)
    above_ma60 = (latest > ma60) if (latest and ma60) else None
    above_ma250 = (latest > ma250) if (latest and ma250) else None

    # ---- 合成位置温度（科创50 估值权重更高，因盈利易变）----
    components = {}
    if price_pct is not None:
        components["price"] = price_pct * 100
    if pe_pct is not None:
        components["pe"] = pe_pct * 100
    if dd_from_all is not None:
        components["drawdown"] = max(0.0, min(100.0, (1 + dd_from_all) * 100))

    weights = {"price": 0.35, "pe": 0.45, "drawdown": 0.20}
    temp = 0.0
    wsum = 0.0
    for k, w in weights.items():
        if k in components:
            temp += components[k] * w
            wsum += w
    position_temp = temp / wsum if wsum else None

    # ---- 5 档信号 ----
    signal, advice, suggest_pos = _to_signal(position_temp)

    # ---- 科创板特有的「跌了但没变便宜」警示 ----
    divergence = False
    div_note = None
    if (price_pct is not None and pe_pct is not None
            and price_pct < 0.3 and pe_pct > 0.6):
        divergence = True
        div_note = (f"⚠️ 价格处历史低位（分位 {price_pct*100:.0f}%），"
                    f"但 PE 仍处 {pe_pct*100:.0f}% 高分位（ROE 仅 {roe*100:.1f}%）。"
                    f"「跌了但没变便宜」——盈利恶化所致，勿把技术超跌误判为估值便宜。")

    return {
        "latest": latest,
        "last_date": last_date,
        "price_pct_3y": price_pct_3y,
        "price_pct_all": price_pct_all,
        "pe_ttm": cur_pe,
        "pe_pct": pe_pct,
        "pb": cur_pb,
        "pb_pct": pb_pct,
        "roe": roe,
        "dividend_yield": val.get("dividend_yield"),
        "eva_type": val.get("eva_type"),
        "high_all": high_all,
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
        "divergence": divergence,
        "div_note": div_note,
    }


def _to_signal(temp: Optional[float]):
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


def build_position_series(kl: List[Dict], window: int = 750) -> Dict:
    """生成可视化序列（近 window 日）：dates/closes/pct。"""
    closes = [k["close"] for k in kl]
    dates = [k["date"] for k in kl]
    n = len(closes)
    start = max(0, n - window)
    dates = dates[start:]
    closes = closes[start:]
    pcts = []
    for i in range(len(closes)):
        pcts.append(_percentile_rank(closes, closes[i]) * 100)
    return {"dates": dates, "closes": closes, "pct": pcts}
