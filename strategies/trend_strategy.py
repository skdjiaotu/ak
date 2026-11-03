# -*- coding: utf-8 -*-
"""AKQuant 趋势交易策略 —— 单标的回测入口（含止损止盈增强对比）。

策略类定义在 trend_strategies.py（可导入模块），本入口负责：
  - 拉取数据
  - 回测基础策略 vs 止损止盈增强策略
  - 输出绩效对比

用法：
  .venv/Scripts/python.exe trend_strategy.py                    # 沪深300
  .venv/Scripts/python.exe trend_strategy.py --symbol 399006    # 创业板指
  .venv/Scripts/python.exe trend_strategy.py --strategy stop    # 只看止损止盈增强
  .venv/Scripts/python.exe trend_strategy.py --strategy trailing # 只看追踪止损
  .venv/Scripts/python.exe trend_strategy.py --start 20180101

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import argparse
import datetime

from akquant import run_backtest

from trend_strategies import (
    fetch_data,
    DualMACrossStrategy,
    MA60TrendStrategy,
    MA60WithStopStrategy,
    MA60TrailingStopStrategy,
    summarize,
    buy_hold_benchmark,
    A_SHARE_BROKER_PROFILE,
)


def run_one(strategy_cls, symbol, df, initial_cash=1_000_000.0):
    """按 A 股真实交易成本回测（佣金+印花税+过户费+最低佣金+滑点+T+1）。"""
    return run_backtest(
        strategy=strategy_cls,
        data=df,
        symbols=symbol,
        initial_cash=initial_cash,
        broker_profile=A_SHARE_BROKER_PROFILE,
    )


def main():
    parser = argparse.ArgumentParser(description="AKQuant 趋势交易策略回测")
    parser.add_argument("--symbol", default="000300", help="标的代码")
    parser.add_argument("--strategy", default="all",
                        choices=["all", "base", "stop", "trailing"],
                        help="all=全部对比, base=基础策略, stop=止损止盈, trailing=追踪止损")
    parser.add_argument("--start", default="20180101", help="回测起始日期")
    parser.add_argument("--end", default=None, help="回测结束日期（默认今天）")
    parser.add_argument("--cash", type=float, default=1_000_000.0, help="初始资金")
    args = parser.parse_args()

    if args.end is None:
        args.end = datetime.date.today().strftime("%Y%m%d")

    print(f"拉取 {args.symbol} 日线数据 ({args.start} ~ {args.end}) ...")
    df, symbol = fetch_data(args.symbol, args.start, args.end)
    print(f"数据条数: {len(df)}，区间: {df['date'].iloc[0]} ~ {df['date'].iloc[-1]}")

    def maybe_run(name, cls, tag):
        if args.strategy in ("all", tag):
            print(f"\n>>> 运行 {name} ...")
            summarize(name, run_one(cls, symbol, df, args.cash))

    maybe_run("双均线交叉 MA30/60", DualMACrossStrategy, "base")
    maybe_run("单均线趋势 MA60", MA60TrendStrategy, "base")
    maybe_run("单均线 MA60 + 止损止盈(8%/20%)", MA60WithStopStrategy, "stop")
    maybe_run("单均线 MA60 + 追踪止损(10%)", MA60TrailingStopStrategy, "trailing")

    # 买入持有基准
    bh_ret, bh_mdd = buy_hold_benchmark(df)
    print(f"\n{'='*60}")
    print(f"  【买入持有基准】")
    print(f"  累计收益率    : {bh_ret:.2f}%")
    print(f"  最大回撤      : {bh_mdd:.2f}%")
    print(f"{'='*60}")

    print(f"\n{'='*60}")
    print("  【结论提示】")
    print("  - 止损止盈的价值：截断单笔巨亏、锁定浮盈，通常降低回撤。")
    print("  - 代价：止损可能被震荡洗出，止盈可能踏空大趋势。")
    print("  - 追踪止损比固定止盈更能吃到大波段，是趋势策略的更优搭配。")
    print("  - 本回测仅供研究参考，不构成投资建议。")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
