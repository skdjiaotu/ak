"""买方择时评分引擎。

把每日市场体检的四维数据（估值 / 技术 / 资金 / 情绪）合成一个统一的
「市场机会分」（0~100，越高越值得布局），并给出仓位建议。

设计原则（买方视角）：
    - 估值是"锚"，决定长期胜率；资金/情绪是"风"，决定短期节奏。
    - 分数不是四维简单平均，而是「低估 + 情绪恐慌 + 资金未撤离」时给高分，
      因为历史看，好价格 + 悲观情绪 + 聪明钱还在 = 最佳买点。
    - 冲突裁决有明确规则，不做含糊的加权。

仅基于公开数据的量化参考，不构成投资建议。
"""

from __future__ import annotations

from typing import Dict, List


# ---------------------------------------------------------------------------
# 估值维度打分（0~100，越高越便宜/越值得布局）
# ---------------------------------------------------------------------------
def score_valuation(indexes: List[Dict]) -> Dict:
    """基于宽基指数 PE 分位的估值打分。

    用「全市场 PE 分位均值」衡量整体估值水位，同时捕捉极端分化。
    """
    pe_pcts = [i["pe_percentile"] for i in indexes if i.get("pe_percentile") is not None]
    if not pe_pcts:
        return {"score": 50, "avg_pe_pct": None, "note": "无估值数据"}

    avg = sum(pe_pcts) / len(pe_pcts)  # 0~100

    # 估值分位越低越便宜，得分越高
    if avg <= 10:
        score = 90  # 历史极低分位，黄金坑
    elif avg <= 20:
        score = 80
    elif avg <= 35:
        score = 65
    elif avg <= 50:
        score = 50  # 中位，不贵不便宜
    elif avg <= 65:
        score = 35
    elif avg <= 80:
        score = 20
    else:
        score = 10  # 历史高位，危险

    note = f"宽基 PE 分位均值 {avg:.1f}%"
    return {"score": score, "avg_pe_pct": avg, "note": note}


# ---------------------------------------------------------------------------
# 技术维度打分（0~100，越高越安全/越接近底部区域）
# ---------------------------------------------------------------------------
def score_technical(indexes: List[Dict]) -> Dict:
    """基于距前高回撤的技术打分：深度回撤 → 位置相对安全。"""
    dd = [i["drawdown"] for i in indexes if i.get("drawdown") is not None]
    if not dd:
        return {"score": 50, "avg_drawdown": None, "note": "无技术数据"}

    avg = sum(dd) / len(dd)  # 负值，如 -30 表示回撤 30%

    # 回撤越深，位置越低，得分越高（但需警惕"接飞刀"）
    if avg <= -40:
        score = 75
    elif avg <= -30:
        score = 70
    elif avg <= -20:
        score = 60
    elif avg <= -10:
        score = 50
    elif avg <= 0:
        score = 35  # 接近/创新高，位置偏高
    else:
        score = 25

    note = f"宽基距前高平均回撤 {avg:.1f}%"
    return {"score": score, "avg_drawdown": avg, "note": note}


# ---------------------------------------------------------------------------
# 资金维度打分（0~100，越高 = 资金面越友好）
# ---------------------------------------------------------------------------
def score_fund_flow(fund: Dict) -> Dict:
    """基于杠杆资金趋势的打分：资金未撤离给中性偏上，撤离则扣分。"""
    trend = fund.get("margin_trend", "")
    score = 50

    if "加速加仓" in trend:
        score = 70
        note = "杠杆资金加速加仓"
    elif "温和加仓" in trend or "加仓" in trend:
        score = 60
        note = "杠杆资金温和加仓"
    elif "撤离" in trend or "去杠杆" in trend:
        score = 25  # 去杠杆是明确的负面信号
        note = "杠杆资金撤离（去杠杆）"
    elif "流出" in trend:
        score = 35
        note = "杠杆资金小幅流出"
    else:
        note = "杠杆资金中性"

    # 杠杆过热 = 情绪亢奋，对"布局"而言是减分项
    emotion = fund.get("margin_emotion", "")
    if "过热" in emotion or "亢奋" in emotion:
        score = min(score, 30)

    return {"score": score, "note": note}


