# -*- coding: utf-8 -*-
"""宽基指数 MA30 / MA60 站上/跌破 每日监控。

复用 index_risk.fetcher 的日 K 采集能力，对六个宽基指数计算：
  - MA30（30 日均线，短期趋势）
  - MA60（60 日均线，中期趋势）
  - 现价相对 MA30 / MA60 的位置（站上 / 跌破 / 接近）
  - MA30 与 MA60 的交叉状态（金叉 / 死叉 / 多头排列 / 空头排列）

输出：
  1. 终端文本报告
  2. HTML 可视化报告到 reports/每日均线监控_YYYY-MM-DD.html

用法：
  python ma_monitor.py
  python ma_monitor.py --no-html     # 只输出终端文本，不生成 HTML

数据仅供研究教学演示，不构成投资建议。
"""

from __future__ import annotations

import argparse
import datetime
import os
from typing import Dict, List

from index_risk.fetcher import INDEX_CONFIG, fetch_kline, FetchError

# 现价距离均线多近算"接近"（百分比）
NEAR_PCT = 2.0


def calc_ma(closes: List[float], window: int) -> float:
    """计算简单移动平均。"""
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def cross_state(ma30_now: float, ma60_now: float, ma30_prev: float, ma60_prev: float) -> str:
    """判断 MA30 与 MA60 的交叉状态。"""
    if ma30_prev is None or ma60_prev is None:
        # 无历史对比，只看当前排列
        return "多头" if ma30_now >= ma60_now else "空头"
    if ma30_prev <= ma60_prev and ma30_now > ma60_now:
        return "金叉(刚上穿)"
    if ma30_prev >= ma60_prev and ma30_now < ma60_now:
        return "死叉(刚下穿)"
    return "多头" if ma30_now >= ma60_now else "空头"


def pos_label(cur: float, ma: float) -> tuple:
    """返回 (状态文本, 偏离度%)。"""
    if ma is None:
        return ("—", None)
    pct = (cur - ma) / ma * 100
    if pct >= 0:
        return ("站上", pct)
    elif abs(pct) <= NEAR_PCT:
        return ("接近(略跌破)", pct)
    else:
        return ("跌破", pct)


def analyze_index(code: str) -> Dict:
    """分析单个指数的均线状态。"""
    cfg = INDEX_CONFIG[code]
    name = cfg["name"]
    try:
        klines = fetch_kline(code, days=300)
    except FetchError as e:
        return {"code": code, "name": name, "error": str(e)}

    if len(klines) < 60:
        return {"code": code, "name": name, "error": "历史数据不足 60 日"}

    closes = [k["close"] for k in klines]
    cur = closes[-1]

    ma30 = calc_ma(closes, 30)
    ma60 = calc_ma(closes, 60)

    # 前一日 MA 用于交叉判断
    ma30_prev = calc_ma(closes[:-1], 30) if len(closes) > 30 else None
    ma60_prev = calc_ma(closes[:-1], 60) if len(closes) > 60 else None

    state30, pct30 = pos_label(cur, ma30)
    state60, pct60 = pos_label(cur, ma60)
    cross = cross_state(ma30, ma60, ma30_prev, ma60_prev)

    # 趋势确认信号：站上 MA60 是右侧确认的关键
    if state60 == "站上":
        signal = "右侧确认(站上MA60)"
    elif state60 == "接近(略跌破)":
        signal = "临界(接近MA60)"
    else:
        signal = "趋势未确认(MA60下方)"

    return {
        "code": code,
        "name": name,
        "cur": cur,
        "ma30": ma30,
        "ma60": ma60,
        "state30": state30,
        "pct30": pct30,
        "state60": state60,
        "pct60": pct60,
        "cross": cross,
        "signal": signal,
        "last_date": klines[-1]["date"],
    }


def run() -> List[Dict]:
    """扫描全部指数。"""
    results = []
    for code in INDEX_CONFIG:
        r = analyze_index(code)
        results.append(r)
    return results


