"""资金面分析引擎 —— 穿透"官方欣欣向荣"的假象。

判定维度：
1. 融资余额（杠杆做多）趋势：上升 = 真金白银加仓，下降 = 去杠杆撤离
2. 融资买入额 / 成交额：情绪热度，过高 = 情绪亢奋见顶信号
3. 融资余额占流通市值比：杠杆水位（2.5%~3% 是常态，>3.5% 过热）
4. 融券余额：做空力量（已因监管受限，趋势性萎缩）
5. 北向资金：净买入已停更（2024-08-19），持股市值/累计净买额看外资态度
6. 交叉验证：指数涨 vs 资金净流出 → 缩量反弹假象
"""

from __future__ import annotations

from typing import Dict, List, Optional


def _pct_rank(series: List[float], value: float) -> float:
    """百分位排名（0~1），value 在 series 中的位置。"""
    if not series:
        return 0.5
    cnt = sum(1 for x in series if x <= value)
    return cnt / len(series)


def _change(series: List[float], lookback: int) -> Optional[float]:
    """最近 lookback 期的变化率。"""
    if len(series) < lookback + 1:
        return None
    base = series[-lookback - 1]
    if not base:
        return None
    return (series[-1] / base - 1) * 100


def _moving_avg(series: List[float], window: int) -> List[Optional[float]]:
    """移动平均，长度与 series 一致，前 window-1 项为 None。"""
    out: List[Optional[float]] = []
    for i in range(len(series)):
        if i + 1 < window:
            out.append(None)
        else:
            out.append(sum(series[i + 1 - window: i + 1]) / window)
    return out


# ---------------------------------------------------------------------------
# 两融分析
# ---------------------------------------------------------------------------

def analyze_margin(margin: List[Dict]) -> Dict:
    """分析两融数据，输出趋势与情绪判定。"""
    rzye = [m["rzye"] for m in margin if m["rzye"]]
    rzmre = [m["rzmre"] for m in margin if m["rzmre"]]
    rzyezb = [m["rzyezb"] for m in margin if m["rzyezb"] is not None]
    rqye = [m["rqye"] for m in margin if m["rqye"] is not None]

    cur_balance = rzye[-1] if rzye else None
    cur_buy = rzmre[-1] if rzmre else None
    cur_ratio = rzyezb[-1] if rzyezb else None
    cur_short = rqye[-1] if rqye else None

    # 融资余额趋势（近 20/60 日变化）
    bal_20d = _change(rzye, 20)
    bal_60d = _change(rzye, 60)

    # 融资余额历史分位（相对近 3 年）
    if len(rzye) > 750:
        rzye_3y = rzye[-750:]
    else:
        rzye_3y = rzye
    bal_pct = _pct_rank(rzye_3y, cur_balance) if cur_balance else None

    # 融资余额占流通市值比分位
    ratio_pct = _pct_rank(rzyezb, cur_ratio) if cur_ratio is not None else None

    # 融资买入额占流通市值（换手式情绪指标）
    # 用融资买入额/融资余额近似 = 单日杠杆换手
    leverage_turnover = None
    if cur_balance and cur_buy:
        leverage_turnover = cur_buy / cur_balance * 100  # %

    # 融券余额趋势（做空力量，20 日变化）
    short_20d = _change(rqye, 20) if len(rqye) > 21 else None

    # ---- 融资余额趋势判定 ----
    trend_signal = "中性"
    trend_score = 0  # 正 = 看多（资金流入），负 = 看空（资金撤离）
    if bal_20d is not None and bal_60d is not None:
        if bal_20d > 1.0 and bal_60d > 0:
            trend_signal = "杠杆资金加速加仓"
            trend_score = 2
        elif bal_20d > 0:
            trend_signal = "杠杆资金温和加仓"
            trend_score = 1
        elif bal_20d < -1.0 and bal_60d < 0:
            trend_signal = "杠杆资金持续撤离（去杠杆）"
            trend_score = -2
        elif bal_20d < 0:
            trend_signal = "杠杆资金小幅流出"
            trend_score = -1

    # ---- 情绪过热判定 ----
    emotion = "中性"
    if cur_ratio is not None:
        if cur_ratio > 3.5:
            emotion = "杠杆过热（占比 >3.5%）"
        elif cur_ratio > 3.0:
            emotion = "杠杆偏高（占比 >3.0%）"
        elif cur_ratio < 2.0:
            emotion = "杠杆偏低（占比 <2.0%，市场谨慎）"
    if leverage_turnover is not None and leverage_turnover > 6:
        emotion = "情绪亢奋（单日杠杆换手 >6%）"

    return {
        "cur_balance": cur_balance,
        "cur_buy": cur_buy,
        "cur_ratio": cur_ratio,
        "cur_short": cur_short,
        "bal_20d": bal_20d,
        "bal_60d": bal_60d,
        "bal_pct": bal_pct,
        "ratio_pct": ratio_pct,
        "leverage_turnover": leverage_turnover,
        "short_20d": short_20d,
        "trend_signal": trend_signal,
        "trend_score": trend_score,
        "emotion": emotion,
    }


