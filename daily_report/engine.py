"""每日市场体检报告 —— 四维整合引擎。

复用已有三个模块，一次性输出：
    ① 估值分位 + 技术结构（index_risk）
    ② 资金流向：两融 + 北向（fund_flow）
    ③ 恐慌情绪（vix）
    ④ 综合判定

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import datetime
from typing import Dict, List

from gem_risk.engine import assess_gem
from index_risk.fetcher import INDEX_CONFIG, build_index_dataset
from fund_flow.fetcher import fetch_all as fund_fetch_all
from fund_flow.engine import assess as fund_assess
from vix.engine import build_vix_dataset, panic_level


def _fmt_pct(v, nd=1):
    return None if v is None else round(v * 100, nd)


def collect_indexes() -> List[Dict]:
    """采集所有宽基指数的估值/技术/危险度。"""
    results = []
    for code in INDEX_CONFIG:
        ds = build_index_dataset(code)
        result = assess_gem(ds)
        val = result.get("valuation", {})
        tech = result.get("technical", {})
        extra = ds.get("extra", {})
        results.append({
            "code": code,
            "name": ds["index_name"],
            "pe_ttm": val.get("pe_ttm"),
            "pe_percentile": _fmt_pct(val.get("pe_percentile")),
            "pb": val.get("pb_current"),
            "pb_percentile": _fmt_pct(val.get("pb_percentile")),
            "roe": _fmt_pct(extra.get("roe")),
            "drawdown": _fmt_pct(tech.get("drawdown_from_high")),
            "ytd": _fmt_pct(tech.get("ytd_return")),
            "score": result.get("composite_score"),
            "signal": result.get("signal"),
            "advice": result.get("advice"),
        })
    return results


def collect_fund_flow() -> Dict:
    """采集资金面（两融 + 北向）。"""
    data = fund_fetch_all()
    result = fund_assess(data)
    mg = result["margin"]
    nb = result["northbound"]
    return {
        "margin_balance": mg["cur_balance"],          # 元
        "margin_balance_20d": _fmt_pct(mg["bal_20d"] / 100) if mg["bal_20d"] is not None else None,
        "margin_trend": mg["trend_signal"],
        "margin_ratio": mg["cur_ratio"],              # %
        "margin_emotion": mg["emotion"],
        "short_balance": mg["cur_short"],
        "north_last_date": nb["last_net_buy_date"],
        "north_nan_date": nb["first_nan_date"],
        "north_cum_yi": nb["last_cum_net_buy_yi"],
        "north_net_60d_yi": nb["net_60d_yi"],
        "north_signal": nb["foreign_signal"],
        "signals": result["signals"],
        "notes": result["notes"],
    }


def collect_vix() -> List[Dict]:
    """采集各指数恐慌度（波动率）。"""
    from vix.engine import INDEX_SYMBOLS
    out = []
    for name in INDEX_SYMBOLS:
        v = build_vix_dataset(name)
        level, desc = panic_level(v["current_vol"], v["percentile"])
        out.append({
            "name": name,
            "vol": v["current_vol"],
            "vol_percentile": _fmt_pct(v["percentile"]),
            "level": level,
        })
    return out


def build_report() -> Dict:
    """构建完整体检报告数据。"""
    return {
        "fetched_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "indexes": collect_indexes(),
        "fund_flow": collect_fund_flow(),
        "vix": collect_vix(),
    }


def overall_signal(report: Dict) -> Dict:
    """综合四维给出整体信号。"""
    indexes = report["indexes"]
    fund = report["fund_flow"]

    # 统计红灯/黄灯数量
    red = sum(1 for i in indexes if "红" in i["signal"])
    yellow = sum(1 for i in indexes if "黄" in i["signal"])
    green = sum(1 for i in indexes if "绿" in i["signal"])

    # 资金面：杠杆资金是否在撤离
    delev = "撤离" in fund["margin_trend"] or "流出" in fund["margin_trend"]

    # 综合判断
    notes = []
    if red >= 2:
        overall = "🔴 高风险"
        notes.append("多个宽基指数亮红灯，估值或技术处于高位，需高度警惕。")
    elif red >= 1 or yellow >= 3:
        overall = "🟡 需警惕"
        notes.append("部分指数亮黄灯/红灯，市场分化明显，需精选标的、控制仓位。")
    else:
        overall = "🟢 相对安全"
        notes.append("多数指数估值处于偏低区域，位置相对安全，可关注布局机会。")

    if delev:
        notes.append("⚠️ 杠杆资金在撤离（融资余额下降），警惕去杠杆带来的调整风险。")

    return {
        "overall": overall,
        "red": red,
        "yellow": yellow,
        "green": green,
        "notes": notes,
    }
