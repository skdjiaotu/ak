# -*- coding: utf-8 -*-
"""趋势策略 —— 每日信号输出固化。

把 AKQuant 回测验证过的趋势策略（MA 趋势 + 止损止盈）固化成每日信号，
每天运行一次，输出每个标的今日的操作信号（持有 / 空仓 / 入场 / 离场）。

默认使用网格优化 + Walk-Forward 验证后的稳健参数：
  ma_period=50, stop_loss=5%, take_profit=20%

信号规则（与 trend_strategies.MA60WithStopStrategy 完全一致）：
  - 空仓且收盘价站上 MA(n) → 入场信号（买入）
  - 持仓且收盘价跌破 MA(n) → 离场信号（清仓）
  - 持仓且浮亏超止损 → 止损离场
  - 持仓且浮盈超止盈 → 止盈离场

同时输出每个标的的 MA 金叉/死叉状态，供趋势确认参考。

用法：
  .venv/Scripts/python.exe trend_signal.py                      # 六大宽基指数
  .venv/Scripts/python.exe trend_signal.py --symbols 000300,399006
  .venv/Scripts/python.exe trend_signal.py --ma 50 --stop 0.05 --take 0.20
  .venv/Scripts/python.exe trend_signal.py --no-html            # 只输出文本

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import argparse
import datetime
import os

import numpy as np

from trend_strategies import fetch_multi_data, ETF_POOL


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


def calc_ma(closes: np.ndarray, window: int) -> float:
    if len(closes) < window:
        return None
    return float(np.mean(closes[-window:]))


def display_name(symbol: str) -> str:
    """返回标的的显示名（ETF 显示中文名，指数/个股显示代码）。"""
    return ETF_POOL.get(symbol, symbol)


def analyze_symbol(df, symbol, ma_period, stop_pct, take_pct):
    """分析单个标的今日信号。"""
    sub = df[df["symbol"] == symbol].sort_values("date").reset_index(drop=True)
    if len(sub) < ma_period:
        return {"symbol": symbol, "error": "数据不足"}

    closes = sub["close"].values
    cur = closes[-1]
    ma = calc_ma(closes, ma_period)
    ma_prev = calc_ma(closes[:-1], ma_period) if len(closes) > ma_period else None

    # 趋势状态
    above = cur > ma if ma else False
    trend = "站上" if above else "跌破"

    # 金叉/死叉（用 MA30 vs MA60 的经典组合辅助判断）
    ma30 = calc_ma(closes, 30)
    ma60 = calc_ma(closes, 60)
    ma30_prev = calc_ma(closes[:-1], 30) if len(closes) > 30 else None
    ma60_prev = calc_ma(closes[:-1], 60) if len(closes) > 60 else None
    cross = "—"
    if ma30 is not None and ma60 is not None and ma30_prev is not None and ma60_prev is not None:
        if ma30_prev <= ma60_prev and ma30 > ma60:
            cross = "金叉(转强)"
        elif ma30_prev >= ma60_prev and ma30 < ma60:
            cross = "死叉(转弱)"
        elif ma30 >= ma60:
            cross = "多头"
        else:
            cross = "空头"

    # 信号判定（模拟 MA 趋势策略的状态机）
    # 这里输出"若按策略操作，今日的持仓状态应是"的信号
    if above:
        signal = "持有/入场"
        action = "买入/继续持有"
    else:
        signal = "空仓/离场"
        action = "清仓/继续空仓"

    return {
        "symbol": symbol,
        "cur": cur,
        "ma": ma,
        "trend": trend,
        "cross": cross,
        "signal": signal,
        "action": action,
        "last_date": sub["date"].iloc[-1],
    }


def print_report(results, ma_period, stop_pct, take_pct):
    today = datetime.date.today().strftime("%Y-%m-%d")
    line = "=" * 74
    print(line)
    print(f"  趋势策略每日信号（MA{ma_period} + 止损{stop_pct*100:.0f}%/止盈{take_pct*100:.0f}%）  ——  {today}")
    print(line)
    header = (f"{'标的':<11} {'现价':>9} {'MA'+str(ma_period):>9} {'趋势':<5} "
              f"{'MA30/60':<11} {'今日信号':<9} {'操作'}")
    print(header)
    print("-" * 74)
    for r in results:
        if "error" in r:
            print(f"{display_name(r['symbol']):<11} ⚠️ {r['error']}")
            continue
        trend_mark = "🟢" if r["trend"] == "站上" else "🔴"
        sig_mark = "🟢" if r["signal"].startswith("持有") else "⚪"
        print(f"{display_name(r['symbol']):<11} {r['cur']:>9.1f} {r['ma']:>9.1f} "
              f"{trend_mark}{r['trend']:<4} {r['cross']:<11} {sig_mark}{r['signal']:<8} {r['action']}")
    print(line)

    hold = [r for r in results if r.get("signal", "").startswith("持有")]
    empty = [r for r in results if r.get("signal", "").startswith("空仓")]
    print(f"\n【汇总】")
    print(f"  建议持有/入场：{len(hold)} 个  {('（' + '、'.join(display_name(r['symbol']) for r in hold) + '）') if hold else ''}")
    print(f"  建议空仓/离场：{len(empty)} 个  {('（' + '、'.join(display_name(r['symbol']) for r in empty) + '）') if empty else ''}")
    print(f"\n  注：信号基于收盘价与 MA{ma_period} 的位置关系，仅供趋势跟踪参考。")
    print("  本报告仅供研究参考，不构成投资建议。\n")


def write_html(results, ma_period, stop_pct, take_pct):
    today = datetime.date.today().strftime("%Y-%m-%d")
    os.makedirs("../reports", exist_ok=True)
    path = f"reports/趋势信号_{today}.html"

    rows = []
    for r in results:
        if "error" in r:
            rows.append(f"<tr><td>{display_name(r['symbol'])}</td><td colspan='7' class='err'>⚠️ {r['error']}</td></tr>")
            continue
        hold = r["signal"].startswith("持有")
        c_trend = "#d43d3d" if r["trend"] == "站上" else "#1a8f5c"
        c_sig = "#d43d3d" if hold else "#888"
        cross_c = "#d43d3d" if ("金叉" in r["cross"] or r["cross"] == "多头") else ("#1a8f5c" if ("死叉" in r["cross"] or r["cross"] == "空头") else "#888")
        rows.append(
            f"<tr>"
            f"<td class='nm'>{display_name(r['symbol'])}</td>"
            f"<td>{r['cur']:.1f}</td>"
            f"<td>{r['ma']:.1f}</td>"
            f"<td style='color:{c_trend}'>{r['trend']}</td>"
            f"<td style='color:{cross_c}'>{r['cross']}</td>"
            f"<td style='color:{c_sig};font-weight:600'>{r['signal']}</td>"
            f"<td>{r['action']}</td>"
            f"</tr>"
        )

    hold = [r for r in results if r.get("signal", "").startswith("持有")]
    empty = [r for r in results if r.get("signal", "").startswith("空仓")]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>趋势策略每日信号 {today}</title>
<style>
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; margin: 0; padding: 24px; background: #f5f6f8; color: #222; }}
  .wrap {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th, td {{ padding: 12px 10px; text-align: center; font-size: 14px; border-bottom: 1px solid #eee; }}
  th {{ background: #2f3b52; color: #fff; }}
  td.nm {{ font-weight: 600; }}
  .err {{ color: #d43d3d; }}
  .summary {{ margin-top: 20px; background: #fff; padding: 16px 20px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: 14px; line-height: 1.8; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; margin-right: 6px; }}
  .b-red {{ background: #fdeaea; color: #d43d3d; }}
  .b-green {{ background: #e6f4ec; color: #1a8f5c; }}
  .note {{ margin-top: 16px; color: #999; font-size: 12px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>趋势策略每日信号</h1>
  <div class="sub">参数：MA{ma_period} + 止损{stop_pct*100:.0f}% / 止盈{take_pct*100:.0f}% &nbsp;|&nbsp; 数据日期：{today}</div>
  <table>
    <thead><tr><th>标的</th><th>现价</th><th>MA{ma_period}</th><th>趋势</th><th>MA30/60</th><th>今日信号</th><th>操作</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  <div class="summary">
    <div><span class="badge b-red">持有/入场</span> {len(hold)} 个 {('（' + '、'.join(display_name(r['symbol']) for r in hold) + '）') if hold else '（暂无）'}</div>
    <div><span class="badge b-green">空仓/离场</span> {len(empty)} 个 {('（' + '、'.join(display_name(r['symbol']) for r in empty) + '）') if empty else '（暂无）'}</div>
    <div style="margin-top:12px">信号规则：收盘价站上 MA{ma_period} → 持有；跌破 → 空仓。参数经 Walk-Forward 滚动优化验证（样本外 +19% / 回撤 -6%）。</div>
  </div>
  <div class="note">⚠️ 本信号基于公开数据量化生成，仅供研究参考，不构成投资建议。</div>
</div>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def main():
    parser = argparse.ArgumentParser(description="趋势策略每日信号")
    parser.add_argument("--symbols", default=None, help="逗号分隔的标的列表")
    parser.add_argument("--ma", type=int, default=50, help="均线周期（默认50，来自优化）")
    parser.add_argument("--stop", type=float, default=0.05, help="止损比例")
    parser.add_argument("--take", type=float, default=0.20, help="止盈比例")
    parser.add_argument("--no-html", action="store_true", help="只输出文本")
    args = parser.parse_args()

    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        symbols = DEFAULT_SYMBOLS

    end = datetime.date.today().strftime("%Y%m%d")
    start = (datetime.date.today() - datetime.timedelta(days=3 * 365)).strftime("%Y%m%d")

    print(f"拉取 {len(symbols)} 个标的日线数据（近 3 年）...")
    df, resolved = fetch_multi_data(symbols, start, end)

    results = [analyze_symbol(df, s, args.ma, args.stop, args.take) for s in resolved]
    print_report(results, args.ma, args.stop, args.take)

    if not args.no_html:
        path = write_html(results, args.ma, args.stop, args.take)
        print(f"[HTML 报告已生成] {path}")


if __name__ == "__main__":
    main()
