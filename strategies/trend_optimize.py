# -*- coding: utf-8 -*-
"""AKQuant 趋势策略 —— 参数网格优化入口。

用 AKQuant 内置的多进程 Grid Search（run_grid_search）对单均线趋势策略的
关键参数做穷举优化，找出历史数据上的最优组合。

注意：
  - Windows 多进程用 spawn 启动，策略类必须定义在可导入模块 trend_strategies.py
    （已满足），本入口须有 if __name__ == "__main__" 保护。
  - 网格搜索极易过拟合，结果仅代表"历史理论最优"，切勿直接用于实盘。

用法：
  .venv/Scripts/python.exe trend_optimize.py --symbol 399006
  .venv/Scripts/python.exe trend_optimize.py --symbol 000300 --workers 4
"""

from __future__ import annotations

import argparse
import datetime

from akquant import run_grid_search

from trend_strategies import fetch_data, MA60WithStopStrategy, A_SHARE_BROKER_PROFILE


def main():
    parser = argparse.ArgumentParser(description="AKQuant 趋势策略参数网格优化")
    parser.add_argument("--symbol", default="399006", help="标的代码")
    parser.add_argument("--start", default="20180101", help="起始日期")
    parser.add_argument("--end", default=None, help="结束日期")
    parser.add_argument("--workers", type=int, default=4, help="并行进程数")
    parser.add_argument("--top", type=int, default=10, help="输出前 N 组最优参数")
    args = parser.parse_args()

    if args.end is None:
        args.end = datetime.date.today().strftime("%Y%m%d")

    print(f"拉取 {args.symbol} 日线数据 ({args.start} ~ {args.end}) ...")
    df, symbol = fetch_data(args.symbol, args.start, args.end)
    print(f"数据条数: {len(df)}")

    # 参数网格：均线周期 × 止损比例 × 止盈比例
    param_grid = {
        "ma_period": [20, 30, 40, 50, 60, 90, 120],
        "stop_loss_pct": [0.05, 0.08, 0.10, 0.15],
        "take_profit_pct": [0.10, 0.15, 0.20, 0.30],
    }
    total_combos = 7 * 4 * 4
    print(f"\n参数网格: ma_period×{len(param_grid['ma_period'])} "
          f"stop_loss×{len(param_grid['stop_loss_pct'])} "
          f"take_profit×{len(param_grid['take_profit_pct'])} = {total_combos} 组")
    print(f"并行进程数: {args.workers}\n")

    # 结果筛选：避免选出"只交易一次"的过拟合幸存者
    # 注意：result_filter 接收的是 dict（不是 metrics 对象），用键访问。
    # max_drawdown_pct 是百分数（如 7.05 表示 7.05%）。
    def result_filter(metrics):
        try:
            trades = metrics.get("closed_trade_count", 0)
            mdd = metrics.get("max_drawdown_pct", 999.0)
            return trades >= 10 and mdd < 20.0
        except Exception:
            return True

    print("开始网格搜索（按夏普比率降序）...")
    results = run_grid_search(
        strategy=MA60WithStopStrategy,
        param_grid=param_grid,
        data=df,
        symbols=symbol,
        initial_cash=1_000_000.0,
        broker_profile=A_SHARE_BROKER_PROFILE,
        sort_by=["sharpe_ratio", "total_return_pct"],
        ascending=[False, False],
        result_filter=result_filter,
        max_workers=args.workers,
        strict_strategy_params=True,
    )

    print(f"\n{'='*70}")
    print(f"  TOP {args.top} 最优参数组合（按夏普比率）")
    print(f"{'='*70}")

    cols = ["ma_period", "stop_loss_pct", "take_profit_pct",
            "total_return_pct", "max_drawdown_pct", "sharpe_ratio", "closed_trade_count"]
    top = results.head(args.top)
    header = (f"{'ma':>5} {'止损%':>6} {'止盈%':>6} "
              f"{'累计收益':>10} {'最大回撤':>9} {'夏普':>7} {'交易数':>6}")
    print(header)
    print("-" * 70)
    for _, row in top.iterrows():
        print(f"{int(row['ma_period']):>5} "
              f"{row['stop_loss_pct']*100:>5.0f}% "
              f"{row['take_profit_pct']*100:>5.0f}% "
              f"{row['total_return_pct']:>9.2f}% "
              f"{row['max_drawdown_pct']:>8.2f}% "
              f"{row['sharpe_ratio']:>7.3f} "
              f"{int(row['closed_trade_count']):>6}")

    print(f"\n{'='*70}")
    print("  ⚠️ 过拟合提醒")
    print("  - 网格搜索是「看着答案找最优解」，选出的参数可能只是历史噪声。")
    print("  - 应关注「参数稳健性」：相邻参数是否表现相近，而非只看第一名的尖峰。")
    print("  - 更稳健的做法是 Walk-Forward（滚动优化），或直接沿用默认参数。")
    print("  - 本优化仅供研究参考，不构成投资建议。")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
