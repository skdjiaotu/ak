# -*- coding: utf-8 -*-
"""
回撤控制验证：给「创业板+科创板纯量价因子策略」叠加风控，看能否压低 -31% 回撤。

核心思路（复用 ETF 轮动验证过的成功路径）：
1. 大盘择时：用指数/全池等权作为"总开关"，跌破均线 → 空仓或降仓（回撤主来源）
2. 波动率目标：持仓日波动率超阈值 → 整体降仓缩放
3. 个股止损：单票跌破 MA → 剔除

基于 stock_factor_backtest 的缓存数据，不污染主引擎。
"""
import os
import pickle
import numpy as np
import pandas as pd
from stock_factor_backtest import (perf, compute_price_factors, zscore_cross_section,
                                   COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE)


def load_data():
    panel = pd.read_csv("../stock/cache/board_cyb_kcb_price.csv",
                        index_col=0, parse_dates=True)
    with open("../stock/cache/board_cyb_kcb_fund.pkl", "rb") as f:
        fund = pickle.load(f)
    return panel, fund


def compute_scores(panel, factor_keys=("momentum", "reversal", "volatility"),
                   factor_signs=(1, 1, -1)):
    """计算每日打分矩阵（横截面 z-score 合成）。"""
    price_factors = compute_price_factors(panel)
    score = pd.DataFrame(0.0, index=panel.index, columns=panel.columns)
    for key, sign in zip(factor_keys, factor_signs):
        raw = price_factors[key].reindex(index=panel.index, columns=panel.columns)
        z = zscore_cross_section(raw)
        score = score + sign * z.fillna(0.0)
    return score


def backtest(panel, score, top_n=40, rebalance=20,
             market_ma=None, vol_target=None, stop_ma=None):
    """带风控的组合回测。

    market_ma : 大盘择时均线周期（None=不做）。用全池等权指数 vs MA 判断。
    vol_target: 目标年化波动率（None=不做）。持仓实际波动超目标则按比例降仓。
    stop_ma   : 个股止损均线（None=不做）。单票跌破该 MA 即剔除/空仓该票。
    """
    n, m = panel.shape
    codes = list(panel.columns)
    close = panel.values

    # 大盘指数 = 全池等权（用前一日及更早数据算均线，避免前视）
    pool_idx = pd.Series(np.nanmean(close, axis=1), index=panel.index)
    # 关键修正：均线用 shift(1)，即"截至昨日收盘"的信号决定今日持仓
    pool_ma = pool_idx.rolling(market_ma).mean().shift(1) if market_ma else None

    # 个股止损均线（同样 shift(1)，用昨日数据决定今日是否持有）
    stop_line = pd.DataFrame(close).rolling(stop_ma).mean().shift(1).values if stop_ma else None

    # 波动率目标：用持仓组合近期日波动估算
    vol_win = 20

    start = 60
    rets = []
    held = []
    for i in range(start, n):
        # ---- 大盘择时：昨日收盘跌破均线 → 今日整体空仓 ----
        if market_ma and i >= market_ma:
            if pd.notna(pool_ma.iloc[i]) and pool_idx.iloc[i - 1] < pool_ma.iloc[i]:
                held = []
                rets.append(0.0)
                continue

        # ---- 调仓判断（用昨日打分决定今日持仓） ----
        if i % rebalance == 0 or not held:
            day_score = score.iloc[i - 1]  # 关键修正：用昨日截面打分
            valid = day_score[day_score.notna()]
            if len(valid) >= top_n:
                new_held = list(valid.sort_values(ascending=False).head(top_n).index)
            elif len(valid) >= 1:
                new_held = list(valid.sort_values(ascending=False).index)
            else:
                new_held = []

            tc = 0.0
            if new_held != held:
                sell_names = [c for c in held if c not in new_held]
                if sell_names:
                    sell_w = len(sell_names) / len(held) if held else 0.0
                    tc += sell_w * (COMMISSION + STAMP_TAX + TRANSFER_FEE + SLIPPAGE)
                buy_names = [c for c in new_held if c not in held]
                if buy_names:
                    buy_w = len(buy_names) / len(new_held) if new_held else 0.0
                    tc += buy_w * (COMMISSION + TRANSFER_FEE + SLIPPAGE)
            held = new_held
        else:
            tc = 0.0
            # ---- 个股止损：昨日收盘跌破止损线 → 今日剔除 ----
            if stop_ma and held:
                held = [c for c in held
                        if close[i - 1, codes.index(c)] > stop_line[i, codes.index(c)]]

        if not held:
            rets.append(0.0)
            continue

        # ---- 当日收益（等权） ----
        r = np.mean([close[i, codes.index(c)] / close[i - 1, codes.index(c)] - 1
                     for c in held])

        # ---- 波动率目标缩放（用已实现的历史波动，无前视） ----
        if vol_target is not None:
            rets_hist = rets[-vol_win:]
            if len(rets_hist) >= 5:
                realized = np.std(rets_hist) * np.sqrt(250)
                if realized > 0:
                    scale = min(1.0, vol_target / realized)
                    r = r * scale

        rets.append(r - tc)

    rets = pd.Series(rets, index=panel.index[start:])
    return rets


def show(name, rets):
    t, a, d, s = perf(rets)
    print(f"  {name:36s} 累计={t*100:7.1f}%  年化={a*100:5.1f}%  "
          f"回撤={d*100:6.1f}%  夏普={s:.2f}")


def main():
    panel, fund = load_data()
    print(f"面板: {panel.shape}, 日期 {panel.index[0].date()} ~ {panel.index[-1].date()}")
    score = compute_scores(panel)

    # 基准（等权持有全池）
    bench = panel.pct_change().mean(axis=1).dropna()
    bench = bench[bench.index >= panel.index[60]]

    print("\n=== 无风控基线 ===")
    base = backtest(panel, score, top_n=40, rebalance=20)
    show("纯量价 Top40 (无风控)", base)
    show("基准(等权全池)", bench)

    print("\n=== 方案A：大盘择时（全池指数 vs MA 空仓） ===")
    for ma in [20, 40, 60]:
        r = backtest(panel, score, top_n=40, rebalance=20, market_ma=ma)
        show(f"择时 MA{ma} 跌破空仓", r)

    print("\n=== 方案B：个股止损（单票跌破 MA 剔除） ===")
    for ma in [10, 20, 30]:
        r = backtest(panel, score, top_n=40, rebalance=20, stop_ma=ma)
        show(f"个股止损 MA{ma}", r)

    print("\n=== 方案C：波动率目标（组合降仓缩放） ===")
    for vt in [0.15, 0.20, 0.25]:
        r = backtest(panel, score, top_n=40, rebalance=20, vol_target=vt)
        show(f"波动率目标 {int(vt*100)}%", r)

    print("\n=== 方案D：组合叠加（择时 + 个股止损 + 波动率目标） ===")
    r = backtest(panel, score, top_n=40, rebalance=20,
                 market_ma=40, stop_ma=20, vol_target=0.20)
    show("择时MA40 + 止损MA20 + 波动率20%", r)
    r = backtest(panel, score, top_n=40, rebalance=20,
                 market_ma=40, stop_ma=20, vol_target=0.18)
    show("择时MA40 + 止损MA20 + 波动率18%", r)
    r = backtest(panel, score, top_n=40, rebalance=20,
                 market_ma=40, stop_ma=20, vol_target=0.15)
    show("择时MA40 + 止损MA20 + 波动率15%", r)


if __name__ == "__main__":
    main()
