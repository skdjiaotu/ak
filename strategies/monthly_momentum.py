# -*- coding: utf-8 -*-
"""
月度动量/反转选股回测（低频、无前视偏差）

核心思想（低频 alpha 的正确方向）：
  每月末用「截至月末」的过去 N 月涨幅给股票排序，
  下月第一个交易日按排序建仓持有，吃下月真实收益。

无前视偏差关键（从第一行就做对）：
  1. 信号只用「月末及之前」的价格数据（不碰下月当日）
  2. 月末确定选股 → 下月首个交易日建仓 → 收益从建仓日算到下一次调仓
  3. 绝不出现"用当日收盘价决定当日持仓"的穿越

验证内容：
  A. 动量 vs 反转：买过去N月涨幅高的（动量）还是跌幅深的（反转）在A股创业板/科创板有效
  B. 不同回看窗口 N=3/6/12
  C. 不同持有数量 Top K
  D. 全部 vs 等权基准

数据：复用 board_cyb_kcb_price.csv（创业板指100 + 科创50，共150只）
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from stock_factor_backtest import perf, COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE

PRICE_CACHE = "stock/cache/board_cyb_kcb_price.csv"


def load_panel():
    return pd.read_csv(PRICE_CACHE, index_col=0, parse_dates=True)


def monthly_momentum_backtest(panel, lookback_months=6, top_n=30, sign=1,
                              rebalance="M"):
    """月度动量/反转回测。

    sign=1 : 动量（买过去涨幅最高的）
    sign=-1: 反转（买过去跌幅最深的）

    无前视口径：
      - 在每个"月末交易日" t 计算信号：过去 lookback_months 的累计涨幅
        (用 t 及之前的数据，即 panel.loc[:t])
      - 信号在 t 日确定，从 t 的下一个交易日开始持有，直到下一个调仓日
    """
    n, m = panel.shape
    codes = list(panel.columns)
    close = panel.values
    idx = panel.index

    # 找到所有"月末交易日"的位置（每月最后一个交易日）
    month_key = pd.Series([(d.year, d.month) for d in idx])
    is_month_end = month_key != month_key.shift(-1)
    month_end_positions = np.where(is_month_end.values)[0]

    # 每个交易日归属"哪个调仓周期"：用上一个月末位置作为信号生效点
    # 简单做法：逐月遍历月末点，从该月末的下一个交易日持有到下一个月末
    rets = []
    ret_idx = []
    held = []

    # 定位每个月末点，构建持仓区间
    for k, pos in enumerate(month_end_positions):
        # 信号：截至 pos 日的过去 lookback_months 累计涨幅
        # 回看窗口起点 = pos - lookback_months*21 个交易日（约每月21交易日）
        lookback_days = lookback_months * 21
        if pos < lookback_days:
            continue  # 数据不足，跳过

        start_pos = pos - lookback_days
        past_start = close[start_pos]
        past_end = close[pos]
        # 累计涨幅（需排除停牌/无数据，用 valid 过滤）
        mom = np.where(past_start > 0, past_end / past_start - 1, np.nan)

        # 选股：按 sign 方向排序取 top_n
        order = np.argsort(-sign * np.nan_to_num(mom, nan=-np.inf))
        # 过滤 NaN（无数据股票）
        valid_mask = ~np.isnan(mom)
        valid_order = [j for j in order if valid_mask[j]][:top_n]
        new_held = [codes[j] for j in valid_order]

        # 持仓区间：pos 的下一个交易日 到 下一个月末位置（或面板末尾）
        next_pos = month_end_positions[k + 1] if k + 1 < len(month_end_positions) else n - 1
        hold_start = pos + 1
        if hold_start > next_pos:
            continue

        # 换手成本（月度，仅当持仓变化）
        tc = 0.0
        if held:
            sell_names = [c for c in held if c not in new_held]
            buy_names = [c for c in new_held if c not in held]
            if sell_names:
                sell_w = len(sell_names) / len(held)
                tc += sell_w * (COMMISSION + STAMP_TAX + TRANSFER_FEE + SLIPPAGE)
            if buy_names:
                buy_w = len(buy_names) / len(new_held)
                tc += buy_w * (COMMISSION + TRANSFER_FEE + SLIPPAGE)

        # 逐日累计收益（等权持有 new_held）
        for i in range(hold_start, next_pos + 1):
            if i <= 0:
                continue
            if new_held:
                r = np.mean([close[i, codes.index(c)] / close[i - 1, codes.index(c)] - 1
                             for c in new_held])
            else:
                r = 0.0
            # 只在持仓首日扣换手成本
            rets.append(r - (tc if i == hold_start else 0.0))
            ret_idx.append(idx[i])

        held = new_held

    return pd.Series(rets, index=ret_idx)


def show(name, rets):
    t, a, d, s = perf(rets)
    print(f"{name:34s} 累计={t*100:7.1f}%  年化={a*100:5.1f}%  "
          f"回撤={d*100:6.1f}%  夏普={s:.2f}")


def main():
    panel = load_panel()
    print(f"面板: {panel.shape}, {panel.index[0].date()} ~ {panel.index[-1].date()}\n")

    # 基准：等权持有全池
    bench = panel.pct_change().mean(axis=1).dropna()
    bench = bench[bench.index >= panel.index[21]]

    print("=" * 90)
    print("  月度动量 vs 反转（创业板+科创板 150只，无前视口径）")
    print("=" * 90)
    show("基准(等权持有全池)", bench)

    print("\n--- 动量（买过去涨幅高的） ---")
    for lb in [3, 6, 12]:
        for top in [20, 30]:
            r = monthly_momentum_backtest(panel, lookback_months=lb, top_n=top, sign=1)
            show(f"动量 回看{lb}月 Top{top}", r)

    print("\n--- 反转（买过去跌幅深的） ---")
    for lb in [3, 6, 12]:
        for top in [20, 30]:
            r = monthly_momentum_backtest(panel, lookback_months=lb, top_n=top, sign=-1)
            show(f"反转 回看{lb}月 Top{top}", r)


if __name__ == "__main__":
    main()
