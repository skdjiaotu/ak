"""市场情绪多因子择时策略回测。

在沪深300指数上回测「情绪热度 → 仓位」择时策略，对比买入持有。

关键设计（避免前视偏差）：
  - 信号用「当月月末」的情绪数据，下月执行（月度调仓）。
  - 仓位由上月情绪热度决定，持有整月后按本月月末情绪再调整。
  - 回测收益 = 仓位 × 指数月收益，无杠杆（仓位 ∈ [0,1]）。

对比基准：
  1. 买入持有（满仓）
  2. 情绪择时（三段式仓位）
  3. 反向基准：把情绪信号反过来用（验证信号方向是否真有意义）
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def fetch_benchmark_index(start: str = "20050101") -> pd.DataFrame:
    """沪深300指数月线（腾讯源日线 → 月末收盘），返回 date/close。"""
    from sentiment.fetcher import fetch_index_daily

    df = fetch_index_daily()
    df["ym"] = df["date"].dt.to_period("M")
    monthly = df.groupby("ym").agg(close=("close", "last"), date=("date", "last"))
    monthly = monthly.reset_index(drop=True)
    monthly["date"] = pd.to_datetime(monthly["date"])
    return monthly[["date", "close"]].sort_values("date")


def backtest(panel: pd.DataFrame, position: pd.Series,
             benchmark: pd.DataFrame) -> pd.DataFrame:
    """执行回测，返回月度结果 DataFrame（含策略/基准净值）。

    position：以「月末」为索引的目标仓位，在下月生效。
    策略月收益 = position(上月) × 指数当月收益。
    """
    idx = benchmark.set_index("date")["close"]
    idx_ret = idx.pct_change().shift(-1)  # 当月月末→下月月末收益（下月收益）

    # 对齐：仓位在 t 月末决定，作用于 t+1 月收益
    pos_shifted = position.reindex(idx.index).ffill().shift(1)
    strat = pos_shifted * idx_ret

    df = pd.DataFrame({
        "bench_ret": idx_ret,
        "strat_ret": strat,
        "position": pos_shifted,
    }).dropna()
    return df


def perf(rets: pd.Series) -> Dict:
    """绩效指标：累计、年化、最大回撤、夏普。"""
    equity = (1 + rets).cumprod()
    total = equity.iloc[-1] - 1
    n = len(rets)
    ann = (1 + total) ** (12 / n) - 1 if n > 0 else 0.0
    dd = (equity / equity.cummax() - 1).min()
    vol = rets.std() * np.sqrt(12)
    sharpe = rets.mean() / rets.std() * np.sqrt(12) if rets.std() > 0 else 0.0
    return {
        "total": total, "ann": ann, "max_dd": dd,
        "vol": vol, "sharpe": sharpe, "n": n,
    }


def backtest_compare(panel: pd.DataFrame, position: pd.Series,
                     benchmark: pd.DataFrame) -> Dict:
    """回测 + 三组对比（买入持有 / 情绪择时 / 反向信号）。"""
    res = backtest(panel, position, benchmark)

    bench = perf(res["bench_ret"])
    strat = perf(res["strat_ret"])

    # 反向基准：仓位取反（1-position），验证信号方向
    inv_pos = 1.0 - position
    inv = backtest(panel, inv_pos, benchmark)
    inv_p = perf(inv["strat_ret"])

    # 平均仓位（衡量择时激进程度）
    avg_pos = position.mean()

    return {
        "res": res,
        "bench": bench,
        "strat": strat,
        "inverse": inv_p,
        "avg_pos": avg_pos,
    }


def sensitivity(panel: pd.DataFrame, benchmark: pd.DataFrame,
                overheat_range=(0.5, 1.0, 1.5),
                ice_range=(-0.5, -1.0, -1.5),
                windows=(12, 24, 36)) -> pd.DataFrame:
    """参数敏感性：不同过热/冰点阈值、滚动窗口下的夏普/回撤。"""
    from sentiment.engine import (build_factor_scores, composite_heat,
                                  heat_to_position)

    rows = []
    for w in windows:
        scores = build_factor_scores(panel, window=w)
        heat = composite_heat(scores)
        for oh in overheat_range:
            for ic in ice_range:
                pos = heat_to_position(heat, overheat=oh, ice=ic)
                res = backtest(panel, pos, benchmark)
                p = perf(res["strat_ret"])
                rows.append({
                    "window": w, "overheat": oh, "ice": ic,
                    "ann": p["ann"], "sharpe": p["sharpe"],
                    "max_dd": p["max_dd"], "avg_pos": pos.mean(),
                })
    return pd.DataFrame(rows)
