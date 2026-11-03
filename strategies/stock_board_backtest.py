# -*- coding: utf-8 -*-
"""多板块（创业板/深主板/科创板）多因子选股回测。

在 stock_factor_backtest 框架基础上，把股票池从「沪深300前30大盘蓝筹」
扩展到「创业板指+科创50+深证成指」成分，验证因子在中小市值板块是否有效。

关键改进：
  1. 股票池扩大（约150-550只），含大量中小市值，因子区分度更高
  2. 增加「市值因子」——A 股小市值溢价是历史最强的量价异象之一
  3. 支持 top_n 更大（分散更充分）

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import os
import pickle
import time

import numpy as np
import pandas as pd
import akshare as ak

import stock_factor_backtest as sfb
from stock_factor_backtest import (
    fetch_price, fetch_fundamental, compute_price_factors,
    zscore_cross_section, perf, get_board_pool, _code_to_symbol,
)


def build_board_data(indexes, cache_tag, limit_per_index=None):
    """构建多板块股票池 + 价格/财务面板（带缓存）。"""
    price_cache = os.path.join(sfb.CACHE_DIR, f"{cache_tag}_price.csv")
    fund_cache = os.path.join(sfb.CACHE_DIR, f"{cache_tag}_fund.pkl")

    pool = get_board_pool(indexes, limit_per_index)
    codes = list(pool["代码"])
    print(f"多板块股票池: {len(codes)} 只")

    panel = sfb.build_price_panel(codes, price_cache)
    print(f"价格面板: {panel.shape}")

    fund = sfb.build_fundamental_panel(codes, fund_cache)
    print(f"ROE面板: {fund['roe'].shape}")
    return pool, panel, fund


def add_market_cap_factor(panel):
    """市值因子：用「收盘价 × 流通股本」近似，但这里简化用「累计成交额」代理。

    更准确的做法是拉总市值，但为控制复杂度，先不引入。市值因子可后续用
    ak.stock_zh_a_spot_em 的流通市值列补充。
    此处返回 None 表示暂不启用市值因子（框架预留）。
    """
    return None


def main():
    print("=" * 60)
    print("  多板块多因子选股回测（创业板/科创板/深主板）")
    print("=" * 60)

    # 股票池：创业板指100 + 科创50 共150只（先验证，后续可加深证成指扩到550）
    indexes = ["399006", "000688"]
    cache_tag = "board_cyb_kcb"
    print(f"\n[1/3] 构建股票池（创业板指+科创50）...")
    pool, panel, fund = build_board_data(indexes, cache_tag)
    codes = list(pool["代码"])

    print(f"\n[2/3] 板块分布:")
    def board_of(c):
        if c.startswith("68"):
            return "科创板"
        if c.startswith("30"):
            return "创业板"
        return "其他"
    print(pd.Series([board_of(c) for c in codes]).value_counts().to_string())

    print(f"\n[3/3] 运行因子回测对比...")
    price_keys = ["momentum", "reversal", "volatility"]
    fund_keys = ["roe", "gross_margin", "revenue_growth"]
    all_keys = price_keys + fund_keys
    all_signs = [1, 1, -1, 1, 1, 1]

    def show(name, r):
        print(f"{name:26s} 累计={r[0]*100:6.1f}% 年化={r[1]*100:5.1f}% "
              f"回撤={r[2]*100:6.1f}% 夏普={r[3]:.2f}")

    # top_n 放大到 30（池子大了，分散更充分）
    show("纯量价(动量+反转+低波动)",
         sfb.run_factor_backtest(panel, fund, price_keys, [1,1,-1], top_n=30, rebalance=20))
    show("纯财务(ROE+毛利率+增长)",
         sfb.run_factor_backtest(panel, fund, fund_keys, [1,1,1], top_n=30, rebalance=20))
    show("全因子组合",
         sfb.run_factor_backtest(panel, fund, all_keys, all_signs, top_n=30, rebalance=20))
    show("全因子+MA60趋势过滤",
         sfb.run_factor_backtest(panel, fund, all_keys, all_signs, top_n=30, rebalance=20,
                                 ma_filter=True, ma_period=60))

    # 基准：等权持有全池
    ret = panel.pct_change().mean(axis=1).dropna()
    ret = ret[ret.index >= panel.index[60]]
    show("基准(等权持有全池)", perf(ret))

    print("\n" + "=" * 60)
    print("  仅供研究参考，不构成投资建议。")


if __name__ == "__main__":
    main()
