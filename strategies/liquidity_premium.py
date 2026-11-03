# -*- coding: utf-8 -*-
"""
流动性/小市值溢价验证（创业板+科创板150只，无前视口径）

用「成交额 amount」作为流动性/市值的代理，做分组回测：
  - 组1 = 成交额最小的（冷门小票）
  - 组5 = 成交额最大的（热门大盘）
看是否单调（组1 系统性跑赢组5）= 流动性溢价是否成立。

无前视：月末用"截至月末"数据分组，下月建仓吃真实收益。
数据：board_cyb_kcb_price.csv（已缓存）+ cyb_kcb_amount.pkl（刚缓存）。
"""
from __future__ import annotations

import pickle
import numpy as np
import pandas as pd

from stock_factor_backtest import perf

PRICE_CACHE = "stock/cache/board_cyb_kcb_price.csv"
AMOUNT_CACHE = "stock/cache/cyb_kcb_amount.pkl"


def load():
    panel = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True)
    with open(AMOUNT_CACHE, "rb") as f:
        amounts = pickle.load(f)
    return panel, amounts


def group_backtest(panel, amounts, n_groups=5):
    """按成交额分组，月度调仓，无前视。"""
    codes = list(panel.columns)

    # 只保留有成交额、且在面板中的票
    valid = [(c, amounts.get(c, np.nan)) for c in codes]
    valid = [(c, a) for c, a in valid if pd.notna(a) and a > 0]
    valid.sort(key=lambda x: x[1])  # 成交额从小到大
    k = len(valid)
    per = k // n_groups
    groups = {}
    for g in range(n_groups):
        s = g * per
        e = (g + 1) * per if g < n_groups - 1 else k
        groups[g] = [c for c, _ in valid[s:e]]

    close = panel.values
    idx = panel.index
    n, m = panel.shape
    code_pos = {c: i for i, c in enumerate(codes)}

    month_key = pd.Series([(d.year, d.month) for d in idx])
    is_month_end = month_key != month_key.shift(-1)
    month_end_positions = np.where(is_month_end.values)[0]

    result = {g: [] for g in range(n_groups)}
    result_idx = []
    for kk, pos in enumerate(month_end_positions):
        next_pos = month_end_positions[kk + 1] if kk + 1 < len(month_end_positions) else n - 1
        hold_start = pos + 1
        if hold_start > next_pos:
            continue
        for i in range(hold_start, next_pos + 1):
            if i <= 0:
                continue
            result_idx.append(idx[i])
            for g in range(n_groups):
                grp = groups[g]
                r = np.mean([close[i, code_pos[c]] / close[i - 1, code_pos[c]] - 1
                             for c in grp])
                result[g].append(r)

    return {g: pd.Series(v, index=result_idx) for g, v in result.items()}, groups, amounts


def show(name, rets):
    t, a, d, s = perf(rets)
    print(f"{name:30s} 累计={t*100:7.1f}%  年化={a*100:5.1f}%  "
          f"回撤={d*100:6.1f}%  夏普={s:.2f}")


def main():
    panel, amounts = load()
    print(f"面板: {panel.shape}, {panel.index[0].date()} ~ {panel.index[-1].date()}")
    print(f"有成交额的票: {sum(1 for c in panel.columns if amounts.get(c) and amounts.get(c)>0)} 只\n")

    grp_rets, groups, amounts = group_backtest(panel, amounts, n_groups=5)

    print("=" * 84)
    print("  流动性/小市值溢价分组回测（创业板+科创板150只，无前视，月度调仓）")
    print("=" * 84)
    labels = ["组1(成交额最小/冷门)", "组2", "组3(中)", "组4", "组5(成交额最大/热门)"]
    for g in range(5):
        show(labels[g], grp_rets[g])

    bench = panel.pct_change().mean(axis=1).dropna()
    show("基准(全池等权)", bench)

    long_short = grp_rets[0] - grp_rets[4]
    show("多空(组1 - 组5)", long_short)

    print()
    print("  各组成交额区间(亿):")
    for g in range(5):
        grp_amt = [amounts[c] for c in groups[g]]
        print(f"    组{g+1}: {min(grp_amt)/1e8:.2f} ~ {max(grp_amt)/1e8:.2f} 亿 ({len(grp_amt)}只)")


if __name__ == "__main__":
    main()
