# -*- coding: utf-8 -*-
"""验证「温和倾斜版趋势强度」—— 在等权基础上做有上限的权重倾斜。

问题：原版 trend_strength 把 98% 仓位押在单标的（赌单品种），收益爆表但不可落地。
方案：给单标的权重设上限 cap，把「极端集中」压回「温和倾斜」，观察：
  - 能否保留一部分 alpha（相对等权）
  - 同时把最大集中度 / 回撤控制住

设计三种倾斜方式：
  1. capped_dev   —— 趋势强度加权，但单券权重封顶 cap（超出部分摊回其他券）
  2. blend        —— 等权与趋势强度的线性混合：w = (1-α)·equal + α·dev
  3. softmax_tau  —— 用 softmax(偏离度/温度) 平滑，温度越高越接近等权

统一 MA20/调仓5/门槛2/Top5，含 A 股成本，与原始回测同口径。
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


def _weights(sel, close_i, ma_i, cols, mode, cap=0.4, alpha=0.5, tau=0.05):
    """按 mode 计算权重。sel 是已按动量排序选出的 TopN 标的名单。"""
    n = len(sel)
    equal = 1.0 / n

    if mode == "equal":
        return {c: equal for c in sel}

    if mode == "trend_strength":
        dev = {c: max(close_i[cols.index(c)] / ma_i[cols.index(c)] - 1, 0.0) for c in sel}
        total = sum(dev.values())
        return ({c: dev[c] / total for c in sel} if total > 0
                else {c: equal for c in sel})

    if mode == "capped_dev":
        # 趋势强度加权，但单券封顶 cap：迭代把超出的权重按剩余券的偏离度比例再分配
        dev = {c: max(close_i[cols.index(c)] / ma_i[cols.index(c)] - 1, 0.0) for c in sel}
        total = sum(dev.values())
        if total <= 0:
            return {c: equal for c in sel}
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
            # 按剩余券的偏离度比例分配 spill
            rem = sum(dev[c] for c in below)
            for c in below:
                w[c] += spill * (dev[c] / rem if rem > 0 else 1.0 / len(below))
        s = sum(w.values())
        w = {c: w[c] / s for c in sel}
        return w

    if mode == "blend":
        dev = {c: max(close_i[cols.index(c)] / ma_i[cols.index(c)] - 1, 0.0) for c in sel}
        total = sum(dev.values())
        dev_w = ({c: dev[c] / total for c in sel} if total > 0
                 else {c: equal for c in sel})
        return {c: (1 - alpha) * equal + alpha * dev_w[c] for c in sel}

    if mode == "softmax_tau":
        dev = np.array([close_i[cols.index(c)] / ma_i[cols.index(c)] - 1 for c in sel])
        z = dev / tau
        z = z - z.max()  # 数值稳定
        e = np.exp(z)
        w = e / e.sum()
        return {c: float(w[k]) for k, c in enumerate(sel)}

    return {c: equal for c in sel}


def run(panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2,
        top_n=5, mode="equal", cap=0.4, alpha=0.5, tau=0.05):
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values
    ma = pd.DataFrame(close).rolling(ma_period).mean().values
    start = max(ma_period, lookback + 1)

    held = {}
    rets = []
    conc_series = []

    for i in range(start, n):
        if i % rebalance == 0 or not held:
            above = [cols[j] for j in range(m) if close[i, j] > ma[i, j]]
            if len(above) >= max(1, min_candidates):
                past = close[i - lookback:i]
                mom = {c: past[-1][cols.index(c)] / past[0][cols.index(c)] - 1
                       for c in above}
                ranked = sorted(above, key=lambda c: mom[c], reverse=True)
                sel = ranked[:top_n]
                new_held = _weights(sel, close[i], ma[i], cols, mode, cap, alpha, tau)
            else:
                new_held = {}

            tc = turnover_cost(list(held.keys()), list(new_held.keys())) \
                if new_held != held else 0.0
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

    rets = pd.Series(rets, index=panel.index[start:])
    t, a, d, s = perf(rets)
    vol = rets.std() * np.sqrt(250)
    return dict(ret=t, ann=a, dd=d, sharpe=s, vol=vol,
                calmar=t / abs(d) if d < 0 else 0,
                conc=np.mean(conc_series), maxconc=np.max(conc_series))


def main():
    print("拉取 ETF 数据...")
    panel = build_panel(ETF_POOL)
    print(f"面板：{panel.shape[0]} 日 × {panel.shape[1]} 只，"
          f"{panel.index[0]} ~ {panel.index[-1]}\n")

    base = dict(ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=5)

    def show(name, r):
        print(f"{name:22s}{r['ret']*100:>8.1f}%{r['sharpe']:>7.2f}{r['dd']*100:>7.1f}%"
              f"{r['vol']*100:>7.1f}%{r['calmar']:>7.1f}{r['maxconc']*100:>9.1f}%")

    print("=" * 82)
    print("  温和倾斜验证（MA20/调仓5/门槛2/Top5，含A股成本）")
    print("=" * 82)
    print(f"{'方案':22s}{'累计':>8s}{'夏普':>7s}{'回撤':>7s}{'日波动':>7s}{'Calmar':>8s}{'最大集中':>9s}")
    print("-" * 82)

    # 参照系
    show("等权Top5(基准)", run(panel, mode="equal", **base))
    show("趋势强度(原始爆表)", run(panel, mode="trend_strength", **base))

    print()

    # 方案1：封顶倾斜
    print("  方案1：趋势强度加权 + 单券权重封顶 cap")
    for cap in [0.3, 0.4, 0.5, 0.6]:
        show(f"    cap={cap}", run(panel, mode="capped_dev", cap=cap, **base))

    print()
    # 方案2：等权与趋势强度混合
    print("  方案2：等权与趋势强度线性混合  w=(1-α)·equal+α·dev")
    for alpha in [0.3, 0.5, 0.7]:
        show(f"    α={alpha}", run(panel, mode="blend", alpha=alpha, **base))

    print()
    # 方案3：softmax 平滑
    print("  方案3：softmax(偏离度/温度) 平滑")
    for tau in [0.02, 0.05, 0.10]:
        show(f"    τ={tau}", run(panel, mode="softmax_tau", tau=tau, **base))

    print()
    print("  说明：最大集中度=单券最大权重。目标：")
    print("    既要显著跑赢等权（保留alpha），又要把单券权重压到 <=40%（不赌单标的）。")
    print("  本分析仅供研究参考，不构成投资建议。")
    print("=" * 82)


if __name__ == "__main__":
    main()
