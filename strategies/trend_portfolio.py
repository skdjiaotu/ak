# -*- coding: utf-8 -*-
"""AKQuant 趋势策略 —— 多标的组合回测入口（含标的筛选）。

对多只宽基指数/个股同时运行趋势策略，输出组合绩效与单标的归因。
支持按「历史波动率」筛选标的，剔除高波动小盘标的、保留大盘稳健标的，
观察筛选对组合绩效的改善。

用法：
  .venv/Scripts/python.exe trend_portfolio.py                          # 默认6个宽基指数
  .venv/Scripts/python.exe trend_portfolio.py --symbols 000300,399006,000905
  .venv/Scripts/python.exe trend_portfolio.py --strategy stop          # 用止损止盈增强版
  .venv/Scripts/python.exe trend_portfolio.py --filter                 # 自动剔除高波动标的
  .venv/Scripts/python.exe trend_portfolio.py --filter --max-vol 0.30  # 自定义波动率阈值

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import argparse
import datetime

import numpy as np
import pandas as pd

from akquant import run_backtest

from trend_strategies import (
    fetch_multi_data,
    DualMACrossStrategy,
    MA60TrendStrategy,
    MA60WithStopStrategy,
    MA60TrailingStopStrategy,
    summarize,
    A_SHARE_BROKER_PROFILE,
)

# 默认组合：六大宽基指数 ETF + 海外/红利 ETF（全部可买卖，替代指数代码）
DEFAULT_SYMBOLS = [
    "sh510300",  # 沪深300ETF
    "sz159915",  # 创业板ETF
    "sh510500",  # 中证500ETF
    "sh510050",  # 上证50ETF
    "sh588000",  # 科创50ETF
    "sz159903",  # 深证成指ETF
    "sh513500",  # 标普500ETF
    "sh512890",  # 红利低波ETF
    "sh513520",  # 日经ETF
    "sh513030",  # 德国ETF
]

STRATEGIES = {
    "dual": ("双均线交叉 MA30/60", DualMACrossStrategy),
    "sma": ("单均线趋势 MA60", MA60TrendStrategy),
    "stop": ("单均线 MA60 + 止损止盈", MA60WithStopStrategy),
    "trailing": ("单均线 MA60 + 追踪止损", MA60TrailingStopStrategy),
}


def calc_volatility(df: pd.DataFrame) -> dict:
    """计算每个标的的年化波动率（用日收益率的滚动标准差 × sqrt(252)）。"""
    vols = {}
    for sym, sub in df.groupby("symbol"):
        sub = sub.sort_values("date")
        rets = sub["close"].pct_change().dropna()
        # 年化波动率
        vol = rets.std() * np.sqrt(252)
        vols[sym] = vol
    return vols


def filter_symbols(df: pd.DataFrame, resolved: list, max_vol: float) -> tuple:
    """按波动率筛选标的，剔除高波动标的。返回 (筛选后 df, 筛选后 resolved, 波动率表)。"""
    vols = calc_volatility(df)
    kept = [s for s in resolved if vols.get(s, 0) <= max_vol]
    removed = [s for s in resolved if vols.get(s, 0) > max_vol]
    df_filtered = df[df["symbol"].isin(kept)].reset_index(drop=True)
    return df_filtered, kept, vols, removed


def run_backtest_portfolio(cls, df, resolved, cash):
    return run_backtest(
        strategy=cls,
        data=df,
        symbols=resolved,
        initial_cash=cash,
        broker_profile=A_SHARE_BROKER_PROFILE,
    )


def buy_hold_benchmark(df: pd.DataFrame) -> tuple:
    """组合等权买入持有基准。"""
    closes = df.pivot_table(index="date", columns="symbol", values="close").ffill()
    norm = closes / closes.iloc[0]
    equal_weight = norm.mean(axis=1)
    bh_ret = (equal_weight.iloc[-1] - 1) * 100
    peak = equal_weight.cummax()
    dd = (equal_weight - peak) / peak
    return bh_ret, dd.min() * 100


def print_attribution(result):
    """打印单标的归因。"""
    print(f"\n{'='*60}")
    print(f"  【单标的归因（各标的交易次数与收益贡献）】")
    print(f"{'='*60}")
    if hasattr(result, "trades_df") and result.trades_df is not None and len(result.trades_df) > 0:
        trades = result.trades_df
        if "symbol" in trades.columns and "net_pnl" in trades.columns:
            grp = trades.groupby("symbol").agg(
                trade_count=("net_pnl", "count"),
                total_pnl=("net_pnl", "sum"),
            ).reset_index().sort_values("total_pnl", ascending=False)
            for _, row in grp.iterrows():
                flag = "✅" if row["total_pnl"] > 0 else "❌"
                print(f"  {flag} {row['symbol']:<12} 交易 {int(row['trade_count']):>3} 次  "
                      f"累计盈亏 {row['total_pnl']:>12.0f} 元")
        else:
            print("  trades_df 字段与预期不符，跳过归因。")
    else:
        print("  无交易记录或字段缺失，跳过归因。")


def main():
    parser = argparse.ArgumentParser(description="AKQuant 趋势策略多标的组合回测（含标的筛选）")
    parser.add_argument("--symbols", default=None, help="逗号分隔的标的列表")
    parser.add_argument("--strategy", default="stop", choices=list(STRATEGIES.keys()))
    parser.add_argument("--start", default="20180101", help="起始日期")
    parser.add_argument("--end", default=None, help="结束日期")
    parser.add_argument("--cash", type=float, default=1_000_000.0, help="初始资金")
    parser.add_argument("--filter", action="store_true", help="按波动率剔除高波动标的")
    parser.add_argument("--max-vol", type=float, default=0.30, help="波动率阈值（年化，默认0.30）")
    args = parser.parse_args()

    if args.end is None:
        args.end = datetime.date.today().strftime("%Y%m%d")

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = DEFAULT_SYMBOLS

    print(f"拉取 {len(symbols)} 个标的日线数据 ({args.start} ~ {args.end}) ...")
    df, resolved = fetch_multi_data(symbols, args.start, args.end)
    print(f"  总数据条数: {len(df)}")

    # 波动率一览
    vols = calc_volatility(df)
    print(f"\n  各标的年化波动率：")
    for s in resolved:
        print(f"    {s:<12} {vols.get(s, 0)*100:>5.1f}%")

    name, cls = STRATEGIES[args.strategy]

    # 筛选前
    print(f"\n>>> 运行 {name}（组合回测，筛选前 {len(resolved)} 标的）...")
    result_all = run_backtest_portfolio(cls, df, resolved, args.cash)
    summarize(f"{name} —— 全组合（{len(resolved)} 标的）", result_all)
    bh_ret, bh_mdd = buy_hold_benchmark(df)
    print(f"  [基准] 等权买入持有: {bh_ret:.2f}% / 回撤 {bh_mdd:.2f}%")
    print_attribution(result_all)

    # 筛选后
    if args.filter:
        df_f, kept, vols, removed = filter_symbols(df, resolved, args.max_vol)
        print(f"\n{'='*60}")
        print(f"  【波动率筛选（阈值 {args.max_vol*100:.0f}%）】")
        print(f"  剔除高波动标的: {', '.join(removed) if removed else '无'}")
        print(f"  保留标的: {', '.join(kept)}")
        print(f"{'='*60}")

        if len(kept) >= 2:
            print(f"\n>>> 运行 {name}（组合回测，筛选后 {len(kept)} 标的）...")
            result_f = run_backtest_portfolio(cls, df_f, kept, args.cash)
            summarize(f"{name} —— 筛选后组合（{len(kept)} 标的）", result_f)
            bh_ret_f, bh_mdd_f = buy_hold_benchmark(df_f)
            print(f"  [基准] 等权买入持有: {bh_ret_f:.2f}% / 回撤 {bh_mdd_f:.2f}%")
            print_attribution(result_f)
        else:
            print("  筛选后标的不足 2 个，跳过筛选后回测。")

    print(f"\n{'='*60}")
    print("  【结论提示】")
    print("  - 趋势策略更适合波动适中的大盘/中盘标的。")
    print("  - 高波动小盘标的（如中证500/科创50）在趋势策略下易巨亏，建议剔除。")
    print("  - 对比筛选前后：若回撤显著下降、收益保持，说明筛选有效。")
    print("  - 本回测仅供研究参考，不构成投资建议。")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
