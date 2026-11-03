"""创业板位置评估 —— 主入口。

用法：
    .venv/Scripts/python.exe -m gem_position.run

输出：创业板指位置温度 + 5 档信号 + 仓位建议（命令行报告）。
"""

from __future__ import annotations

from gem_position.fetcher import build_gem_dataset, FetchError
from gem_position.engine import assess_position


def _pct(v):
    return "N/A" if v is None else f"{v * 100:.1f}%"


def _num(v, nd=2):
    return "N/A" if v is None else f"{v:.{nd}f}"


def main():
    W = 72
    print("=" * W)
    print("创业板位置评估 —— 高位风险提示 / 低位建仓信号")
    print("=" * W)

    try:
        ds = build_gem_dataset()
    except FetchError as e:
        print(f"❌ 数据采集失败: {e}")
        return

    r = assess_position(ds)
    cur = ds["current"]

    print(f"\n数据时间: {ds['fetched_at']}    创业板指(399006)")
    print(f"当前点位: {_num(r['latest'])}   当日涨跌: {_pct(cur.get('change_pct'))}")

    print("\n【1】价格位置")
    print(f"  近5年分位:  {_pct(r['price_pct_5y'])}   （越高越接近高位）")
    print(f"  全历史分位: {_pct(r['price_pct_all'])}")
    print(f"  近5年高点:  {_num(r['high_5y'], 1)}   距其回撤 {_pct(r['dd_from_5y'])}")
    print(f"  历史高点:   {_num(r['high_all'], 1)}   距其回撤 {_pct(r['dd_from_all'])}")

    print("\n【2】估值位置")
    print(f"  PE-TTM:     {_num(r['pe_ttm'])} 倍   历史分位 {_pct(r['pe_pct'])}"
          f"（创业板50 {r['pe_series_len']} 期）")
    print(f"  PB:         {_num(r['pb'])} 倍   历史分位 {_pct(r['pb_pct'])}")

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
    labels = {"price": "价格分位(40%)", "pe": "估值分位(40%)", "drawdown": "距高点(20%)"}
    for k, label in labels.items():
        if k in r["components"]:
            v = r["components"][k]
            bar = "█" * int(v / 5)
            print(f"  {label:<14} {v:>5.1f}  {bar}")

    print("\n" + "=" * W)
    print("⚠️ 位置分位低 ≠ 不会继续跌；本评估仅供研究参考，不构成投资建议。")
    print("=" * W)

    # ---- 记录到策略台账 ----
    try:
        from strategy_log import record
        record("gem_position", {
            "latest": r["latest"],
            "position_temp": r["position_temp"],
            "suggest_pos": r["suggest_pos"],
            "pe_ttm": r["pe_ttm"],
            "pe_pct": r["pe_pct"],
            "pb": r["pb"],
            "pb_pct": r["pb_pct"],
            "price_pct_5y": r["price_pct_5y"],
            "price_pct_all": r["price_pct_all"],
            "dd_from_5y": r["dd_from_5y"],
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
