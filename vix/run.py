"""A 股恐慌指数（已实现波动率版）—— 主入口。

用法：
    python -m vix.run                # 沪深300 恐慌指数（默认）
    python -m vix.run 创业板指       # 指定指数
    python -m vix.run all            # 全部指数对比

输出：当前恐慌值、历史分位、恐慌等级、走势统计。
"""

from __future__ import annotations

import sys

from vix.engine import (
    INDEX_SYMBOLS,
    build_vix_dataset,
    panic_level,
    FetchError,
)


def _fmt_pct(v) -> str:
    return "N/A" if v is None else f"{v:.2%}"


def print_report(vix: dict):
    W = 86
    name = vix["name"]
    cur_vol = vix["current_vol"]
    pct = vix["percentile"]
    level, desc = panic_level(cur_vol, pct)

    print("=" * W)
    print(f"A 股恐慌指数（{name} 已实现波动率）")
    print(f"数据时间: {vix['fetched_at']}    近 {vix['history_len']} 个交易日历史")
    print("=" * W)

    print("\n【当前恐慌值】")
    print(f"  20 日年化波动率:   {cur_vol:.2%}")
    print(f"  历史分位:          {pct:.2%}")
    print(f"  恐慌等级:          {level}")
    print(f"  解读:              {desc}")

    print("\n【历史波动率统计】")
    print(f"  最低:  {vix['vol_min']:.2%}")
    print(f"  最高:  {vix['vol_max']:.2%}")
    print(f"  均值:  {vix['vol_mean']:.2%}")
    print(f"  最新收盘: {vix['close']:.2f}")

    # 恐慌刻度条
    print("\n【恐慌刻度】（0 = 平静 ── 100 = 极度恐慌）")
    bar_len = 50
    pos = int(min(max(pct, 0), 1) * bar_len)
    bar = "█" * pos + "░" * (bar_len - pos)
    print(f"  [{bar}] {pct:.0%}")

    print("\n" + "=" * W)
    print("⚠️  本恐慌指数基于已实现波动率，是美股 VIX 的近似代理，不构成投资建议。")
    print("   高波动率常出现在市场下跌期（恐慌），但低波动本身也可能预示变盘。")
    print("=" * W)


def print_comparison(results: list):
    """多指数恐慌对比。"""
    W = 72
    print("=" * W)
    print("A 股主要指数恐慌度对比（20 日年化波动率）")
    print(f"数据时间: {results[0]['fetched_at']}")
    print("=" * W)
    print(f"{'指数':<10}{'当前波动率':>12}{'历史分位':>10}{'恐慌等级':>14}")
    print("-" * W)
    for v in results:
        level, _ = panic_level(v["current_vol"], v["percentile"])
        print(f"{v['name']:<10}{v['current_vol']:>12.2%}{v['percentile']:>10.1%}{level:>14}")
    print("=" * W)


def main():
    args = sys.argv[1:]
    if not args:
        names = ["沪深300"]
    elif args[0].lower() == "all":
        names = list(INDEX_SYMBOLS.keys())
    else:
        names = [a for a in args if a in INDEX_SYMBOLS]
        if not names:
            print(f"未识别指数，可选: {list(INDEX_SYMBOLS.keys())}")
            return

    print("正在采集数据（新浪财经）...")
    results = []
    for name in names:
        try:
            v = build_vix_dataset(name)
            results.append(v)
        except FetchError as e:
            print(f"  ⚠️ {name} 采集失败: {e}")

    if not results:
        print("❌ 采集失败，请检查网络后重试。")
        return

    if len(results) == 1:
        print_report(results[0])
    else:
        print_comparison(results)


if __name__ == "__main__":
    main()
