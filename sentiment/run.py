"""市场情绪多因子择时策略 —— 主入口。

用法：
    .venv/Scripts/python.exe -m sentiment.run

输出：
  1. 7 因子数据覆盖概览
  2. 单因子有效性（IC 与方向是否符合预期）
  3. 择时回测对比（买入持有 vs 情绪择时 vs 反向信号）
  4. 参数敏感性
  5. 当前情绪快照（各因子分位 + 综合仓位建议）
"""

from __future__ import annotations

import warnings

warnings.filterwarnings("ignore")

from sentiment.fetcher import build_monthly_panel
from sentiment.engine import (build_factor_scores, composite_heat,
                              heat_to_position, current_status,
                              factor_effectiveness, FACTOR_CN)
from sentiment.backtest import (fetch_benchmark_index, backtest_compare,
                                sensitivity, perf)

W = 78


def _fmt_pct(v, nd=1):
    return "N/A" if v is None else f"{v * 100:.{nd}f}%"


def main():
    print("=" * W)
    print("  市场情绪多因子择时策略")
    print("  因子：换手率 / 成交额 / 融资余额 / 新增开户数 / 基金发行热度")
    print("        股债性价比 / 波动率指数(QVIX)")
    print("=" * W)

    # ---- 数据 ----
    print("\n[1] 数据采集与覆盖")
    panel = build_monthly_panel()
    print(f"  月度面板：{panel.shape[0]} 个月 × {panel.shape[1]} 个因子")
    print(f"  区间：{panel.index[0].date()} ~ {panel.index[-1].date()}")
    print("  各因子数据覆盖：")
    for col in panel.columns:
        s = panel[col].dropna()
        if len(s):
            print(f"    {FACTOR_CN.get(col, col):8s}  {s.index[0].date()} ~ "
                  f"{s.index[-1].date()}  ({len(s)} 月)")
        else:
            print(f"    {FACTOR_CN.get(col, col):8s}  无数据")

    # 明确数据约束
    print("\n  ⚠️ 数据约束（真实可得性，非策略缺陷）：")
    print("     · 新增开户数：中登 2015-04 起披露，且 2023-08 后停止更新")
    print("     · 基金发行热度：东财新发基金接口仅回溯至 2023 年")
    print("     · 波动率指数 QVIX：2015-02 起")
    print("     · 融资余额：2012-06 起")

    # ---- 单因子有效性 ----
    print("\n[2] 单因子有效性（IC：因子信号 vs 未来1月沪深300收益）")
    bench = fetch_benchmark_index()
    idx = bench.set_index("date")["close"]
    fwd = idx.pct_change().shift(-1)  # 未来1月收益

    scores = build_factor_scores(panel, window=24)
    eff = factor_effectiveness(scores, fwd)
    if len(eff):
        for _, r in eff.iterrows():
            mark = "✓" if r["符合预期"] else "✗(方向不符)"
            print(f"    {r['因子']:8s}  IC={r['IC']:+.3f}  {mark}")
    else:
        print("    （样本不足，跳过）")

    # ---- 综合信号 + 回测 ----
    print("\n[3] 情绪择时回测（沪深300，月度调仓，无杠杆）")
    heat = composite_heat(scores)
    pos = heat_to_position(heat, overheat=1.0, ice=-1.0)

    cmp = backtest_compare(panel, pos, bench)
    print(f"  {'策略':16s}{'累计':>9s}{'年化':>8s}{'最大回撤':>9s}{'波动':>7s}{'夏普':>7s}")
    b, s, iv = cmp["bench"], cmp["strat"], cmp["inverse"]
    print(f"  {'买入持有':16s}{_fmt_pct(b['total'],0):>9s}{_fmt_pct(b['ann']):>8s}"
          f"{_fmt_pct(b['max_dd']):>9s}{_fmt_pct(b['vol']):>7s}{b['sharpe']:>7.2f}")
    print(f"  {'★情绪择时':16s}{_fmt_pct(s['total'],0):>9s}{_fmt_pct(s['ann']):>8s}"
          f"{_fmt_pct(s['max_dd']):>9s}{_fmt_pct(s['vol']):>7s}{s['sharpe']:>7.2f}")
    print(f"  {'反向信号(对照)':16s}{_fmt_pct(iv['total'],0):>9s}{_fmt_pct(iv['ann']):>8s}"
          f"{_fmt_pct(iv['max_dd']):>9s}{_fmt_pct(iv['vol']):>7s}{iv['sharpe']:>7.2f}")
    print(f"  · 平均仓位（择时激进度）：{_fmt_pct(cmp['avg_pos'])}")
    print(f"  · 回测样本：{b['n']} 个月")

    # ---- 参数敏感性 ----
    print("\n[4] 参数敏感性（阈值 × 滚动窗口，夏普/回撤）")
    sens = sensitivity(panel, bench)
    sens = sens.sort_values("sharpe", ascending=False)
    print(sens.head(6).round(3).to_string(index=False))

    # ---- 当前快照 ----
    print("\n[5] 当前情绪快照")
    snap = current_status(panel, scores, heat)
    print(f"  {'因子':12s}{'当前值':>14s}{'近3年分位':>10s}{'信号方向':>12s}")
    for col, d in snap.items():
        arrow = "过热↑" if d["sign"] > 0 else "低估↓"
        print(f"  {d['cn']:12s}{d['value']:>14.4g}{d['pct']:>9.0f}%{arrow:>12s}")
    last_heat = heat.dropna().iloc[-1]
    last_pos = pos.dropna().iloc[-1]
    print(f"\n  ▶ 综合情绪热度：{last_heat:+.2f}（>1 过热 / <-1 冰点）")
    print(f"  ▶ 建议仓位：{last_pos * 100:.0f}%")

    print("\n" + "=" * W)
    print("  说明：本策略为情绪逆向择时——「众人贪婪我恐惧，众人恐惧我贪婪」。")
    print("  数据仅供研究参考，不构成投资建议。")
    print("=" * W)

    # ---- 记录到策略台账 ----
    try:
        from strategy_log import record
        record("sentiment", {
            "heat": float(last_heat),
            "position": float(last_pos),
            "signal": "过热" if last_heat >= 1 else ("冰点" if last_heat <= -1 else "中性"),
            "factors": {col: float(d["pct"]) for col, d in snap.items()},
        })
    except Exception as e:  # noqa
        print(f"  [警告] 记录到台账失败: {e}")


if __name__ == "__main__":
    main()
