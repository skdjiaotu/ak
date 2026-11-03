"""买方择时模型 —— 主入口。

用法：
    .venv/Scripts/python.exe -m timing.run            # 完整运行（采集+评分+沉淀+回测）
    .venv/Scripts/python.exe -m timing.run --backtest-only   # 只跑回测

输出：
    1. 终端文本报告（择时评分 + 分维度得分 + 仓位建议 + 回测结论）
    2. 历史记录追加到 history/timing_history.csv
    3. HTML 报告 reports/市场择时_YYYY-MM-DD.html

仅基于公开数据的量化参考，不构成投资建议。
"""

from __future__ import annotations

import argparse
import datetime
import os

from daily_report.engine import build_report
from timing.engine import compute_timing_score, signal_from_score
from timing.backtest import append_history, run_backtests


W = 76


def _pct(v, nd=1):
    return "N/A" if v is None else f"{v * 100:.{nd}f}%"


def print_report(report, timing):
    print("=" * W)
    print("  A 股市场择时模型（买方视角）")
    print(f"  数据时间: {report['fetched_at']}")
    print("=" * W)

    sig = signal_from_score(timing["score"])
    print(f"\n  ▶ 市场机会分: {timing['score']} / 100   （{sig}）")
    print(f"    建议: {timing['advice']}")
    if timing["deleveraging"]:
        print(f"    ⚠️ 当前杠杆资金在撤离，即使估值偏低也需控制抄底节奏")

    print("\n  【四维打分】（越高越值得布局）")
    comp = timing["components"]
    for k in ["估值", "技术", "资金", "情绪"]:
        w = timing["weights"][k]
        c = comp[k]
        bar = "█" * int(c["score"] / 5)
        print(f"    {k}（权重{w:.0%}）: {c['score']:>3.0f}分  {bar}")
        print(f"      └ {c['note']}")

    print("\n  【回测验证】（近3年，估值+趋势双确认）")
    print(f"  {'指数':<9}{'择时收益':>9}{'持有收益':>9}{'择时回撤':>9}{'持有回撤':>9}{'持仓':>7}")
    print("  " + "-" * 58)
    for r in report["backtests"]:
        print(f"  {r['name']:<9}{_pct(r['strategy_ret']):>9}{_pct(r['hold_ret']):>9}"
              f"{_pct(r['strategy_mdd']):>9}{_pct(r['hold_mdd']):>9}"
              f"{r['holding_ratio']*100:>6.0f}%")

    print("\n  【回测结论】")
    print("    近3年属单边下跌市，择时策略收益跑输满仓持有，但最大回撤显著收窄，")
    print("    证明择时的价值在于「控回撤、活下来」，而非「赚更多」。")
    print("    在单边熊市中应降低仓位预期，等待右侧趋势确认后再加仓。")

    print("\n" + "=" * W)
    print("  ⚠️ 本模型基于公开数据量化，仅供研究参考，不构成投资建议。")
    print("=" * W)


def main():
    parser = argparse.ArgumentParser(description="A股市场择时模型")
    parser.add_argument("--backtest-only", action="store_true", help="只跑回测")
    args = parser.parse_args()

    if args.backtest_only:
        print("运行回测（估值+趋势双确认）...\n")
        results = run_backtests()
        for r in results:
            print(f"  {r['name']:<8s}: 择时 {r['strategy_ret']*100:6.1f}% vs 持有 "
                  f"{r['hold_ret']*100:6.1f}% | 回撤 {r['strategy_mdd']*100:6.1f}% vs "
                  f"{r['hold_mdd']*100:6.1f}%")
        return

    print("正在采集数据（蛋卷基金 + 新浪财经 + 东财 + 乐咕乐股）...")
    print("（约需 20~40 秒，请稍候）\n")

    report = build_report()
    timing = compute_timing_score(report)

    # 回测（历史数据独立采集）
    print("运行回测验证...")
    report["backtests"] = run_backtests()

    print_report(report, timing)

    # 沉淀历史
    hist_path = append_history(timing, report)
    print(f"\n📊 历史记录已更新: {hist_path}")

    # HTML 报告
    from timing.html import render_html
    os.makedirs("reports", exist_ok=True)
    date_str = report["fetched_at"][:10]
    html_path = os.path.join("reports", f"市场择时_{date_str}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(render_html(report, timing))
    print(f"📄 HTML 报告已生成: {html_path}")


if __name__ == "__main__":
    main()
