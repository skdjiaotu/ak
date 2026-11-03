"""科创板位置监控 —— 主入口。

用法：
    .venv/Scripts/python.exe -m star_position.run

输出：科创50 位置温度 + 5 档信号 + 仓位建议（含「跌了但没变便宜」警示）。
"""

from __future__ import annotations

from star_position.fetcher import build_star50_dataset, FetchError
from star_position.engine import assess_position


def _pct(v):
    return "N/A" if v is None else f"{v * 100:.1f}%"


def _num(v, nd=2):
    return "N/A" if v is None else f"{v:.{nd}f}"


def main():
    W = 72
    print("=" * W)
    print("科创板位置监控 —— 高位风险提示 / 低位建仓信号")
    print("=" * W)

    try:
        ds = build_star50_dataset()
    except FetchError as e:
        print(f"❌ 数据采集失败: {e}")
        return

    r = assess_position(ds)

    print(f"\n数据时间: {ds['fetched_at']}    科创50(000688)")
    print(f"当前点位: {_num(r['latest'])}")

    print("\n【1】价格位置")
    print(f"  近3年分位:  {_pct(r['price_pct_3y'])}   （越高越接近高位）")
    print(f"  全历史分位: {_pct(r['price_pct_all'])}")
    print(f"  历史高点:   {_num(r['high_all'], 1)}   距其回撤 {_pct(r['dd_from_all'])}")

    print("\n【2】估值位置（蛋卷基金完整历史分位）")
    print(f"  PE-TTM:     {_num(r['pe_ttm'])} 倍   历史分位 {_pct(r['pe_pct'])}")
    print(f"  PB:         {_num(r['pb'])} 倍   历史分位 {_pct(r['pb_pct'])}")
    print(f"  ROE:        {_pct(r['roe'])}   股息率 {_pct(r['dividend_yield'])}")

    print("\n【3】均线结构")
    print(f"  MA60={_num(r['ma60'],1)}  MA250={_num(r['ma250'],1)}"
          f"  站上MA60:{'是' if r['above_ma60'] else '否'}"
          f"  站上MA250:{'是' if r['above_ma250'] else '否'}")

    print("\n" + "-" * W)
    temp = r["position_temp"]
    print(f"【位置温度】{_num(temp, 1)} / 100   （越高越危险）")
    print(f"  信号: {r['signal']}")
    print(f"  建议仓位: {_num(r['suggest_pos'] * 100, 0)}%")
    print(f"  建议: {r['advice']}")
    print("-" * W)

    print("\n【温度构成】（0=低位安全，100=高位危险）")
    labels = {"price": "价格分位(35%)", "pe": "估值分位(45%)", "drawdown": "距高点(20%)"}
    for k, label in labels.items():
        if k in r["components"]:
            v = r["components"][k]
            bar = "█" * int(v / 5)
            print(f"  {label:<14} {v:>5.1f}  {bar}")

    if r["divergence"]:
        print("\n" + "=" * W)
        print(r["div_note"])
        print("=" * W)

    print("\n⚠️ 位置分位低 ≠ 不会继续跌；本评估仅供研究参考，不构成投资建议。")

    # ---- 记录到策略台账 ----
    try:
        from strategy_log import record
        record("star_position", {
            "latest": r["latest"],
            "position_temp": r["position_temp"],
            "suggest_pos": r["suggest_pos"],
            "pe_ttm": r["pe_ttm"],
            "pe_pct": r["pe_pct"],
            "pb": r["pb"],
            "pb_pct": r["pb_pct"],
            "roe": r["roe"],
            "price_pct_3y": r["price_pct_3y"],
            "price_pct_all": r["price_pct_all"],
            "dd_from_all": r["dd_from_all"],
            "ma60": r["ma60"],
            "ma250": r["ma250"],
            "above_ma60": r["above_ma60"],
            "above_ma250": r["above_ma250"],
            "components": r["components"],
            "signal": r["signal"],
            "advice": r["advice"],
        })
    except Exception as e:  # noqa
        print(f"[警告] 记录到台账失败: {e}")


if __name__ == "__main__":
    main()
