# -*- coding: utf-8 -*-
"""多因子选股策略的样本外验证（时间切割前向检验）。

复用 ETF 轮动研究中 analyze_walkforward 的思路：
  训练段（前段）做参数网格扫描 → 选出最优参数
  验证段（后段）套用训练段参数 → 看是否依然成立

四条判据：
  1. 验证段是否仍跑赢等权基准
  2. 参数是否漂移（训练段最优 vs 全样本最优）
  3. 验证段夏普是否接近"验证段自身最优"（距天花板多远）
  4. 收益是否塌方

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

import stock_factor_backtest as sfb
from stock_factor_backtest import (
    run_factor_backtest, perf, compute_price_factors, zscore_cross_section,
)

PRICE_KEYS = ["momentum", "reversal", "volatility"]
FUND_KEYS = ["roe", "gross_margin", "revenue_growth"]
ALL_KEYS = PRICE_KEYS + FUND_KEYS
ALL_SIGNS = [1, 1, -1, 1, 1, 1]

TRAIN_END = "2023-12-29"   # 训练段截止
TEST_START = "2024-01-01"  # 验证段起始


def split_panel(panel, fund_panels, split_date):
    """按日期切分面板为训练段和验证段。"""
    train_panel = panel[panel.index <= split_date]
    test_panel = panel[panel.index > split_date]
    train_fund = {k: v[v.index <= split_date] for k, v in fund_panels.items()}
    test_fund = {k: v[v.index > split_date] for k, v in fund_panels.items()}
    return train_panel, test_panel, train_fund, test_fund


def bench_return(panel):
    """等权买入持有全池的日收益序列。"""
    ret = panel.pct_change().mean(axis=1).dropna()
    return ret[ret.index >= panel.index[60]]


def main():
    print("=" * 60)
    print("  多因子选股 · 样本外验证")
    print("=" * 60)

    # 数据（复用缓存）
    pool = sfb.get_stock_pool(30)
    codes = list(pool["代码"])
    print(f"\n股票池 {len(codes)} 只")
    price_cache = os.path.join(sfb.CACHE_DIR, "price_panel.csv")
    fund_cache = os.path.join(sfb.CACHE_DIR, "fundamental.pkl")
    panel = sfb.build_price_panel(codes, price_cache)
    fund = sfb.build_fundamental_panel(codes, fund_cache)
    print(f"面板 {panel.shape[0]} 日 × {panel.shape[1]} 只, "
          f"{panel.index[0].date()} ~ {panel.index[-1].date()}")

    train_panel, test_panel, train_fund, test_fund = split_panel(panel, fund, TRAIN_END)
    print(f"\n训练段: {train_panel.index[0].date()} ~ {train_panel.index[-1].date()} "
          f"({train_panel.shape[0]} 日)")
    print(f"验证段: {test_panel.index[0].date()} ~ {test_panel.index[-1].date()} "
          f"({test_panel.shape[0]} 日)")

    # ---- 训练段参数扫描：top_n × rebalance ----
    print("\n[训练段] 参数网格扫描 (top_n × rebalance)...")
    grid = []
    for top_n in [10, 15, 20, 30]:
        for rebalance in [20, 40, 60]:
            total, ann, dd, sharpe = run_factor_backtest(
                train_panel, train_fund, ALL_KEYS, ALL_SIGNS,
                top_n=top_n, rebalance=rebalance)
            grid.append((sharpe, top_n, rebalance, total, dd))
            print(f"  top_n={top_n:2d} 调仓={rebalance:2d}日: "
                  f"夏普={sharpe:.2f} 累计={total*100:.0f}% 回撤={dd*100:.0f}%")

    grid.sort(reverse=True)
    best_sharpe, best_topn, best_reb, _, _ = grid[0]
    print(f"\n  ★ 训练段最优: top_n={best_topn}, 调仓={best_reb}日, 夏普={best_sharpe:.2f}")

    # ---- 验证段：套用训练段最优参数 ----
    print(f"\n[验证段] 套用训练段最优参数 (top_n={best_topn}, 调仓={best_reb}日)...")
    t_total, t_ann, t_dd, t_sharpe = run_factor_backtest(
        test_panel, test_fund, ALL_KEYS, ALL_SIGNS,
        top_n=best_topn, rebalance=best_reb)

    # 验证段基准
    b_ret = bench_return(test_panel)
    b_total, b_ann, b_dd, b_sharpe = perf(b_ret)

    # 验证段"自身最优"（天花板）：在验证段上直接扫参数
    test_grid = []
    for top_n in [10, 15, 20, 30]:
        for rebalance in [20, 40, 60]:
            total, ann, dd, sharpe = run_factor_backtest(
                test_panel, test_fund, ALL_KEYS, ALL_SIGNS,
                top_n=top_n, rebalance=rebalance)
            test_grid.append((sharpe, top_n, rebalance))
    test_grid.sort(reverse=True)
    ceiling_sharpe, _, _ = test_grid[0]

    # ---- 全样本最优（对比参数漂移） ----
    full_grid = []
    for top_n in [10, 15, 20, 30]:
        for rebalance in [20, 40, 60]:
            total, ann, dd, sharpe = run_factor_backtest(
                panel, fund, ALL_KEYS, ALL_SIGNS,
                top_n=top_n, rebalance=rebalance)
            full_grid.append((sharpe, top_n, rebalance))
    full_grid.sort(reverse=True)
    full_best = full_grid[0]

    # ---- 输出结论 ----
    print("\n" + "=" * 60)
    print("  样本外验证结论")
    print("=" * 60)
    print(f"  训练段最优参数      : top_n={best_topn}, 调仓={best_reb}日")
    print(f"  全样本最优参数      : top_n={full_best[1]}, 调仓={full_best[2]}日")
    print(f"  参数是否漂移        : {'是' if (best_topn, best_reb) != (full_best[1], full_best[2]) else '否'}")
    print(f"\n  验证段·策略夏普      : {t_sharpe:.2f} (累计 {t_total*100:.0f}%, 回撤 {t_dd*100:.0f}%)")
    print(f"  验证段·等权基准夏普  : {b_sharpe:.2f} (累计 {b_total*100:.0f}%, 回撤 {b_dd*100:.0f}%)")
    print(f"  验证段·理论天花板夏普: {ceiling_sharpe:.2f}")
    print(f"  训练参数达天花板比例 : {t_sharpe/ceiling_sharpe*100:.0f}%")
    print(f"\n  判据1 跑赢基准       : {'✓' if t_sharpe > b_sharpe else '✗'}")
    print(f"  判据3 接近天花板     : {'✓' if t_sharpe/ceiling_sharpe > 0.85 else '✗'}")
    print(f"\n  仅供研究参考，不构成投资建议。")


if __name__ == "__main__":
    main()