# ---------------------------------------------------------------------------
# 北向资金分析
# ---------------------------------------------------------------------------

def analyze_northbound(nb: List[Dict], status: Dict) -> Dict:
    """分析北向资金，重点暴露「净买入已停更」的事实。

    单位（已在 fetcher 归一）：
      net_buy_yi = 亿元, cum_net_buy_wanyi = 万亿元, hold_mv_yuan = 元
    """
    # 有效净买入序列（非 0，截止 2024-08-16）
    valid = [r for r in nb if r.get("net_buy_yi")]
    cum_series = [r["cum_net_buy_wanyi"] for r in valid
                  if r.get("cum_net_buy_wanyi") is not None]

    # 持股市值（仅停更前有效；停更后为 0，需剔除）
    hold_mv_valid = [r["hold_mv_yuan"] for r in nb
                     if r.get("hold_mv_yuan") and r["hold_mv_yuan"] > 0]

    last_cum_wanyi = cum_series[-1] if cum_series else None
    hold_mv = hold_mv_valid[-1] if hold_mv_valid else None
    hold_20d = _change(hold_mv_valid, 20) if len(hold_mv_valid) > 21 else None
    hold_60d = _change(hold_mv_valid, 60) if len(hold_mv_valid) > 61 else None

    # 停更前的最后动向（净买入，亿元）
    net_20d_yi = None
    if len(cum_series) > 21:
        net_20d_yi = (cum_series[-1] - cum_series[-21]) * 10000  # 万亿→亿
    net_60d_yi = None
    if len(cum_series) > 61:
        net_60d_yi = (cum_series[-1] - cum_series[-61]) * 10000

    # 外资态度（基于净买入 + 持仓市值综合判断）
    # 注意：持仓市值变化 = 股价涨跌 + 真实增减持，需结合净买入判断
    foreign_signal = "无法判断（净买入已停更，持股市值亦停更）"
    if net_60d_yi is not None and net_60d_yi < -500:
        # 停更前 60 日净卖出超 500 亿，明确减持
        foreign_signal = f"停更前外资大幅净卖出（60日 {net_60d_yi:.0f} 亿），边涨边卖"
    elif net_60d_yi is not None and net_60d_yi < 0:
        foreign_signal = f"停更前外资净卖出（60日 {net_60d_yi:.0f} 亿）"
    elif net_60d_yi is not None and net_60d_yi > 0:
        foreign_signal = f"停更前外资净买入（60日 {net_60d_yi:.0f} 亿）"
    elif hold_20d is not None:
        if hold_20d > 3:
            foreign_signal = "停更前外资持仓市值上升（增持/股价上涨）"
        elif hold_20d < -3:
            foreign_signal = "停更前外资持仓市值下降（减持/股价下跌）"
        else:
            foreign_signal = "停更前外资持仓市值稳定"

    return {
        "last_net_buy_date": status.get("last_net_buy_date"),
        "first_nan_date": status.get("first_nan_date"),
        "last_cum_net_buy_yi": last_cum_wanyi * 10000 if last_cum_wanyi else None,  # 亿元
        "net_20d_yi": net_20d_yi,
        "net_60d_yi": net_60d_yi,
        "hold_mv_yi": hold_mv / 1e8 if hold_mv else None,  # 亿元
        "hold_20d": hold_20d,
        "hold_60d": hold_60d,
        "foreign_signal": foreign_signal,
    }


# ---------------------------------------------------------------------------
# 综合判定
# ---------------------------------------------------------------------------

def assess(data: Dict) -> Dict:
    """综合判定资金面，输出"真金白银 vs 假象"结论。"""
    nb = analyze_northbound(data["northbound"], data["northbound_status"])
    mg = analyze_margin(data["margin"])

    # 资金面综合倾向：杠杆趋势 + 外资态度
    signals = []
    notes = []

    # 杠杆资金是核心（两融数据完整公开，最可靠）
    if mg["trend_score"] >= 1:
        signals.append("杠杆资金在加仓（融资余额上升）")
    elif mg["trend_score"] <= -1:
        signals.append("杠杆资金在撤离（融资余额下降）")

    if nb["foreign_signal"] and "无法判断" not in nb["foreign_signal"]:
        signals.append(nb["foreign_signal"])

    # 关键警示：北向净买入停更
    notes.append(
        f"⚠️ 北向资金「当日净买入」已于 {nb['first_nan_date']} 停止披露，"
        f"此前最后披露日为 {nb['last_net_buy_date']}。官方不再公布外资净流向，"
        "需用持股市值变化间接推断。"
    )

    # 情绪过热警示
    if "过热" in mg["emotion"] or "亢奋" in mg["emotion"]:
        notes.append(f"⚠️ {mg['emotion']}，历史经验往往对应阶段性顶部，需警惕。")

    # 融资余额高位警示
    if mg["bal_pct"] is not None and mg["bal_pct"] > 0.9:
        notes.append("⚠️ 融资余额处于近3年90%分位以上，杠杆水位偏高。")

    # 缩量反弹假象检测：这里需要指数数据，由 run 层传入比对
    return {
        "margin": mg,
        "northbound": nb,
        "signals": signals,
        "notes": notes,
    }
