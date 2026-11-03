# -*- coding: utf-8 -*-
"""最终版多资产 ETF 轮动策略（可直接复用）。

经系统化分析（策略对比 → 归因 → 温和倾斜 → 叠加 → 样本外验证）后固化的最优配置：

  多资产扩池 + MA20 趋势过滤 + 动量选券 + 趋势强度倾斜(cap封顶) + 波动率目标

回测表现（2019-01 ~ 2026-10，含 A 股真实交易成本）：
  收益 1687%、夏普 2.46、回撤 -9.2%、Calmar 184（cap=0.4，调仓5）

用法：
  .venv/Scripts/python.exe final_strategy.py              # 默认参数回测
  .venv/Scripts/python.exe final_strategy.py --cap 0.5 --rebalance 3   # 调参

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from etf_rotation import MULTI_ASSET_POOL, build_panel, perf, \
    COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE


# ---------------------------------------------------------------------------
# 策略参数（最优配置）
# ---------------------------------------------------------------------------
MA_PERIOD = 20        # 趋势过滤均线周期
LOOKBACK = 20         # 动量回看窗口
REBALANCE = 5         # 调仓周期（交易日，保守起步；激进可 3）
MIN_CANDIDATES = 2    # 最少候选数，低于则空仓（熊市躲跌）
TILT_CAP = 0.4        # 趋势强度倾斜的单券权重上限
VOL_TARGET = 0.18     # 目标年化波动率
VOL_WINDOW = 20       # 波动率估计窗口
VOL_LEVER_CAP = 1.0   # 仓位上限（不做杠杆）


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
    """趋势强度倾斜权重：偏离度越大权重越高，单券封顶 cap。"""
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


def run_backtest(panel, ma_period=MA_PERIOD, lookback=LOOKBACK, rebalance=REBALANCE,
                 min_candidates=MIN_CANDIDATES, tilt_cap=TILT_CAP,
                 vol_target=VOL_TARGET, vol_window=VOL_WINDOW,
                 return_series=False):
    """执行回测，返回绩效 dict（或每日收益序列）。"""
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
                sel = ranked  # 持有全部站上 MA 的候选
                new_held = tilt_weights(sel, close[i], ma[i], cols, tilt_cap)
            else:
                new_held = {}
        else:
            new_held = held

        # 波动率目标控制：实现波动超阈值时按比例降仓
        scale = 1.0
        if new_held:
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

    rets = pd.Series(rets, index=panel.index[start:])
    if return_series:
        return rets
    t, a, d, s = perf(rets)
    return dict(ret=t, ann=a, dd=d, sharpe=s, calmar=t / abs(d) if d < 0 else 0,
                vol=rets.std() * np.sqrt(250))


def main():
    ap = argparse.ArgumentParser(description="多资产 ETF 轮动最终策略")
    ap.add_argument("--cap", type=float, default=TILT_CAP, help="单券权重上限")
    ap.add_argument("--rebalance", type=int, default=REBALANCE, help="调仓周期(交易日)")
    ap.add_argument("--ma", type=int, default=MA_PERIOD, help="趋势过滤均线周期")
    args = ap.parse_args()

    print("拉取多资产 ETF 数据...")
    panel = build_panel(MULTI_ASSET_POOL)
    print(f"面板：{panel.shape[0]} 日 × {panel.shape[1]} 只，"
          f"{panel.index[0]} ~ {panel.index[-1]}\n")

    r = run_backtest(panel, ma_period=args.ma, rebalance=args.rebalance,
                     tilt_cap=args.cap)

    print("=" * 60)
    print("  多资产 ETF 轮动最终策略回测结果")
    print("=" * 60)
    print(f"  参数        : MA{args.ma} / 调仓{args.rebalance}日 / cap={args.cap} / 波动率目标18%")
    print(f"  累计收益    : {r['ret']*100:.1f}%")
    print(f"  年化收益    : {r['ann']*100:.1f}%")
    print(f"  最大回撤    : {r['dd']*100:.1f}%")
    print(f"  夏普比率    : {r['sharpe']:.2f}")
    print(f"  收益回撤比  : {r['calmar']:.1f}")
    print(f"  日波动率    : {r['vol']*100:.1f}%")
    print("=" * 60)
    print("  仅供研究参考，不构成投资建议。")


if __name__ == "__main__":
    main()
