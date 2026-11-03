"""创业板位置危险度评估 —— 指标计算与判定引擎。

从四个维度评估创业板指数当前位置的危险程度：

    1. 估值分位 —— PE/PB 历史分位、股债性价比(ERP)
    2. 技术结构 —— 均线乖离、距前高回撤、年内涨跌幅
    3. 市场情绪与杠杆 —— 成交额变化、换手率（用成交额/流通市值近似）
    4. 资金面 —— 成交额趋势、全市场估值温度

每个指标归一化为 0~100 的"危险度分数"，分数越高越危险，最后加权汇总
输出红/黄/绿灯判定。

判定规则（经验阈值，可调）：
    - 红灯（危险）：综合分 >= 70，或估值分位 >= 90% 且价格创新高
    - 黄灯（警惕）：综合分 40~70
    - 绿灯（安全）：综合分 < 40
"""

from __future__ import annotations

from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# 阈值配置（经验值，可按需调整）
# ---------------------------------------------------------------------------
# PE/PB 分位危险度映射：分位越高越贵越危险
def _percentile_danger(p: float) -> float:
    """将估值分位(0~1)映射到危险度(0~100)。"""
    if p <= 0.2:
        return p / 0.2 * 20          # 0~20 分：低位安全
    if p <= 0.5:
        return 20 + (p - 0.2) / 0.3 * 20   # 20~40 分
    if p <= 0.8:
        return 40 + (p - 0.5) / 0.3 * 30   # 40~70 分
    return 70 + (p - 0.8) / 0.2 * 30       # 70~100 分：高估危险


# ---------------------------------------------------------------------------
# 通用统计函数
# ---------------------------------------------------------------------------
def _percentile_rank(values: List[float], current: float) -> float:
    """计算 current 在历史 values 中的分位（0~1，越高越靠前/越贵）。"""
    if not values:
        return 0.5
    less = sum(1 for v in values if v < current)
    return less / len(values)


def _ma(values: List[float], n: int) -> float:
    """简单移动平均。"""
    if len(values) < n:
        return values[-1] if values else 0.0
    return sum(values[-n:]) / n


# ---------------------------------------------------------------------------
# 维度 1：估值分位
# ---------------------------------------------------------------------------
def calc_valuation_metrics(ds: Dict) -> Dict:
    """计算估值维度指标。"""
    cur = ds["current"]
    # 兼容两种键名：valuation_series（通用）/ gem50_valuation（创业板专用）
    vs = ds.get("valuation_series") or ds.get("gem50_valuation") or {}
    extra = ds.get("extra") or {}

    # 优先使用数据源直接提供的分位（如蛋卷基金），否则用历史序列计算
    if "pe_percentile" in extra:
        pe_percentile = extra["pe_percentile"]
        pe_series_len = None  # 分位由数据源直接给出，无序列长度
    else:
        pe_series = [r["pe"] for r in vs.get("pe", []) if r["pe"] > 0]
        pe_series_len = len(pe_series)
        cur_pe_approx = cur.get("pe_ttm", 0)
        pe_percentile = _percentile_rank(pe_series, cur_pe_approx) if pe_series else None

    cur_pe_approx = cur.get("pe_ttm", 0)

    # PB 分位
    pb_percentile = None
    pb_current = cur.get("pb") if cur.get("pb") else None
    if "pb_percentile" in extra:
        pb_percentile = extra["pb_percentile"]
    else:
        pb_series = [r["pb"] for r in vs.get("pb", []) if r["pb"] > 0]
        if pb_series and pb_current:
            pb_percentile = _percentile_rank(pb_series, pb_current)

    # 股债性价比 ERP = 1/PE - 无风险利率（用 10 年期国债 ~2.5% 近似）
    risk_free = 0.025
    market_pe = ds["market_pe"][-1]["pe"] if ds["market_pe"] else 0
    if cur_pe_approx > 0:
        gem_earning_yield = 1.0 / cur_pe_approx
        erp = gem_earning_yield - risk_free
    else:
        erp = None

    return {
        "pe_ttm": cur_pe_approx,
        "pe_percentile": pe_percentile,
        "pe_series_len": pe_series_len,
        "pb_current": pb_current,
        "pb_percentile": pb_percentile,
        "erp": erp,
        "market_pe": market_pe,
    }