def print_report(results: List[Dict]) -> None:
    """输出终端文本报告。"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    line = "=" * 78
    print(line)
    print(f"  宽基指数 MA30 / MA60 每日监控  ——  {today}")
    print(line)

    header = f"{'指数':<7} {'现价':>8} {'MA30':>8} {'vs30':>7} {'MA60':>8} {'vs60':>7}  {'MA30/60':<10} {'趋势信号'}"
    print(header)
    print("-" * 78)

    for r in results:
        if "error" in r:
            print(f"{r['name']:<7}  ⚠️ {r['error']}")
            continue
        vs30 = f"{r['pct30']:+.1f}%" if r["pct30"] is not None else "—"
        vs60 = f"{r['pct60']:+.1f}%" if r["pct60"] is not None else "—"
        print(
            f"{r['name']:<7} {r['cur']:>8.1f} {r['ma30']:>8.1f} {vs30:>7} "
            f"{r['ma60']:>8.1f} {vs60:>7}  {r['cross']:<10} {r['signal']}"
        )
    print(line)

    # 汇总信号
    on_ma60 = [r for r in results if r.get("state60") == "站上"]
    near_ma60 = [r for r in results if r.get("state60") == "接近(略跌破)"]
    golden = [r for r in results if r.get("cross", "").startswith("金叉")]

    print("\n【汇总】")
    print(f"  站上 MA60 的指数：{len(on_ma60)} 个", ("（" + "、".join(r['name'] for r in on_ma60) + "）") if on_ma60 else "")
    print(f"  接近 MA60 的指数：{len(near_ma60)} 个", ("（" + "、".join(r['name'] for r in near_ma60) + "）") if near_ma60 else "")
    print(f"  今日出现金叉   ：{len(golden)} 个", ("（" + "、".join(r['name'] for r in golden) + "）") if golden else "")
    print("\n  注：站上 MA60 视为中期趋势右侧确认信号，是择时加仓的关键触发条件。")
    print("  本报告仅供研究参考，不构成投资建议。\n")


def write_html(results: List[Dict]) -> str:
    """生成 HTML 可视化报告，返回文件路径。"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    os.makedirs("../reports", exist_ok=True)
    path = f"reports/每日均线监控_{today}.html"

    rows = []
    for r in results:
        if "error" in r:
            rows.append(
                f"<tr><td>{r['name']}</td><td colspan='8' class='err'>⚠️ {r['error']}</td></tr>"
            )
            continue
        # 状态颜色：站上=红(涨/多头，符合A股习惯)，跌破=绿
        c30 = "#d43d3d" if r["state30"] == "站上" else ("#d4a017" if "接近" in r["state30"] else "#1a8f5c")
        c60 = "#d43d3d" if r["state60"] == "站上" else ("#d4a017" if "接近" in r["state60"] else "#1a8f5c")
        cross_c = "#d43d3d" if "金叉" in r["cross"] or r["cross"] == "多头" else ("#1a8f5c" if "死叉" in r["cross"] or r["cross"] == "空头" else "#888")
        sig_c = "#d43d3d" if "确认" in r["signal"] else ("#d4a017" if "临界" in r["signal"] else "#888")
        vs30 = f"{r['pct30']:+.1f}%" if r["pct30"] is not None else "—"
        vs60 = f"{r['pct60']:+.1f}%" if r["pct60"] is not None else "—"
        rows.append(
            f"<tr>"
            f"<td class='nm'>{r['name']}</td>"
            f"<td>{r['cur']:.1f}</td>"
            f"<td>{r['ma30']:.1f}</td>"
            f"<td style='color:{c30}'>{r['state30']}<br><span class='pct'>{vs30}</span></td>"
            f"<td>{r['ma60']:.1f}</td>"
            f"<td style='color:{c60}'>{r['state60']}<br><span class='pct'>{vs60}</span></td>"
            f"<td style='color:{cross_c}'>{r['cross']}</td>"
            f"<td style='color:{sig_c};font-weight:600'>{r['signal']}</td>"
            f"</tr>"
        )

    on_ma60 = [r for r in results if r.get("state60") == "站上"]
    golden = [r for r in results if r.get("cross", "").startswith("金叉")]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日均线监控 {today}</title>
<style>
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; margin: 0; padding: 24px; background: #f5f6f8; color: #222; }}
  .wrap {{ max-width: 960px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th, td {{ padding: 12px 10px; text-align: center; font-size: 14px; border-bottom: 1px solid #eee; }}
  th {{ background: #2f3b52; color: #fff; font-weight: 600; }}
  tr:hover td {{ background: #fafbfc; }}
  td.nm {{ font-weight: 600; }}
  .pct {{ color: #999; font-size: 12px; }}
  .err {{ color: #d43d3d; }}
  .summary {{ margin-top: 20px; background: #fff; padding: 16px 20px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: 14px; line-height: 1.8; }}
  .badge {{ display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; margin-right: 6px; }}
  .b-red {{ background: #fdeaea; color: #d43d3d; }}
  .b-green {{ background: #e6f4ec; color: #1a8f5c; }}
  .b-yellow {{ background: #fdf3e0; color: #d4a017; }}
  .note {{ margin-top: 16px; color: #999; font-size: 12px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>宽基指数 MA30 / MA60 每日监控</h1>
  <div class="sub">数据日期：{today} &nbsp;|&nbsp; 数据源：新浪财经日 K</div>

  <table>
    <thead>
      <tr>
        <th>指数</th><th>现价</th><th>MA30</th><th>vs MA30</th><th>MA60</th><th>vs MA60</th><th>MA30/60</th><th>趋势信号</th>
      </tr>
    </thead>
    <tbody>
      {''.join(rows)}
    </tbody>
  </table>

  <div class="summary">
    <div><span class="badge b-red">站上 MA60</span> 中期趋势右侧确认的指数：{len(on_ma60)} 个 {("（" + "、".join(r['name'] for r in on_ma60) + "）") if on_ma60 else "（暂无）"}</div>
    <div><span class="badge b-yellow">接近 MA60</span> 处于临界、值得盯盘的指数：{len([r for r in results if r.get('state60') == '接近(略跌破)'])} 个</div>
    <div><span class="badge b-green">今日金叉</span> MA30 上穿 MA60：{len(golden)} 个 {("（" + "、".join(r['name'] for r in golden) + "）") if golden else "（暂无）"}</div>
    <div style="margin-top:12px">判断口径：<b>站上 MA60</b> = 中期趋势右侧确认，是择时加仓的关键触发条件；<b>MA30 上穿 MA60（金叉）</b> = 短期趋势转强的领先信号。</div>
  </div>

  <div class="note">⚠️ 本报告基于公开数据量化生成，仅供研究参考，不构成投资建议。</div>
</div>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="宽基指数 MA30/MA60 每日监控")
    parser.add_argument("--no-html", action="store_true", help="只输出终端文本，不生成 HTML")
    args = parser.parse_args()

    results = run()
    print_report(results)

    if not args.no_html:
        path = write_html(results)
        print(f"[HTML 报告已生成] {path}")


if __name__ == "__main__":
    main()
