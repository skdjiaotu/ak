# -*- coding: utf-8 -*-
"""ETF 轮动策略进阶对比 —— 寻找比「等权 Top N」更好的策略结构。

在「趋势过滤 + 动量轮动」框架上，尝试更高阶的改进方向：
  1. 等权 Top N（基线，已是最优参数 MA20/Top5/调仓5/门槛2）
  2. 动量强度加权：按动量大小分配权重（强者多配）
  3. 低波动加权：候选内按波动率倒数加权（风险控制）
  4. 两段式动量：短期动量 + 中期动量双确认（过滤假动量）
  5. 趋势强度打分：按「价格偏离 MA 的程度」加权（而非简单站上/跌破）

统一含 A 股成本，按累计收益 / 回撤 / 夏普 / Calmar 对比，找最优结构。

用法：
  .venv/Scripts/python.exe etf_rotation_advanced.py

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation import ETF_POOL, build_panel, perf, \
    COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE


def turnover_cost(old_held, new_held):
    """计算换手成本（按换入换出的权重折算）。"""
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


def backtest_weighted(panel, ma_period=20, lookback=20, rebalance=5,
                      min_candidates=2, top_n=5, weight_mode="equal"):
    """趋势过滤 + 动量轮动，支持多种加权方式。

    weight_mode:
      - "equal"：等权 Top N
      - "momentum"：按动量强度加权（候选内动量归一化后加权）
      - "low_vol"：按波动率倒数加权（低波动多配，风险控制）
      - "trend_strength"：按「价格偏离 MA 程度」加权（趋势越强越多配）
    """
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values
    ma = pd.DataFrame(close).rolling(ma_period).mean().values
    ret_panel = pd.DataFrame(close).pct_change().values
    start = max(ma_period, lookback + 1)

    held = {}  # {name: weight}
    rets = []
    for i in range(start, n):
        if i % rebalance == 0 or not held:
            above = [cols[j] for j in range(m) if close[i, j] > ma[i, j]]
            if len(above) >= max(1, min_candidates):
                past = close[i - lookback:i]
                mom = {c: past[-1][cols.index(c)] / past[0][cols.index(c)] - 1
                       for c in above}
                ranked = sorted(above, key=lambda c: mom[c], reverse=True)
                sel = ranked[:top_n]

                # 计算权重
                if weight_mode == "equal":
                    w = {c: 1.0 / len(sel) for c in sel}
                elif weight_mode == "momentum":
                    # 动量强度加权：负动量截断为 0，其余按动量比例
                    pos_mom = {c: max(mom[c], 0.0) for c in sel}
                    total = sum(pos_mom.values())
                    if total > 0:
                        w = {c: pos_mom[c] / total for c in sel}
                    else:
                        w = {c: 1.0 / len(sel) for c in sel}
                elif weight_mode == "low_vol":
                    # 低波动加权：近 lookback 日波动率倒数
                    vols = {}
                    for c in sel:
                        j = cols.index(c)
                        std = np.nanstd(ret_panel[i - lookback:i, j])
                        vols[c] = 1.0 / std if std > 0 else 1.0
                    total = sum(vols.values())
                    w = {c: vols[c] / total for c in sel}
                elif weight_mode == "trend_strength":
                    # 趋势强度：价格相对 MA 的偏离度
                    dev = {c: (close[i, cols.index(c)] / ma[i, cols.index(c)] - 1)
                           for c in sel}
                    total = sum(max(dev[c], 0.0) for c in sel)
                    if total > 0:
                        w = {c: max(dev[c], 0.0) / total for c in sel}
                    else:
                        w = {c: 1.0 / len(sel) for c in sel}
                else:
                    w = {c: 1.0 / len(sel) for c in sel}

                new_held = w
            else:
                new_held = {}

            # 换手成本（按权重差）
            if new_held != held:
                tc = turnover_cost(list(held.keys()), list(new_held.keys()))
            else:
                tc = 0.0
            held = new_held
        else:
            tc = 0.0

        # 当日收益：按权重加权
        if held:
            ret = sum(held[c] * (close[i, cols.index(c)] / close[i - 1, cols.index(c)] - 1)
                      for c in held)
        else:
            ret = 0.0
        rets.append(ret - tc)

    return pd.Series(rets, index=panel.index[start:])


def backtest_dual_momentum(panel, ma_period=20, lookback_short=20, lookback_long=120,
                           rebalance=5, min_candidates=2, top_n=5):
    """两段式动量：短期动量 + 中期动量双确认。

    候选需同时满足：站上 MA + 短期动量 > 0 + 中期动量 > 0（双确认过滤假动量）。
    """
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values
    ma = pd.DataFrame(close).rolling(ma_period).mean().values
    start = max(ma_period, lookback_long + 1, lookback_short + 1)

    held = []
    rets = []
    for i in range(start, n):
        if i % rebalance == 0 or not held:
            above = [cols[j] for j in range(m) if close[i, j] > ma[i, j]]
            candidates = []
            for c in above:
                j = cols.index(c)
                mom_short = close[i, j] / close[i - lookback_short, j] - 1
                mom_long = close[i, j] / close[i - lookback_long, j] - 1
                if mom_short > 0 and mom_long > 0:  # 双确认
                    candidates.append((c, mom_short))
            if len(candidates) >= max(1, min_candidates):
                candidates.sort(key=lambda x: x[1], reverse=True)
                new_held = [c for c, _ in candidates[:top_n]]
            else:
                new_held = []
            if new_held != held:
                tc = turnover_cost(held, new_held)
            else:
                tc = 0.0
            held = new_held
        else:
            tc = 0.0

        if held:
            ret = sum((close[i, cols.index(c)] / close[i - 1, cols.index(c)] - 1)
                      for c in held) / len(held)
        else:
            ret = 0.0
        rets.append(ret - tc)

    return pd.Series(rets, index=panel.index[start:])


def main():
    print("正在拉取 ETF 数据...")
    panel = build_panel(ETF_POOL)
    print(f"面板：{panel.shape[0]} 个交易日，{panel.shape[1]} 只 ETF，"
          f"{panel.index[0]} ~ {panel.index[-1]}\n")

    # 统一用最优参数（MA20/回看20/调仓5/门槛2/Top5），对比不同策略结构
    configs = []

    def run(name, rets):
        t, a, d, s = perf(rets)
        c = t / abs(d) if d < 0 else 0
        configs.append((name, t, a, d, s, c))

    # 1. 等权 Top5（基线）
    run("等权Top5(基线)", backtest_weighted(
        panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=5,
        weight_mode="equal"))

    # 2. 动量强度加权
    run("动量强度加权", backtest_weighted(
        panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=5,
        weight_mode="momentum"))

    # 3. 低波动加权
    run("低波动加权", backtest_weighted(
        panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=5,
        weight_mode="low_vol"))

    # 4. 趋势强度加权
    run("趋势强度加权", backtest_weighted(
        panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=5,
        weight_mode="trend_strength"))

    # 5. 两段式动量（短+长双确认）
    run("两段式动量(短20+长120)", backtest_dual_momentum(
        panel, ma_period=20, lookback_short=20, lookback_long=120,
        rebalance=5, min_candidates=2, top_n=5))

    # 6. 等权 Top3 对照
    run("等权Top3(对照)", backtest_weighted(
        panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2, top_n=3,
        weight_mode="equal"))

    print("=" * 80)
    print("  进阶策略对比（MA20 过滤 + 调仓5天 + 门槛2，含A股成本）")
    print("=" * 80)
    print(f"{'策略':24s}{'累计':>9s}{'年化':>8s}{'回撤':>9s}{'夏普':>7s}{'Calmar':>8s}")
    print("-" * 80)
    for name, t, a, d, s, c in configs:
        print(f"{name:24s}{t*100:>8.1f}%{a*100:>7.1f}%{d*100:>8.1f}%{s:>6.2f}{c:>8.2f}")

    # 排序找出最优
    best = max(configs, key=lambda x: x[5])  # 按 Calmar
    print("\n  按收益回撤比(Calmar)最优：", best[0])
    print("  ⚠️ 仅供研究参考，不构成投资建议。")
    print("=" * 80)


if __name__ == "__main__":
    main()