# ---------------------------------------------------------------------------
# 维度 2：技术结构
# ---------------------------------------------------------------------------
def calc_technical_metrics(ds: Dict) -> Dict:
    """计算技术结构指标。"""
    kl = ds["kline"]
    if not kl:
        return {}

    closes = [k["close"] for k in kl]
    cur = closes[-1]

    ma20 = _ma(closes, 20)
    ma60 = _ma(closes, 60)
    ma120 = _ma(closes, 120)
    ma250 = _ma(closes, 250)

    # 均线乖离率
    bias_ma20 = (cur - ma20) / ma20 if ma20 else 0
    bias_ma60 = (cur - ma60) / ma60 if ma60 else 0

    # 距近 250 日最高点的回撤
    high_250 = max(closes[-250:]) if len(closes) >= 250 else max(closes)
    drawdown_from_high = (cur - high_250) / high_250 if high_250 else 0

    # 年内涨跌幅（当年首个交易日至今）
    first_of_year = next((k for k in kl if k["date"][:4] == kl[-1]["date"][:4]), kl[0])
    ytd_return = (cur - first_of_year["close"]) / first_of_year["close"] if first_of_year["close"] else 0

    # 20 日涨跌幅（动量）
    if len(closes) >= 20:
        mom_20d = (cur - closes[-20]) / closes[-20]
    else:
        mom_20d = 0

    return {
        "close": cur,
        "ma20": ma20,
        "ma60": ma60,
        "ma120": ma120,
        "ma250": ma250,
        "bias_ma20": bias_ma20,
        "bias_ma60": bias_ma60,
        "drawdown_from_high": drawdown_from_high,
        "high_250": high_250,
        "ytd_return": ytd_return,
        "mom_20d": mom_20d,
    }


# ---------------------------------------------------------------------------
# 维度 3：市场情绪与杠杆（成交额）
# ---------------------------------------------------------------------------
def calc_sentiment_metrics(ds: Dict) -> Dict:
    """计算情绪/成交额指标。"""
    kl = ds["kline"]
    if not kl:
        return {}

    # 成交额（新浪 volume 是成交量股数，需近似成交额；用近 20 日均量对比）
    vols = [k["volume"] for k in kl]
    cur_vol = vols[-1]
    avg_vol_20 = _ma(vols, 20)
    avg_vol_60 = _ma(vols, 60)

    vol_ratio_20 = cur_vol / avg_vol_20 if avg_vol_20 else 1.0
    vol_ratio_60 = cur_vol / avg_vol_60 if avg_vol_60 else 1.0

    # 量能放大程度（危险信号：短期量能显著放大可能过热）
    return {
        "cur_volume": cur_vol,
        "vol_ratio_20": vol_ratio_20,
        "vol_ratio_60": vol_ratio_60,
    }