# ---------------------------------------------------------------------------
# 情绪维度打分（0~100，越高 = 越恐慌 = 越接近买点，逆向思维）
# ---------------------------------------------------------------------------
def score_sentiment(vix: List[Dict]) -> Dict:
    """基于恐慌指数的逆向打分：极度恐慌时反而是布局时机。"""
    pcts = [v["vol_percentile"] for v in vix if v.get("vol_percentile") is not None]
    if not pcts:
        return {"score": 50, "avg_vol_pct": None, "note": "无情绪数据"}

    avg = sum(pcts) / len(pcts)  # 0~100

    # 逆向：恐慌（高波动分位）→ 高布局分；亢奋平静（低波动）→ 低布局分
    if avg >= 80:
        score = 80  # 极度恐慌，逆向买点
        note = f"恐慌度分位均值 {avg:.1f}%（极度恐慌，逆向机会）"
    elif avg >= 60:
        score = 65
        note = f"恐慌度分位均值 {avg:.1f}%（偏恐慌）"
    elif avg >= 40:
        score = 50
        note = f"恐慌度分位均值 {avg:.1f}%（中性）"
    elif avg >= 20:
        score = 35
        note = f"恐慌度分位均值 {avg:.1f}%（偏平静，情绪偏乐观）"
    else:
        score = 25
        note = f"恐慌度分位均值 {avg:.1f}%（极度平静，谨防变盘）"

    return {"score": score, "avg_vol_pct": avg, "note": note}


# ---------------------------------------------------------------------------
# 综合择时评分 + 仓位建议
# ---------------------------------------------------------------------------
def compute_timing_score(report: Dict) -> Dict:
    """综合四维，输出市场机会分与仓位建议。

    权重（买方经验）：
        估值 35%（锚，决定长期胜率）
        技术 15%（位置）
        资金 20%（聪明钱方向）
        情绪 30%（逆向买点，权重给高因为恐慌常是最佳时机）
    """
    v = score_valuation(report["indexes"])
    t = score_technical(report["indexes"])
    f = score_fund_flow(report["fund_flow"])
    s = score_sentiment(report["vix"])

    weights = {"估值": 0.35, "技术": 0.15, "资金": 0.20, "情绪": 0.30}
    components = {
        "估值": {"score": v["score"], "note": v["note"]},
        "技术": {"score": t["score"], "note": t["note"]},
        "资金": {"score": f["score"], "note": f["note"]},
        "情绪": {"score": s["score"], "note": s["note"]},
    }

    total = sum(components[k]["score"] * weights[k] for k in components)
    total = round(total, 1)

    # ---- 仓位建议（基于总分，附冲突裁决）----
    delev = "撤离" in report["fund_flow"].get("margin_trend", "")

    if total >= 75:
        advice = "可积极布局（分批建仓）"
        if delev:
            advice = "低估 + 恐慌，但杠杆资金仍在撤离，建议分批、不重仓抄底"
    elif total >= 60:
        advice = "可逢低分批布局"
    elif total >= 45:
        advice = "中性，控制仓位、精选标的"
    elif total >= 30:
        advice = "偏谨慎，降低仓位"
    else:
        advice = "谨慎观望，估值偏高/情绪亢奋"

    return {
        "score": total,
        "components": components,
        "weights": weights,
        "advice": advice,
        "deleveraging": delev,
    }


# ---------------------------------------------------------------------------
# 红黄绿灯（与现有 overall_signal 兼容，但更量化）
# ---------------------------------------------------------------------------
def signal_from_score(score: float) -> str:
    if score >= 75:
        return "🟢 机会区"
    elif score >= 60:
        return "🟢 偏机会"
    elif score >= 45:
        return "🟡 中性区"
    elif score >= 30:
        return "🟠 谨慎区"
    else:
        return "🔴 危险区"
