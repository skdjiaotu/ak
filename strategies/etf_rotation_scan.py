# -*- coding: utf-8 -*-
"""ETF 轮动策略参数扫描 —— 寻找「高收益 + 低回撤」的最优组合。

在 etf_rotation 的「趋势过滤 + 动量轮动」框架上，系统扫描：
  - 趋势过滤均线周期 ma_period
  - 动量回看期 lookback
  - 调仓周期 rebalance
  - 持仓数量 top_n
  - 空仓门槛 min_candidates（候选不足则空仓躲熊市）

按「收益回撤比(Calmar)」和「夏普」双重排序，找出回撤小、收益高的稳健组合。

用法：
  .venv/Scripts/python.exe etf_rotation_scan.py
  .venv/Scripts/python.exe etf_rotation_scan.py --top 20   # 输出前 20 名

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import argparse
import itertools

import numpy as np
import pandas as pd

from etf_rotation import ETF_POOL, build_panel, backtest_rotation, perf


def calmar(total: float, dd: float) -> float:
    """收益回撤比（Calmar）：累计收益 / |最大回撤|。"""
    if dd >= 0 or dd == 0:
        return float("inf") if total > 0 else 0.0
    return total / abs(dd)


def main():
    parser = argparse.ArgumentParser(description="ETF 轮动策略参数扫描")
    parser.add_argument("--top", type=int, default=20, help="输出前 N 名")
    args = parser.parse_args()

    print("正在拉取 ETF 数据...")
    panel = build_panel(ETF_POOL)
    print(f"面板：{panel.shape[0]} 个交易日，{panel.shape[1]} 只 ETF，"
          f"{panel.index[0]} ~ {panel.index[-1]}\n")

    # 扫描网格
    grid = {
        "ma_period": [20, 30, 40, 50, 60, 90],
        "lookback": [10, 20, 40, 60],
        "rebalance": [5, 10, 20, 30],
        "top_n": [1, 2, 3, 5],
        "min_candidates": [1, 2, 3],
    }
    combos = list(itertools.product(
        grid["ma_period"], grid["lookback"], grid["rebalance"],
        grid["top_n"], grid["min_candidates"]))
    total = len(combos)
    print(f"共 {total} 组参数组合，开始扫描...\n")

    rows = []
    for idx, (ma, lb, rb, topn, minc) in enumerate(combos, 1):
        rets = backtest_rotation(panel, ma_period=ma, lookback=lb, rebalance=rb,
                                 min_candidates=minc, top_n=topn)
        t, a, d, s = perf(rets)
        c = calmar(t, d)
        rows.append({
            "ma_period": ma, "lookback": lb, "rebalance": rb,
            "top_n": topn, "min_candidates": minc,
            "total": t, "ann": a, "mdd": d, "sharpe": s, "calmar": c,
        })
        if idx % 200 == 0:
            print(f"  进度 {idx}/{total} ...")

    df = pd.DataFrame(rows)

    # 按 Calmar 排序（收益回撤比优先，体现「高收益+低回撤」）
    df_sorted = df.sort_values("calmar", ascending=False).reset_index(drop=True)

    print("=" * 96)
    print("  ETF 轮动参数扫描 TOP{}（按收益回撤比 Calmar 降序）".format(args.top))
    print("=" * 96)
    header = (f"{'排名':>4} {'MA':>4} {'回看':>5} {'调仓':>5} {'持仓':>5} {'门槛':>5} "
              f"{'累计':>9} {'年化':>8} {'回撤':>9} {'夏普':>7} {'Calmar':>8}")
    print(header)
    print("-" * 96)
    for i, row in df_sorted.head(args.top).iterrows():
        print(f"{i+1:>4} {int(row['ma_period']):>4} {int(row['lookback']):>5} "
              f"{int(row['rebalance']):>5} {int(row['top_n']):>5} {int(row['min_candidates']):>5} "
              f"{row['total']*100:>8.1f}% {row['ann']*100:>7.1f}% {row['mdd']*100:>8.1f}% "
              f"{row['sharpe']:>7.2f} {row['calmar']:>8.2f}")

    print("\n" + "=" * 96)
    print("  【同样按夏普排序 TOP10】")
    print("=" * 96)
    df_sharpe = df.sort_values("sharpe", ascending=False).reset_index(drop=True)
    print(header)
    print("-" * 96)
    for i, row in df_sharpe.head(10).iterrows():
        print(f"{i+1:>4} {int(row['ma_period']):>4} {int(row['lookback']):>5} "
              f"{int(row['rebalance']):>5} {int(row['top_n']):>5} {int(row['min_candidates']):>5} "
              f"{row['total']*100:>8.1f}% {row['ann']*100:>7.1f}% {row['mdd']*100:>8.1f}% "
              f"{row['sharpe']:>7.2f} {row['calmar']:>8.2f}")

    print("\n  【关键洞察】")
    print("  - Calmar 高 = 单位回撤换来的收益高（你要的「高收益+低回撤」）。")
    print("  - 观察最优参数是否聚集（稳健）还是分散（过拟合）。")
    print("  - 空仓门槛 min_candidates 是控回撤的关键：门槛越高，普跌市越早空仓。")
    print("  - 本扫描仅供研究参考，不构成投资建议。")
    print("=" * 96)


if __name__ == "__main__":
    main()
