"""择时历史记录沉淀 + 回测验证。

1. 历史沉淀：每次运行把择时评分追加到 history/timing_history.csv，
   形成连续的信号序列，用于观察模型信号演变、后续回测。

2. 回测验证：用指数历史 K 线，验证「估值分位低时买入、高时卖出」这类
   择时规则的历史表现，输出年化收益、最大回撤、胜率等，证明模型规则
   不是拍脑袋。

仅基于公开数据的量化参考，不构成投资建议。
"""

from __future__ import annotations

import csv
import datetime
import os
from typing import Dict, List

from index_risk.fetcher import fetch_kline, INDEX_CONFIG, FetchError


# ---------------------------------------------------------------------------
# 历史记录沉淀
# ---------------------------------------------------------------------------
HISTORY_DIR = "history"
HISTORY_FILE = os.path.join(HISTORY_DIR, "timing_history.csv")

_HEADERS = [
    "date", "score", "signal", "advice",
    "val_score", "tech_score", "fund_score", "sent_score",
    "avg_pe_pct", "avg_drawdown", "avg_vol_pct",
]


def append_history(timing: Dict, report: Dict) -> str:
    """把当日择时结果追加到历史 CSV，返回文件路径。"""
    os.makedirs(HISTORY_DIR, exist_ok=True)

    comp = timing["components"]
    row = {
        "date": report["fetched_at"][:10],
        "score": timing["score"],
        "signal": signal_name(timing["score"]),
        "advice": timing["advice"],
        "val_score": comp["估值"]["score"],
        "tech_score": comp["技术"]["score"],
        "fund_score": comp["资金"]["score"],
        "sent_score": comp["情绪"]["score"],
        "avg_pe_pct": _pct_from_note(comp["估值"]["note"]),
        "avg_drawdown": _pct_from_note(comp["技术"]["note"]),
        "avg_vol_pct": _pct_from_note(comp["情绪"]["note"]),
    }

    # 若同日已有记录则覆盖（避免重复运行造成重复行）
    rows = _read_history()
    rows = [r for r in rows if r.get("date") != row["date"]]
    rows.append(row)
    rows.sort(key=lambda r: r["date"])

    with open(HISTORY_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=_HEADERS)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in _HEADERS})

    return HISTORY_FILE


def _read_history() -> List[Dict]:
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _pct_from_note(note: str):
    """从 '宽基 PE 分位均值 12.3%' 这类 note 里提取百分数。"""
    if not note:
        return ""
    import re
    m = re.search(r"([-+]?\d+\.?\d*)%", note)
    return float(m.group(1)) if m else ""


def signal_name(score: float) -> str:
    if score >= 75:
        return "机会区"
    elif score >= 60:
        return "偏机会"
    elif score >= 45:
        return "中性区"
    elif score >= 30:
        return "谨慎区"
    else:
        return "危险区"


