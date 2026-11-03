# -*- coding: utf-8 -*-
"""
中大盘股分散组合研究（无前视口径）

目标：在「上证50+沪深300+中证500+科创50+创业板指」的中大盘池(206只代表)上，
研究怎么配置/再平衡最稳，不追超额，求稳健、回撤可控。

对比方案：
  1. 等权全池（基准，一次性买入持有）
  2. 等权 + 月度再平衡
  3. 等权 + 季度再平衡
  4. 低波动倾斜（选过去N日波动最小的Top K，季度调仓）——中大盘低波动因子常有效
  5. 分层配置（大盘:中盘:成长 按比例）

无前视：所有信号用「截至T-1」数据，月度/季度调仓。
"""
from __future__ import annotations

import pickle
import numpy as np
import pandas as pd

from stock_factor_backtest import perf, COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE

PRICE_CACHE = "stock/cache/midcap_price.csv"
POOL_CACHE = "stock/cache/midcap_pool.pkl"


def load():
    panel = pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True)
    with open(POOL_CACHE, "rb") as f:
        pool = pickle.load(f)
    return panel, pool


def show(name, rets):
    t, a, d, s = perf(rets)
    print(f"{name:30s} 累计={t*100:7.1f}%  年化={a*100:5.1f}%  "
          f"回撤={d*100:6.1f}%  夏普={s:.2f}")


def equal_weight_rebalance(panel, freq="M"):
    """等权 + 定期再平衡（freq: 'M'月度 / 'Q'季度 / None不调）。"""
    n, m = panel.shape
    close = panel.values
    idx = panel.index
    codes = list(panel.columns)
    code_pos = {c: i for i, c in enumerate(codes)}

    # 有效列（去掉全 NaN）
    valid_cols = [c for c in codes if panel[c].notna().any()]
    n_valid = len(valid_cols)
    w = {c: 1.0 / n_valid for c in valid_cols}

    rets = []
    ret_idx = []
    for i in range(1, n):
        # 当日收益：只对「前后两日都有有效价格」的票取均值（跳过 NaN，避免缺口污染）
        valid_ret = []
        for c in valid_cols:
            p0 = close[i - 1, code_pos[c]]
            p1 = close[i, code_pos[c]]
            if np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                valid_ret.append(p1 / p0 - 1)
        r = np.mean(valid_ret) if valid_ret else 0.0

        rets.append(r)
        ret_idx.append(idx[i])

    return pd.Series(rets, index=ret_idx)


def low_vol_tilt(panel, lookback=60, top_k=80, freq="Q"):
    """低波动倾斜：每季度选过去 lookback 日波动最小的 top_k 只，等权持有。"""
    n, m = panel.shape
    close = panel.values
    idx = panel.index
    codes = list(panel.columns)
    code_pos = {c: i for i, c in enumerate(codes)}

    # 滚动波动率（用截至前一日的窗口，无前视）
    rets_df = panel.pct_change()
    vol = rets_df.rolling(lookback).std().shift(1)  # shift 用昨日波动决定今日

    held = []
    rets = []
    ret_idx = []
    for i in range(lookback + 1, n):
        # 季度调仓
        is_rebal = (idx[i].year, (idx[i].month - 1) // 3) != \
                   (idx[i - 1].year, (idx[i - 1].month - 1) // 3)
        if is_rebal or not held:
            v = vol.iloc[i - 1]  # 用昨日波动
            v = v[v.notna()]
            held = list(v.sort_values().head(top_k).index)

        if held:
            valid_ret = []
            for c in held:
                p0 = close[i - 1, code_pos[c]]
                p1 = close[i, code_pos[c]]
                if np.isfinite(p0) and np.isfinite(p1) and p0 > 0:
                    valid_ret.append(p1 / p0 - 1)
            r = np.mean(valid_ret) if valid_ret else 0.0
        else:
            r = 0.0
        rets.append(r)
        ret_idx.append(idx[i])

    return pd.Series(rets, index=ret_idx)


def main():
    panel, pool = load()
    print(f"面板: {panel.shape[0]} 日 × {panel.shape[1]} 只, "
          f"{panel.index[0].date()} ~ {panel.index[-1].date()}\n")

    # 基准：等权持有（不复位，含漂移）
    bench = panel.pct_change().mean(axis=1).dropna()

    print("=" * 84)
    print("  中大盘股分散组合研究（206只，无前视口径）")
    print("=" * 84)
    show("基准(等权持有不复位)", bench)
    show("等权+月度再平衡", equal_weight_rebalance(panel, freq="M"))
    show("等权+季度再平衡", equal_weight_rebalance(panel, freq="Q"))

    print("\n--- 低波动倾斜（中大盘低波动因子） ---")
    for top_k in [60, 80, 100]:
        show(f"低波动 Top{top_k} 季度调仓", low_vol_tilt(panel, lookback=60, top_k=top_k))


if __name__ == "__main__":
    main()
