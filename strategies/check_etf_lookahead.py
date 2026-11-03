# -*- coding: utf-8 -*-
"""
ETF 轮动策略 前视偏差复查

目的：检查 etf_rotation 系列回测是否存在 look-ahead bias（前视偏差），
并量化「修正前 vs 修正后」的真实差异。

发现的问题（与个股引擎相同的 bug）：
1. 趋势过滤用 close[i] > ma[i]，其中 ma[i] 含当日收盘价 → 偷看当日
2. 动量 past = close[i-lookback:i] 含当日收盘价 → 偷看当日
3. 用 i 日选出的持仓，计算 i-1→i 的收益 → 时间穿越

正确口径：所有信号用「截至昨日(T-1)收盘」的数据，决定 T 日持仓，吃 T 日真实涨跌。

本脚本提供 corrected_backtest_rotation（修正版）与 corrected_backtest_enhanced（修正版增强），
并与原 etf_rotation 的 backtest_rotation / etf_rotation_enhanced 的 backtest_enhanced 对比。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation import (MULTI_ASSET_POOL, build_panel, perf,
                          COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE)
from etf_rotation import backtest_rotation as original_backtest_rotation
from etf_rotation_enhanced import backtest_enhanced as original_backtest_enhanced


def corrected_backtest_rotation(panel, ma_period=20, lookback=20, rebalance=5,
                                min_candidates=2, top_n=5, cost=True):
    """修正前视偏差后的趋势过滤+动量轮动。

    关键：所有信号前移一天（用 T-1 收盘数据决定 T 日持仓）。
    """
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values

    # 均线 shift(1)：用"截至昨日"的均线判断今日是否持有
    ma = pd.DataFrame(close).rolling(ma_period).mean().shift(1).values

    start = max(ma_period, lookback + 1) + 1  # 多留 1 日给 shift

    rets = []
    held = []
    for i in range(start, n):
        if i % rebalance == 0 or not held:
            # 趋势过滤：昨日收盘站上昨日 MA
            above_ma = [cols[j] for j in range(m)
                        if close[i - 1, j] > ma[i, j] and not np.isnan(ma[i, j])]
            if len(above_ma) >= max(1, min_candidates):
                # 动量：截至昨日的近 lookback 日涨幅
                past = close[i - lookback - 1:i - 1]
                mom = past[-1] / past[0] - 1
                ranked = sorted(above_ma, key=lambda c: mom[cols.index(c)], reverse=True)
                new_held = ranked[:top_n]
            else:
                new_held = []

            turnover_cost = 0.0
            if cost and new_held != held:
                sell_names = [c for c in held if c not in new_held]
                if sell_names:
                    sell_w = len(sell_names) / len(held) if held else 0.0
                    turnover_cost += sell_w * (COMMISSION + STAMP_TAX + TRANSFER_FEE + SLIPPAGE)
                buy_names = [c for c in new_held if c not in held]
                if buy_names:
                    buy_w = len(buy_names) / len(new_held) if new_held else 0.0
                    turnover_cost += buy_w * (COMMISSION + TRANSFER_FEE + SLIPPAGE)
            held = new_held
        else:
            turnover_cost = 0.0

        if held:
            ret = 0.0
            for c in held:
                j = cols.index(c)
                ret += (close[i, j] / close[i - 1, j] - 1)
            ret /= len(held)
        else:
            ret = 0.0
        rets.append(ret - turnover_cost)

    return pd.Series(rets, index=panel.index[start:])


def corrected_backtest_enhanced(panel, ma_period=20, lookback=20, rebalance=5,
                                min_candidates=2, top_n=None,
                                use_vol_target=False, vol_target=0.18,
                                vol_window=20, keep_ratio=1.0):
    """修正前视偏差后的增强回测（趋势过滤+动量轮动+波动率目标+换手容忍带）。"""
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values

    ma = pd.DataFrame(close).rolling(ma_period).mean().shift(1).values

    start = max(ma_period, lookback + 1) + 1

    held = {}
    rets = []

    for i in range(start, n):
        if i % rebalance == 0 or not held:
            above = [cols[j] for j in range(m)
                     if close[i - 1, j] > ma[i, j] and not np.isnan(ma[i, j])]
            if len(above) >= max(1, min_candidates):
                past = close[i - lookback - 1:i - 1]
                mom = {c: past[-1][cols.index(c)] / past[0][cols.index(c)] - 1
                       for c in above}
                ranked = sorted(above, key=lambda c: mom[c], reverse=True)
                sel = ranked if top_n is None else ranked[:top_n]
                new_held = {c: 1.0 / len(sel) for c in sel}
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
                hist = np.array(rets[-vol_window:])
                realized_vol = np.std(hist) * np.sqrt(250) if len(hist) > 1 else 0.0
                if realized_vol > 0:
                    scale = min(vol_target / realized_vol, 1.0)
                    scale = max(scale, 0.0)
            new_held = {c: w * scale for c, w in new_held.items()}

        if new_held != held:
            tc = 0.0
            sell_names = [c for c in held if c not in new_held]
            buy_names = [c for c in new_held if c not in held]
            if sell_names:
                sell_w = len(sell_names) / len(held) if held else 0.0
                tc += sell_w * (COMMISSION + STAMP_TAX + TRANSFER_FEE + SLIPPAGE)
            if buy_names:
                buy_w = len(buy_names) / len(new_held) if new_held else 0.0
                tc += buy_w * (COMMISSION + TRANSFER_FEE + SLIPPAGE)
        else:
            tc = 0.0
        held = new_held

        if held:
            ret = sum(w * (close[i, cols.index(c)] / close[i - 1, cols.index(c)] - 1)
                      for c, w in held.items())
        else:
            ret = 0.0
        rets.append(ret - tc)

    return pd.Series(rets, index=panel.index[start:])


def show(name, rets):
    t, a, d, s = perf(rets)
    c = t / abs(d) if d < 0 else 0
    print(f"{name:34s} 累计={t*100:8.1f}%  年化={a*100:5.1f}%  "
          f"回撤={d*100:6.1f}%  夏普={s:.2f}  Calmar={c:.1f}")


def main():
    print("正在拉取 ETF 数据（多资产池）...")
    panel = build_panel(MULTI_ASSET_POOL)
    print(f"面板：{panel.shape[0]} 日 × {panel.shape[1]} 只，{panel.index[0]} ~ {panel.index[-1]}\n")

    # 基准
    bench = panel.pct_change().mean(axis=1).dropna()
    bench.iloc[0] -= (COMMISSION + TRANSFER_FEE + SLIPPAGE)

    print("=" * 92)
    print("  【A】基础轮动策略：原版(有前视偏差) vs 修正版(无前视偏差)")
    print("=" * 92)
    show("基准(等权持有)", bench)
    show("原版 MA20+Top5 调仓5", original_backtest_rotation(
        panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=5))
    show("修正 MA20+Top5 调仓5", corrected_backtest_rotation(
        panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=5))
    show("原版 MA60+Top3 调仓20", original_backtest_rotation(
        panel, ma_period=60, lookback=20, rebalance=20, min_candidates=1, top_n=3))
    show("修正 MA60+Top3 调仓20", corrected_backtest_rotation(
        panel, ma_period=60, lookback=20, rebalance=20, min_candidates=1, top_n=3))

    print()
    print("=" * 92)
    print("  【B】增强策略（扩池+波动率目标）：原版 vs 修正版")
    print("=" * 92)
    base = dict(ma_period=20, lookback=20, rebalance=5, min_candidates=2)
    show("原版 扩池(全池等权)", original_backtest_enhanced(panel, **base))
    show("修正 扩池(全池等权)", corrected_backtest_enhanced(panel, **base))
    show("原版 扩池+波动率18%", original_backtest_enhanced(panel, use_vol_target=True, **base))
    show("修正 扩池+波动率18%", corrected_backtest_enhanced(panel, use_vol_target=True, **base))

    print()
    print("=" * 92)
    print("  【C】修正版参数扫描：看真实最优参数是否还成立")
    print("=" * 92)
    for reb in [5, 10, 20]:
        r = corrected_backtest_rotation(panel, ma_period=20, lookback=20,
                                        rebalance=reb, min_candidates=2, top_n=5)
        show(f"修正 MA20+Top5 调仓{reb}", r)


if __name__ == "__main__":
    main()
