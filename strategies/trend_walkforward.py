# -*- coding: utf-8 -*-
"""AKQuant 趋势策略 —— Walk-Forward 滚动优化入口。

用 run_walk_forward 验证参数的真实稳健性：把数据切成多个 [训练|测试] 窗口，
每个窗口在训练段做网格搜索选最优参数，再用该参数在紧随其后的测试段验证
（样本外）。拼接所有测试段得到真实可预期的绩效。

对比：网格搜索是"看着答案找最优解"（过拟合风险高），Walk-Forward 是
"只用过去数据决定现在参数"，更接近实战。

用法：
  .venv/Scripts/python.exe trend_walkforward.py --symbol 399006
  .venv/Scripts/python.exe trend_walkforward.py --symbol 000300 --train 500 --test 60

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import argparse
import datetime

from akquant import run_walk_forward

from trend_strategies import fetch_data, MA60WithStopStrategy, A_SHARE_BROKER_PROFILE


# 回调函数须定义在模块顶层，多进程 spawn 才能 pickle 序列化。
def constraint(params):
    """参数约束：止损应小于止盈，避免无效组合。"""
    return params["stop_loss_pct"] < params["take_profit_pct"]


def warmup_calc(params):
    """动态预热期：均线周期 + 缓冲。"""
    return params["ma_period"] + 5


def main():
    parser = argparse.ArgumentParser(description="AKQuant 趋势策略 Walk-Forward 滚动优化")
    parser.add_argument("--symbol", default="399006", help="标的代码")
    parser.add_argument("--start", default="20180101", help="起始日期")
    parser.add_argument("--end", default=None, help="结束日期")
    parser.add_argument("--train", type=int, default=500, help="训练窗口 Bar 数")
    parser.add_argument("--test", type=int, default=60, help="测试窗口 Bar 数")
    parser.add_argument("--workers", type=int, default=4, help="并行进程数")
    args = parser.parse_args()

    if args.end is None:
        args.end = datetime.date.today().strftime("%Y%m%d")

    print(f"拉取 {args.symbol} 日线数据 ({args.start} ~ {args.end}) ...")
    df, symbol = fetch_data(args.symbol, args.start, args.end)
    print(f"数据条数: {len(df)}")

    # 参数网格（与网格优化一致，但只在训练段搜索）
    param_grid = {
        "ma_period": [30, 40, 50, 60, 90],
        "stop_loss_pct": [0.05, 0.08, 0.10],
        "take_profit_pct": [0.15, 0.20, 0.30],
    }

    print(f"\nWalk-Forward 配置:")
    print(f"  训练窗口: {args.train} bars，测试窗口: {args.test} bars")
    print(f"  参数网格: {len(param_grid['ma_period'])}×{len(param_grid['stop_loss_pct'])}×{len(param_grid['take_profit_pct'])} = "
          f"{len(param_grid['ma_period'])*len(param_grid['stop_loss_pct'])*len(param_grid['take_profit_pct'])} 组/窗口")
    print(f"  优化目标: sharpe_ratio，并行进程: {args.workers}\n")

    print("开始 Walk-Forward 滚动优化 ...")
    wfo = run_walk_forward(
        strategy=MA60WithStopStrategy,
        param_grid=param_grid,
        data=df,
        symbols=symbol,
        train_period=args.train,
        test_period=args.test,
        metric="sharpe_ratio",
        ascending=False,
        initial_cash=1_000_000.0,
        broker_profile=A_SHARE_BROKER_PROFILE,
        warmup_calc=warmup_calc,
        constraint=constraint,
        max_workers=args.workers,
        strict_strategy_params=True,
    )

    print(f"\n{'='*70}")
    print(f"  Walk-Forward 滚动优化结果")
    print(f"{'='*70}")

    # 结果按交易日展开，equity 列是样本外拼接的权益曲线
    if hasattr(wfo, "columns") and "equity" in wfo.columns:
        import numpy as np
        equity = wfo["equity"].astype(float).values
        init = 1_000_000.0

        # 样本外整体绩效
        total_ret = (equity[-1] / init - 1) * 100
        peak = np.maximum.accumulate(equity)
        mdd = ((equity - peak) / peak).min() * 100

        # 每段选出的参数（按 train_end 去重，看参数稳定性）
        param_cols = [c for c in ["ma_period", "stop_loss_pct", "take_profit_pct"] if c in wfo.columns]
        if param_cols and "train_end" in wfo.columns:
            seg = wfo.drop_duplicates(subset=["train_end"], keep="first")[param_cols + ["train_end"]]

            print(f"\n  样本外测试天数  : {len(equity)} 天")
            print(f"  样本外累计收益  : {total_ret:.2f}%")
            print(f"  样本外最大回撤  : {mdd:.2f}%")
            print(f"\n  各滚动窗口选出的最优参数（观察是否稳定）：")
            print(f"  {'训练结束':<12} {'ma':>4} {'止损%':>6} {'止盈%':>6}")
            print(f"  {'-'*36}")
            for _, r in seg.iterrows():
                print(f"  {str(r['train_end'])[:10]:<12} "
                      f"{int(r['ma_period']):>4} "
                      f"{r['stop_loss_pct']*100:>5.0f}% "
                      f"{r['take_profit_pct']*100:>5.0f}%")

            # 参数稳定性统计
            if "ma_period" in param_cols:
                ma_vals = seg["ma_period"].astype(int)
                print(f"\n  参数稳定性：")
                print(f"    ma_period 取值分布: {dict(ma_vals.value_counts().sort_index())}")
                print(f"    最常见 ma_period = {ma_vals.mode().iloc[0]}（出现 {int((ma_vals==ma_vals.mode().iloc[0]).sum())}/{len(ma_vals)} 个窗口）")
    else:
        print(f"\n  结果类型: {type(wfo)}")
        try:
            print(f"  列: {list(wfo.columns)}")
        except Exception:
            print(wfo)

    print(f"\n  ⚠️ 解读提示")
    print("  - Walk-Forward 的样本外绩效，才是策略真实可预期的表现。")
    print("  - 若样本外绩效远差于样本内（网格搜索最优），说明参数在过拟合。")
    print("  - 若样本外绩效稳定，说明参数稳健、可放心沿用。")
    print("  - 本优化仅供研究参考，不构成投资建议。")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