# ---------------------------------------------------------------------------
# 综合判定
# ---------------------------------------------------------------------------
def assess_gem(ds: Dict) -> Dict:
    """综合评估创业板危险度，返回完整结果。"""
    val = calc_valuation_metrics(ds)
    tech = calc_technical_metrics(ds)
    sent = calc_sentiment_metrics(ds)

    # ---- 危险度打分（0~100，越高越危险）----
    scores = {}
    notes = []

    # 1. 估值分位危险度
    if val.get("pe_percentile") is not None:
        scores["pe_percentile"] = _percentile_danger(val["pe_percentile"])
        if val["pe_percentile"] >= 0.9:
            notes.append("⚠️ PE 处于历史 90% 以上高分位，估值偏高")
        elif val["pe_percentile"] <= 0.1:
            notes.append("✅ PE 处于历史 10% 以下低分位，估值便宜")

    # 2. PB 分位危险度
    if val.get("pb_percentile") is not None:
        scores["pb_percentile"] = _percentile_danger(val["pb_percentile"])

    # 3. 技术乖离（短期涨幅过大危险）
    bias20 = tech.get("bias_ma20", 0)
    if bias20 > 0.15:
        scores["bias"] = 80
        notes.append(f"⚠️ 价格偏离 20 日均线 {bias20:.1%}，短期过热")
    elif bias20 > 0.08:
        scores["bias"] = 55
    elif bias20 < -0.10:
        scores["bias"] = 10  # 超跌，反而相对安全
        notes.append(f"✅ 价格低于 20 日均线 {abs(bias20):.1%}，短期超跌")
    else:
        scores["bias"] = 30

    # 4. 距前高回撤（回撤越大越"便宜"，危险度越低）
    dd = tech.get("drawdown_from_high", 0)
    if dd > -0.05:
        scores["drawdown"] = 60  # 接近新高，追高危险
    elif dd < -0.30:
        scores["drawdown"] = 10  # 深度回撤
        notes.append(f"✅ 距 250 日高点回撤 {abs(dd):.1%}，处于相对低位")
    else:
        scores["drawdown"] = 40

    # 5. 年内涨幅（涨幅过大危险）
    ytd = tech.get("ytd_return", 0)
    if ytd > 0.5:
        scores["ytd"] = 75
        notes.append(f"⚠️ 年内累计上涨 {ytd:.1%}，涨幅已大")
    elif ytd > 0.2:
        scores["ytd"] = 50
    elif ytd < 0:
        scores["ytd"] = 15
    else:
        scores["ytd"] = 30

    # 6. 量能（短期量能异常放大是过热信号）
    vr20 = sent.get("vol_ratio_20", 1.0)
    if vr20 > 2.0:
        scores["volume"] = 70
        notes.append(f"⚠️ 20 日量能放大 {vr20:.1f} 倍，情绪亢奋")
    elif vr20 > 1.5:
        scores["volume"] = 50
    elif vr20 < 0.7:
        scores["volume"] = 15
    else:
        scores["volume"] = 30

    # ---- 加权汇总（估值权重最高）----
    weights = {
        "pe_percentile": 0.30,
        "pb_percentile": 0.15,
        "bias": 0.15,
        "drawdown": 0.10,
        "ytd": 0.15,
        "volume": 0.15,
    }
    # PB 缺失时（如科创50 官方无 PB 数据），将其权重让渡给 PE
    if "pb_percentile" not in scores and "pe_percentile" in scores:
        weights["pe_percentile"] += weights.pop("pb_percentile", 0.0)
    total = 0.0
    wsum = 0.0
    for k, w in weights.items():
        if k in scores:
            total += scores[k] * w
            wsum += w
    composite = total / wsum if wsum else 0.0

    # ---- 红黄绿灯 ----
    pe_pct = val.get("pe_percentile")
    # 估值是核心矛盾：即使技术超跌，估值高位也不应给"安全"绿灯
    if composite >= 70 or (pe_pct is not None and pe_pct >= 0.9):
        signal = "红灯 🔴 危险"
        advice = "估值处于历史高位，短期涨幅/量能过热，建议谨慎、控制仓位、警惕回撤风险。"
    elif composite >= 40 or (pe_pct is not None and pe_pct >= 0.6):
        signal = "黄灯 🟡 警惕"
        advice = "估值中性偏高（PE 处于历史 60% 以上分位），价格虽回落但估值仍不便宜，建议逢高减仓、不追高、审慎对待。"
    else:
        signal = "绿灯 🟢 相对安全"
        advice = "估值处于历史偏低区域，位置相对安全，可考虑分批布局，但仍需关注基本面。"
    if composite < 40 and signal.startswith("绿灯"):
        notes.append("✅ 综合多项指标，当前位置风险相对较低")
    if pe_pct is not None and pe_pct >= 0.6:
        notes.append(f"⚠️ PE 处于历史 {pe_pct:.1%} 高分位：价格虽回落但估值仍偏高（可能盈利恶化所致），警惕'跌了但没变便宜'的陷阱")

    return {
        "valuation": val,
        "technical": tech,
        "sentiment": sent,
        "scores": scores,
        "composite_score": composite,
        "signal": signal,
        "advice": advice,
        "notes": notes,
    }
