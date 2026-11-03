# -*- coding: utf-8 -*-
"""深入分析「趋势强度加权」收益爆表的真实原因。

回答三个问题：
  Q1. 它是不是靠「集中度/隐形杠杆」而非 alpha？
  Q2. 收益是否只在一个窄参数窗口（参数运气/过拟合）才爆表？
  Q3. 分年度是否稳健，还是被某一年暴涨撑起来？

复用 etf_rotation 的 cost/perf 口径，保证与原始回测一致。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation import ETF_POOL, build_panel, perf, \
    COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE


def turnover_cost(old_held, new_held):
    if new_held == old_held:
        return 0.0
    sell_names = [c for c in old_held if c not in new_held]
    buy_names = [c for c in new_held if c not in old_held]
    cost = 0.0
    if sell_names:
        sell_w = len(sell_names) / len(old_held) if old_held else 0.0
        cost += sell_w * (COMMISSION + STAMP_TAX + TRANSFER_FEE + SLIPPAGE)
    if buy_names:
        buy_w = len(buy_names) / len(new_held) if new_held else 0.0
        cost += buy_w * (COMMISSION + TRANSFER_FEE + SLIPPAGE)
    return cost


def run_weighted(panel, ma_period=20, lookback=20, rebalance=5,
                 min_candidates=2, top_n=5, weight_mode="equal"):
    """复现 backtest_weighted，同时统计换手次数与持仓集中度。"""
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values
    ma = pd.DataFrame(close).rolling(ma_period).mean().values
    ret_panel = pd.DataFrame(close).pct_change().values
    start = max(ma_period, lookback + 1)

    held = {}
    rets = []
    turnovers = 0            # 实际发生换仓的调仓次数
    conc_series = []         # 每次持仓的最大单券权重（集中度）
    dates = panel.index

    for i in range(start, n):
        if i % rebalance == 0 or not held:
            above = [cols[j] for j in range(m) if close[i, j] > ma[i, j]]
            if len(above) >= max(1, min_candidates):
                past = close[i - lookback:i]
                mom = {c: past[-1][cols.index(c)] / past[0][cols.index(c)] - 1
                       for c in above}
                ranked = sorted(above, key=lambda c: mom[c], reverse=True)
                sel = ranked[:top_n]

                if weight_mode == "equal":
                    w = {c: 1.0 / len(sel) for c in sel}
                elif weight_mode == "momentum":
                    pos_mom = {c: max(mom[c], 0.0) for c in sel}
                    total = sum(pos_mom.values())
                    w = ({c: pos_mom[c] / total for c in sel} if total > 0
                         else {c: 1.0 / len(sel) for c in sel})
                elif weight_mode == "low_vol":
                    vols = {}
                    for c in sel:
                        j = cols.index(c)
                        std = np.nanstd(ret_panel[i - lookback:i, j])
                        vols[c] = 1.0 / std if std > 0 else 1.0
                    total = sum(vols.values())
                    w = {c: vols[c] / total for c in sel}
                elif weight_mode == "trend_strength":
                    dev = {c: (close[i, cols.index(c)] / ma[i, cols.index(c)] - 1)
                           for c in sel}
                    total = sum(max(dev[c], 0.0) for c in sel)
                    w = ({c: max(dev[c], 0.0) / total for c in sel} if total > 0
                         else {c: 1.0 / len(sel) for c in sel})
                else:
                    w = {c: 1.0 / len(sel) for c in sel}

                new_held = w
            else:
                new_held = {}

            if new_held != held:
                tc = turnover_cost(list(held.keys()), list(new_held.keys()))
                if new_held and held:
                    turnovers += 1
            else:
                tc = 0.0
            held = new_held
        else:
            tc = 0.0

        if held:
            conc_series.append(max(held.values()))
            ret = sum(held[c] * (close[i, cols.index(c)] / close[i - 1, cols.index(c)] - 1)
                      for c in held)
        else:
            conc_series.append(0.0)
            ret = 0.0
        rets.append(ret - tc)

    rets = pd.Series(rets, index=dates[start:])
    return rets, turnovers, np.mean(conc_series), np.max(conc_series)


def yearly(panel, rets):
    """分年度收益拆解。"""
    years = [int(str(d)[:4]) for d in rets.index]
    yr = pd.Series(years, index=rets.index)
    out = {}
    for y, sub in rets.groupby(yr):
        out[y] = (1 + sub).prod() - 1
    return out


def main():
    print("拉取 ETF 数据...")
    panel = build_panel(ETF_POOL)
    print(f"面板：{panel.shape[0]} 日 × {panel.shape[1]} 只，"
          f"{panel.index[0]} ~ {panel.index[-1]}\n")

    modes = ["equal", "momentum", "low_vol", "trend_strength"]

    # ---------- Q1: 集中度 + 换手 + 波动 ----------
    print("=" * 76)
    print("  Q1. 集中度 / 换手 / 波动率 对比（MA20/调仓5/门槛2/Top5）")
    print("=" * 76)
    print(f"{'加权方式':14s}{'累计':>8s}{'夏普':>7s}{'回撤':>8s}"
          f"{'日波动':>8s}{'换手次':>7s}{'均集中度':>9s}{'最大集中':>9s}")
    store = {}
    for mode in modes:
        rets, tv, conc, maxc = run_weighted(panel, weight_mode=mode)
        t, a, d, s = perf(rets)
        vol = rets.std() * np.sqrt(250)
        store[mode] = rets
        print(f"{mode:14s}{t*100:>7.1f}%{s:>7.2f}{d*100:>7.1f}%"
              f"{vol*100:>7.1f}%{tv:>7d}{conc*100:>8.1f}%{maxc*100:>8.1f}%")

    # ---------- Q3: 分年度 ----------
    print("\n" + "=" * 76)
    print("  Q3. 分年度收益拆解（趋势强度加权 vs 等权）")
    print("=" * 76)
    ts_y = yearly(panel, store["trend_strength"])
    eq_y = yearly(panel, store["equal"])
    print(f"{'年度':>6s}{'等权Top5':>12s}{'趋势强度加权':>14s}{'差值':>10s}")
    for y in sorted(ts_y):
        tsv = ts_y.get(y, 0)
        eqv = eq_y.get(y, 0)
        print(f"{y:>6d}{eqv*100:>11.1f}%{tsv*100:>13.1f}%{(tsv-eqv)*100:>9.1f}%")

    # ---------- Q2: 参数敏感性（趋势强度加权） ----------
    print("\n" + "=" * 76)
    print("  Q2. 参数敏感性：固定其他，横扫 ma_period / rebalance / top_n")
    print("      基线 = MA20 / 调仓5 / Top5（★ 标记）")
    print("=" * 76)

    def grid(name, cfg, key, vals):
        print(f"\n  --- 横扫 {name} ---")
        print(f"{'参数':>8s}{'累计':>9s}{'夏普':>7s}{'回撤':>8s}")
        for v in vals:
            c = dict(cfg)
            c[key] = v
            rets, _, _, _ = run_weighted(panel, weight_mode="trend_strength", **c)
            t, a, d, s = perf(rets)
            star = " ★" if v == cfg[key] else ""
            print(f"{v:>8}{t*100:>8.1f}%{s:>7.2f}{d*100:>7.1f}%{star}")

    base = dict(ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=5)
    grid("ma_period", base, "ma_period", [10, 15, 20, 30, 40, 60])
    grid("rebalance", base, "rebalance", [2, 3, 5, 10, 15, 20])
    grid("top_n", base, "top_n", [2, 3, 5, 8, 11])

    print("\n" + "=" * 76)
    print("  分析脚本仅供研究参考，不构成投资建议。")
    print("=" * 76)


if __name__ == "__main__":
    main()
