"""每日市场体检报告 —— 主入口。

用法：
    .venv/Scripts/python.exe -m daily_report.run

输出：
    1. 终端文本报告（四维全景）
    2. HTML 可视化报告（reports/每日市场体检_YYYY-MM-DD.html）
"""

from __future__ import annotations

import os

from daily_report.engine import build_report, overall_signal
from daily_report.html import render_html

W = 72


def _pct(v):
    return "N/A" if v is None else f"{v:.1f}%"


def _num(v, nd=2):
    return "N/A" if v is None else f"{v:,.{nd}f}"


def _yi(v):
    return None if v is None else v / 1e8


def print_report(report):
    r = report
    ff = r["fund_flow"]
    overall = overall_signal(r)

    print("=" * W)
    print("  A 股每日市场体检报告（四维交叉验证）")
    print(f"  数据时间: {r['fetched_at']}")
    print("=" * W)

    # 综合结论置顶
    print(f"\n  ▶ 综合判定: {overall['overall']}")
    print(f"    红灯 {overall['red']} 个 / 黄灯 {overall['yellow']} 个 / 绿灯 {overall['green']} 个")
    for n in overall["notes"]:
        print(f"    • {n}")

    # ① 估值 + 技术
    print("\n【1】宽基指数估值 · 技术 · 危险度")
    print(f"  {'指数':<9}{'PE':>7}{'PE分位':>8}{'PB分位':>8}{'回撤':>8}{'危险度':>7}  信号")
    print("  " + "-" * 62)
    for i in r["indexes"]:
        print(f"  {i['name']:<9}{_num(i['pe_ttm'],1):>7}{_pct(i['pe_percentile']):>8}"
              f"{_pct(i['pb_percentile']):>8}{_pct(i['drawdown']):>8}"
              f"{i['score']:>6.0f}  {i['signal']}")

    # ② 资金面
    print("\n【2】资金面 —— 两融 + 北向（穿透官方假象）")
    print(f"  融资余额:       {_num(_yi(ff['margin_balance']))} 亿元（20日 {_pct(ff['margin_balance_20d'])}）")
    print(f"  杠杆资金判定:   {ff['margin_trend']}")
    print(f"  融资余额/流通市值: {_num(ff['margin_ratio'])}%（{ff['margin_emotion']}）")
    print(f"  北向净买入:     已于 {ff['north_nan_date']} 停止披露（最后披露 {ff['north_last_date']}）")
    print(f"  停更前外资态度: {ff['north_signal']}")

    # ③ 恐慌度
    print("\n【3】恐慌指数（20日年化波动率）")
    for v in r["vix"]:
        print(f"  {v['name']:<8} 波动率 {_pct(v['vol']*100 if v['vol'] else None):>7} "
              f"分位 {_pct(v['vol_percentile']):>7}  {v['level']}")

    print("\n" + "=" * W)
    print("  ⚠️ 本报告基于公开数据量化，仅供研究参考，不构成投资建议。")
    print("=" * W)


def main():
    print("正在采集数据（蛋卷基金 + 新浪财经 + 东财 + 乐咕乐股）...")
    print("（约需 10~30 秒，请稍候）\n")

    report = build_report()
    print_report(report)

    # 生成 HTML
    os.makedirs("reports", exist_ok=True)
    date_str = report["fetched_at"][:10]
    html_path = os.path.join("reports", f"每日市场体检_{date_str}.html")
    html = render_html(report, overall_signal(report))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\n📄 HTML 报告已生成: {html_path}")

    # ---- 记录到策略台账 ----
    try:
        from strategy_log import record
        overall = overall_signal(report)
        record("daily_report", {
            "overall": overall["overall"],
            "red": overall["red"],
            "yellow": overall["yellow"],
            "green": overall["green"],
            "notes": overall["notes"],
            "indexes": report["indexes"],
            "fund_flow": report["fund_flow"],
            "vix": report["vix"],
        })
    except Exception as e:  # noqa
        print(f"[警告] 记录到台账失败: {e}")


if __name__ == "__main__":
    main()
