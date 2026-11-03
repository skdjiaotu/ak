"""资金面监控主入口 —— 北向资金 + 融资融券。

用法：
    .venv/Scripts/python.exe -m fund_flow.run

输出：资金面穿透报告，揭示"官方欣欣向荣"表象下的真实资金动向。
"""

from __future__ import annotations

import sys

from fund_flow.fetcher import fetch_all
from fund_flow.engine import assess, analyze_margin, analyze_northbound

W = 62


def _fmt_num(v, nd=2):
    if v is None:
        return "N/A"
    return f"{v:,.{nd}f}"


def _fmt_pct(v, nd=2):
    if v is None:
        return "N/A"
    return f"{v:.{nd}f}%"


def _yi(v):
    """元 -> 亿元。"""
    if v is None:
        return None
    return v / 1e8


def main():
    print("=" * W)
    print("  资金面穿透报告 ｜ 北向资金 · 融资融券")
    print("  目标：过滤「官方一片欣欣向荣」的假象，看真实资金动向")
    print("=" * W)

    data = fetch_all()
    result = assess(data)
    mg = result["margin"]
    nb = result["northbound"]

    # ---- 一、融资融券（最可靠的公开硬指标）----
    print("\n【1】融资融券 —— 杠杆资金的真实态度（数据完整公开）")
    print(f"  融资余额（杠杆做多）: {_fmt_num(_yi(mg['cur_balance']))} 亿元")
    print(f"  融资余额 20 日变化:   {_fmt_pct(mg['bal_20d'])}")
    print(f"  融资余额 60 日变化:   {_fmt_pct(mg['bal_60d'])}")
    print(f"  融资余额近3年分位:    {_fmt_pct(mg['bal_pct'] and mg['bal_pct']*100)}")
    print(f"  融资余额/流通市值:    {_fmt_pct(mg['cur_ratio'])}")
    print(f"  单日杠杆换手:         {_fmt_pct(mg['leverage_turnover'])}")
    print(f"  融券余额（做空力量）: {_fmt_num(_yi(mg['cur_short']))} 亿元（20日 {_fmt_pct(mg['short_20d'])}）")
    print(f"  融资买入额:           {_fmt_num(_yi(mg['cur_buy']))} 亿元/日")
    print(f"\n  ▶ 杠杆资金判定: {mg['trend_signal']}")
    print(f"  ▶ 情绪状态:     {mg['emotion']}")

    # ---- 二、北向资金（关键：净买入已停更）----
    print("\n【2】北向资金 —— 外资动向（净买入数据已停止披露）")
    print(f"  ⚠️ 当日净买入最后披露日: {nb['last_net_buy_date']}")
    print(f"  ⚠️ 净买入停更首日:       {nb['first_nan_date']}")
    print(f"  停更前累计净买入:       {_fmt_num(nb['last_cum_net_buy_yi'], 0)} 亿元")
    if nb["net_20d_yi"] is not None:
        print(f"  停更前 20 日净买入:     {_fmt_num(nb['net_20d_yi'], 1)} 亿元")
    if nb["net_60d_yi"] is not None:
        print(f"  停更前 60 日净买入:     {_fmt_num(nb['net_60d_yi'], 1)} 亿元")
    print(f"  停更前持股市值:         {_fmt_num(nb['hold_mv_yi'], 0)} 亿元")
    if nb["hold_20d"] is not None:
        print(f"  停更前持仓市值 20 日变化: {_fmt_pct(nb['hold_20d'])}（2024年7-8月，非当前）")
    print(f"  ▶ 外资态度推断: {nb['foreign_signal']}")
    # 关键洞察：边涨边卖
    if nb["net_60d_yi"] is not None and nb["net_60d_yi"] < 0 and nb["hold_60d"] is not None and nb["hold_60d"] > 0:
        print(f"  ⚠️ 洞察：停更前外资净卖出 {abs(nb['net_60d_yi']):.0f} 亿，但持仓市值仍在涨 → 外资「边涨边卖」")

    # ---- 三、综合结论 ----
    print("\n【3】资金面综合结论")
    if result["signals"]:
        for s in result["signals"]:
            print(f"  • {s}")
    else:
        print("  • 资金面信号中性，无明显方向")
    print()
    for n in result["notes"]:
        print(f"  {n}")

    print("\n" + "=" * W)
    print("  说明：两融数据每日完整公开（可穿透）；北向净买入自 2024-08-19")
    print("  停止披露，官方隐藏了外资净流向 —— 这本身就是「假象」的一部分。")
    print("=" * W)


if __name__ == "__main__":
    main()
