# -*- coding: utf-8 -*-
"""最终验证：扩池(多资产) + 波动率目标 + cap倾斜，三者叠加能否更优。

思路：
  第一轮结论 —— 扩池+波动率目标 夏普 2.19 / 回撤 -8.4% / Calmar 92（最稳健）
  第二轮结论 —— cap=0.4 趋势强度倾斜 收益 979% / 夏普 1.65（保留alpha、不赌单标的）
  本脚本 —— 把两者叠加：在扩池+波动率目标框架里，把「等权」换成「cap封顶倾斜」，
           看能否拿到「夏普更高 + 收益更高」的更好组合。

复用 etf_rotation_enhanced 的波动率目标/换手容忍带/成本口径。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation import ETF_POOL, MULTI_ASSET_POOL, build_panel, perf, \
    COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE

VOL_TARGET = 0.18
VOL_WINDOW = 20
VOL_LEVER_CAP = 1.0


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


def tilt_weights(sel, close_i, ma_i, cols, cap):
    """cap 封顶的趋势强度倾斜权重。"""
    dev = {c: max(close_i[cols.index(c)] / ma_i[cols.index(c)] - 1, 0.0) for c in sel}
    total = sum(dev.values())
    if total <= 0:
        return {c: 1.0 / len(sel) for c in sel}
    w = {c: dev[c] / total for c in sel}
    for _ in range(50):
        over = [c for c in sel if w[c] > cap]
        if not over:
            break
        below = [c for c in sel if w[c] <= cap]
        if not below:
            w = {c: cap for c in sel}
            break
        spill = sum(w[c] - cap for c in over)
        for c in over:
            w[c] = cap
        rem = sum(dev[c] for c in below)
        for c in below:
            w[c] += spill * (dev[c] / rem if rem > 0 else 1.0 / len(below))
    s = sum(w.values())
    return {c: w[c] / s for c in sel}


def backtest(panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2,
             top_n=None, use_vol_target=False, vol_target=VOL_TARGET,
             vol_window=VOL_WINDOW, keep_ratio=1.0, tilt_cap=None):
    """扩池框架回测，tilt_cap 非 None 时把等权换成 cap 封顶倾斜。"""
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values
    ma = pd.DataFrame(close).rolling(ma_period).mean().values
    start = max(ma_period, lookback + 1)

    held = {}
    rets = []

    for i in range(start, n):
        if i % rebalance == 0 or not held:
            above = [cols[j] for j in range(m) if close[i, j] > ma[i, j]]
            if len(above) >= max(1, min_candidates):
                past = close[i - lookback:i]
                mom = {c: past[-1][cols.index(c)] / past[0][cols.index(c)] - 1
                       for c in above}
                ranked = sorted(above, key=lambda c: mom[c], reverse=True)
                sel = ranked if top_n is None else ranked[:top_n]
                if tilt_cap is None:
                    new_held = {c: 1.0 / len(sel) for c in sel}
                else:
                    new_held = tilt_weights(sel, close[i], ma[i], cols, tilt_cap)
            else:
                new_held = {}
        else:
            new_held = held

        if keep_ratio < 1.0 and held and new_held:
            overlap = len(set(held.keys()) & set(new_held.keys()))
            maxlen = max(len(held), len(new_held))
            if overlap / maxlen >= keep_ratio:
                new_held = held

        scale = 1.0
        if use_vol_target and new_held:
            if i >= start + vol_window:
                hist = np.array(rets[-(vol_window):])
                realized_vol = np.std(hist) * np.sqrt(250) if len(hist) > 1 else 0.0
                if realized_vol > 0:
                    scale = min(vol_target / realized_vol, VOL_LEVER_CAP)
                    scale = max(scale, 0.0)
            new_held = {c: w * scale for c, w in new_held.items()}

        tc = turnover_cost(list(held.keys()), list(new_held.keys())) \
            if new_held != held else 0.0
        held = new_held

        if held:
            ret = sum(w * (close[i, cols.index(c)] / close[i - 1, cols.index(c)] - 1)
                      for c, w in held.items())
        else:
            ret = 0.0
        rets.append(ret - tc)

    return pd.Series(rets, index=panel.index[start:])


def main():
    print("拉取数据...")
    panel = build_panel(MULTI_ASSET_POOL)      # 多资产池（含黄金/原油/30年国债）
    panel_orig = build_panel(ETF_POOL)         # 原池
    common = max(panel.index[0], panel_orig.index[0])
    panel = panel[panel.index >= common]
    panel_orig = panel_orig[panel_orig.index >= common]
    print(f"多资产池：{panel.shape[0]} 日 × {panel.shape[1]} 只")
    print(f"原池    ：{panel_orig.shape[0]} 日 × {panel_orig.shape[1]} 只\n")

    base = dict(ma_period=20, lookback=20, rebalance=5, min_candidates=2)

    def show(name, rets):
        t, a, d, s = perf(rets)
        c = t / abs(d) if d < 0 else 0
        vol = rets.std() * np.sqrt(250)
        print(f"{name:26s}{t*100:>8.1f}%{s:>7.2f}{d*100:>7.1f}%{vol*100:>7.1f}%{c:>8.1f}")

    print("=" * 84)
    print("  叠加验证：扩池 + 波动率目标 + cap倾斜（MA20/调仓5/门槛2，含A股成本）")
    print("=" * 84)
    print(f"{'方案':26s}{'累计':>8s}{'夏普':>7s}{'回撤':>7s}{'日波动':>7s}{'Calmar':>8s}")
    print("-" * 84)

    # 参照系
    show("① 扩池等权(无波动率)", backtest(panel, **base))
    show("② 扩池等权+波动率目标", backtest(panel, use_vol_target=True, **base))
    show("③ 原池等权+波动率目标", backtest(panel_orig, use_vol_target=True, **base))

    print()
    # 叠加：扩池 + 波动率目标 + 不同 cap 倾斜
    print("  叠加：扩池 + 波动率目标 + cap趋势强度倾斜")
    for cap in [0.3, 0.4, 0.5]:
        show(f"    cap={cap}倾斜+波动率",
             backtest(panel, use_vol_target=True, tilt_cap=cap, **base))

    print()
    # 叠加 + 换手容忍带
    print("  再叠加换手容忍带 90%（cap=0.4）")
    show("    cap=0.4+波动率+容忍带90%",
         backtest(panel, use_vol_target=True, tilt_cap=0.4, keep_ratio=0.9, **base))

    print()
    print("  说明：目标是同时拿到「比2.19更高的夏普」和「比等权更高的收益」。")
    print("  本分析仅供研究参考，不构成投资建议。")
    print("=" * 84)


if __name__ == "__main__":
    main()