# ---------------------------------------------------------------------------
# 回测验证（基于估值分位择时）
# ---------------------------------------------------------------------------
def backtest_valuation_timing(code: str = "000300", lookback_pct: float = 20.0,
                              top_pct: float = 80.0, use_trend_filter: bool = True) -> Dict:
    """回测「估值低 + 趋势转好」双确认择时策略。

    核心思想（买方择时的精髓）：
        「便宜」不等于「该买」——单边熊市里越跌越买只会越套越深。
        正确做法是：估值低（回撤深）只作为必要条件，还需等趋势右侧确认
        （价格站上 MA60）才买入。这避免"接飞刀"。

    策略（use_trend_filter=True）：
        - 回撤深于 lookback%（估值低）且 站上 MA60 → 持有
        - 否则空仓
    比较「择时持有」vs「一直持有(buy & hold)」的收益与回撤。

    use_trend_filter=False 时退化为纯估值择时（回撤深就买），用于对比。
    """
    cfg = INDEX_CONFIG[code]
    name = cfg["name"]
    try:
        klines = fetch_kline(code, days=800)
    except FetchError as e:
        return {"error": str(e), "name": name}

    if len(klines) < 260:
        return {"error": "历史数据不足", "name": name}

    closes = [k["close"] for k in klines]
    dates = [k["date"] for k in klines]

    # 预计算 MA60（前 59 日用 None）
    def ma60(i):
        if i < 59:
            return None
        return sum(closes[i - 59:i + 1]) / 60

    # 滚动计算「距近 250 日高点回撤」
    positions = []  # 1=持有, 0=空仓
    for i in range(len(closes)):
        if i < 250:
            positions.append(1)
            continue
        high = max(closes[i - 250:i + 1])
        dd = (closes[i] - high) / high * 100  # 负值，越深越负

        cheap = dd <= -lookback_pct        # 估值低（回撤深）
        expensive = dd >= -top_pct         # 估值高（接近新高）

        if use_trend_filter:
            m = ma60(i)
            above_trend = (m is not None and closes[i] > m)
            if cheap and above_trend:
                positions.append(1)   # 便宜 + 趋势转好 → 买
            elif expensive:
                positions.append(0)   # 贵 → 卖
            else:
                positions.append(positions[-1])  # 维持
        else:
            if cheap:
                positions.append(1)
            elif expensive:
                positions.append(0)
            else:
                positions.append(positions[-1])

    # 计算策略收益（用日收益累乘，含 A 股交易成本）
    def calc_ret(pos_list):
        ret = 1.0
        # A 股成本：佣金双边 0.025%、印花税卖出 0.05%、过户费双边 0.001%、滑点 0.1%
        buy_cost = 0.00025 + 0.00001 + 0.001   # 佣金 + 过户费 + 滑点
        sell_cost = 0.00025 + 0.0005 + 0.00001 + 0.001  # 再加印花税
        for i in range(1, len(closes)):
            # 状态切换（前一交易日决定持仓，当日生效）：切换日计入换手成本
            if pos_list[i] != pos_list[i - 1]:
                if pos_list[i] == 1:
                    ret *= (1 - buy_cost)   # 空仓 → 持有：买入成本
                else:
                    ret *= (1 - sell_cost)  # 持有 → 空仓：卖出成本
            if pos_list[i - 1] == 1:  # 前一交易日持有，吃当天涨跌
                ret *= closes[i] / closes[i - 1]
        return ret - 1.0

    strategy_ret = calc_ret(positions)
    hold_ret = closes[-1] / closes[0] - 1.0

    # 年化（按约 3 年）
    years = len(closes) / 252
    strategy_ann = (1 + strategy_ret) ** (1 / years) - 1 if years > 0 else 0
    hold_ann = (1 + hold_ret) ** (1 / years) - 1 if years > 0 else 0

    # 最大回撤（策略，含交易成本，与 calc_ret 口径一致）
    def max_drawdown(pos_list):
        peak = -1e18
        max_dd = 0.0
        equity = 1.0
        buy_cost = 0.00025 + 0.00001 + 0.001
        sell_cost = 0.00025 + 0.0005 + 0.00001 + 0.001
        for i in range(1, len(closes)):
            if pos_list[i] != pos_list[i - 1]:
                if pos_list[i] == 1:
                    equity *= (1 - buy_cost)
                else:
                    equity *= (1 - sell_cost)
            if pos_list[i - 1] == 1:
                equity *= closes[i] / closes[i - 1]
            if equity > peak:
                peak = equity
            dd = (equity - peak) / peak if peak > 0 else 0
            if dd < max_dd:
                max_dd = dd
        return max_dd

    strategy_mdd = max_drawdown(positions)
    hold_mdd = _hold_max_drawdown(closes)

    # 持仓时间占比
    holding_days = sum(positions)
    holding_ratio = holding_days / len(positions)

    return {
        "name": name,
        "code": code,
        "strategy_ret": strategy_ret,
        "hold_ret": hold_ret,
        "strategy_ann": strategy_ann,
        "hold_ann": hold_ann,
        "strategy_mdd": strategy_mdd,
        "hold_mdd": hold_mdd,
        "holding_ratio": holding_ratio,
        "lookback_pct": lookback_pct,
        "top_pct": top_pct,
        "use_trend_filter": use_trend_filter,
        "period": f"{dates[0]} ~ {dates[-1]}",
    }


def _hold_max_drawdown(closes: List[float]) -> float:
    peak = -1e18
    mdd = 0.0
    for c in closes:
        if c > peak:
            peak = c
        dd = (c - peak) / peak if peak > 0 else 0
        if dd < mdd:
            mdd = dd
    return mdd


def run_backtests() -> List[Dict]:
    """对多个宽基指数跑「估值+趋势」双确认择时回测。"""
    results = []
    for code in ["000300", "399006", "000905", "000688"]:
        if code not in INDEX_CONFIG:
            continue
        r = backtest_valuation_timing(code, use_trend_filter=True)
        if "error" not in r:
            results.append(r)
    return results
