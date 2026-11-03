# -*- coding: utf-8 -*-
"""多 ETF 轮动策略 —— 每日信号固化。

把 etf_rotation.py 回测验证过的「趋势过滤 + 等权持有」策略固化成每日信号，
每天运行一次，告诉你今日该持有哪些 ETF（以及下一交易日是否要调仓）。

策略规则（参数经 1152 组扫描 + 增强方向验证最优）：
  1. 资产池：原 11 只权益 ETF + 黄金/原油/30年国债（跨资产分散，少而精）
  2. 趋势过滤：只把「收盘价站上 MA20」的 ETF 纳入候选
  3. 等权持有：持有全部站上 MA20 的候选（不截断 TopN，分散最充分）
  4. 空仓规则：若通过过滤的候选不足 min_candidates（默认 2）只，则空仓躲熊市
  5. 波动率目标：组合实现波动率超 18% 时按比例降仓（平滑净值、压回撤、提夏普）
  6. 调仓节奏：每 5 个交易日重选一次，其余时间持有不动

输出：
  - 控制台文本报告（含建议仓位）
  - reports/轮动信号_YYYY-MM-DD.html 可视化报告

用法：
  .venv/Scripts/python.exe etf_signal.py                 # 默认：持有全部站上MA20的候选 + 波动率目标18%
  .venv/Scripts/python.exe etf_signal.py --top 3          # 只持有动量最强 3 只
  .venv/Scripts/python.exe etf_signal.py --ma 60 --lookback 20
  .venv/Scripts/python.exe etf_signal.py --no-html        # 只输出文本

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import argparse
import datetime
import os

import numpy as np
import pandas as pd

from etf_rotation import MULTI_ASSET_POOL, build_panel


def latest_panel(pool: dict, start: str = "20180101", min_count: int = 4):
    """拉取最新数据并构建面板，返回 (panel, 各ETF最新收盘价 dict)。"""
    panel = build_panel(pool, start, min_count)
    last = panel.iloc[-1]
    return panel, last.to_dict()


def compute_signal(panel: pd.DataFrame, ma_period: int = 20, lookback: int = 20,
                   top_n: int = None, min_candidates: int = 2,
                   use_vol_target: bool = True, vol_target: float = 0.18,
                   vol_window: int = 20):
    """计算今日信号，返回结构化结果 dict（含波动率目标仓位建议）。

    top_n=None 表示「持有全部站上 MA 的候选」等权（不截断）。
    这是经扫描验证的最优：持有越多、分散越充分、波动越低、收益越高。
    """
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values

    # 各 ETF 当前收盘价与 MA
    ma = pd.DataFrame(close).rolling(ma_period).mean().values
    cur = close[-1]
    ma_now = ma[-1]
    above = cur > ma_now  # 趋势过滤

    # 近 lookback 日动量
    past = close[-lookback - 1:-1] if n > lookback else close
    mom = past[-1] / past[0] - 1

    # 候选（站上 MA 的 ETF）
    candidates = [(cols[j], mom[j], cur[j], ma_now[j]) for j in range(m) if above[j]]
    # 按动量降序
    candidates.sort(key=lambda x: x[1], reverse=True)

    # 判定是否触发调仓
    holding = []
    action = "空仓"
    if len(candidates) >= max(1, min_candidates):
        # top_n=None 时持有全部候选（不截断）；否则取动量前 top_n 只
        holding = candidates if top_n is None else candidates[:top_n]
        action = "持有全部 {} 只".format(len(holding)) if top_n is None \
            else "持有 Top{}".format(top_n)

    # 波动率目标控制：用近 vol_window 日组合（等权 Top N）收益波动率估算，
    # 实际目标波动率超阈值时按比例降仓，剩余资金持现金。
    # 说明：这里用「等权 Top N 的历史收益」近似代表组合历史波动（与回测一致口径）。
    scale = 1.0
    vol_note = ""
    if use_vol_target and holding:
        # 重构等权 Top N 组合的历史日收益（近 vol_window 日）
        top_names = [c[0] for c in holding]
        top_idx = [cols.index(nm) for nm in top_names]
        hist_close = close[:, top_idx]
        hist_ret = pd.DataFrame(hist_close).pct_change().iloc[-vol_window - 1:]
        port_ret = hist_ret.mean(axis=1).dropna().values
        if len(port_ret) > 1:
            realized_vol = np.std(port_ret) * np.sqrt(250)
            if realized_vol > 0:
                scale = min(vol_target / realized_vol, 1.0)
                scale = max(scale, 0.0)
                if scale < 0.999:
                    vol_note = (f"组合近{vol_window}日年化波动率 {realized_vol*100:.1f}% "
                                f"超过目标 {vol_target*100:.0f}%，建议仓位降至 {scale*100:.0f}%")
                else:
                    vol_note = (f"组合近{vol_window}日年化波动率 {realized_vol*100:.1f}% "
                                f"在目标 {vol_target*100:.0f}% 内，可满仓")
            else:
                vol_note = "波动率近零，可满仓"
        else:
            vol_note = "数据不足，默认满仓"

    # 所有 ETF 明细（含非候选）
    details = []
    for j in range(m):
        name = cols[j]
        details.append({
            "name": name,
            "cur": cur[j],
            "ma": ma_now[j],
            "above": bool(above[j]),
            "mom": mom[j],
            "rank": None,
        })
    # 标注动量排名（仅候选内排名）
    for k, c in enumerate(candidates):
        for d in details:
            if d["name"] == c[0]:
                d["rank"] = k + 1

    return {
        "date": str(panel.index[-1]),
        "ma_period": ma_period,
        "lookback": lookback,
        "top_n": len(holding) if top_n is None else top_n,
        "min_candidates": min_candidates,
        "holding": holding,          # [(name, mom, cur, ma), ...]
        "candidates": candidates,    # 全部候选（按动量排序）
        "details": details,          # 全池明细
        "action": action,
        "n_candidates": len(candidates),
        "scale": scale,              # 波动率目标建议仓位（0~1）
        "vol_note": vol_note,        # 波动率目标说明
        "vol_target": vol_target,
    }


def print_report(sig: dict):
    today = datetime.date.today().strftime("%Y-%m-%d")
    line = "=" * 76
    print(line)
    print(f"  多 ETF 轮动策略每日信号（MA{sig['ma_period']} 过滤 + 等权持有 + 波动率目标{sig['vol_target']*100:.0f}%）  ——  {today}")
    print(f"  数据日期：{sig['date']}")
    print(line)

    print(f"\n【今日信号】{sig['action']}")
    if sig["holding"]:
        print(f"  建议持有以下 {len(sig['holding'])} 只 ETF（等权）：")
        for name, mom, cur, ma in sig["holding"]:
            print(f"    🟢 {name:<10} 现价 {cur:>8.3f}  站上MA{sig['ma_period']} {ma:.3f}  近{sig['lookback']}日涨幅 {mom*100:>6.2f}%")
        # 波动率目标仓位建议
        if sig.get("vol_note"):
            print(f"\n  📊 仓位控制：{sig['vol_note']}")
            print(f"     → 建议总仓位 {sig['scale']*100:.0f}%，单只约 {sig['scale']*100/len(sig['holding']):.1f}%")
    else:
        print("  ⚪ 无候选通过趋势过滤，建议空仓（普跌市，规避系统性风险）")

    print(f"\n【全池明细】（按近{sig['lookback']}日动量排序）")
    det = sorted(sig["details"], key=lambda d: d["mom"], reverse=True)
    header = f"  {'排名':<5}{'ETF':<12}{'现价':>9}{'MA'+str(sig['ma_period']):>9}{'趋势':<6}{'动量':>8}"
    print(header)
    print("  " + "-" * 66)
    for d in det:
        mark = "🟢站上" if d["above"] else "🔴跌破"
        rank = f"{d['rank']}" if d["rank"] else "—"
        print(f"  {rank:<5}{d['name']:<12}{d['cur']:>9.3f}{d['ma']:>9.3f}{mark:<7}{d['mom']*100:>7.2f}%")
    print(line)

    print("\n  注：信号基于收盘价与 MA 的位置关系 + 近 20 日动量，仅供趋势跟踪参考。")
    print("  调仓节奏：每 5 个交易日重选一次，其余时间持有不动。")
    print("  本报告仅供研究参考，不构成投资建议。\n")


def write_html(sig: dict):
    today = datetime.date.today().strftime("%Y-%m-%d")
    os.makedirs("../reports", exist_ok=True)
    path = f"reports/轮动信号_{today}.html"

    # 持仓卡
    if sig["holding"]:
        hold_cards = []
        for name, mom, cur, ma in sig["holding"]:
            hold_cards.append(
                f"<div class='hold-card'>"
                f"<div class='hold-name'>{name}</div>"
                f"<div class='hold-price'>¥{cur:.3f}</div>"
                f"<div class='hold-mom' style='color:#d43d3d'>+{mom*100:.2f}%</div>"
                f"<div class='hold-sub'>站上 MA{sig['ma_period']} {ma:.3f}</div>"
                f"</div>"
            )
        hold_html = "".join(hold_cards)
        # 波动率目标仓位控制卡
        if sig.get("vol_note"):
            hold_html += (
                f"<div class='vol-card'>"
                f"<div class='vol-title'>📊 波动率目标仓位控制</div>"
                f"<div class='vol-note'>{sig['vol_note']}</div>"
                f"<div class='vol-scale'>建议总仓位 <span style='color:#d43d3d;font-weight:700'>{sig['scale']*100:.0f}%</span>"
                f"（单只约 {sig['scale']*100/len(sig['holding']):.1f}%）</div>"
                f"</div>"
            )
    else:
        hold_html = "<div class='empty'>⚪ 无候选通过趋势过滤，建议空仓（普跌市规避系统性风险）</div>"

    # 全池明细表
    det = sorted(sig["details"], key=lambda d: d["mom"], reverse=True)
    rows = []
    for d in det:
        mark = "🟢 站上" if d["above"] else "🔴 跌破"
        c = "#d43d3d" if d["above"] else "#1a8f5c"
        mom_c = "#d43d3d" if d["mom"] >= 0 else "#1a8f5c"
        rank = str(d["rank"]) if d["rank"] else "—"
        # 持有判定：是候选（站上MA 且有排名）即被等权持有
        held = d["rank"] is not None and len(sig["candidates"]) >= sig["min_candidates"]
        bg = "background:#fdf0f0;" if held else ""
        rows.append(
            f"<tr style='{bg}'>"
            f"<td>{rank}</td>"
            f"<td class='nm'>{d['name']}</td>"
            f"<td>{d['cur']:.3f}</td>"
            f"<td>{d['ma']:.3f}</td>"
            f"<td style='color:{c}'>{mark}</td>"
            f"<td style='color:{mom_c};font-weight:600'>{d['mom']*100:+.2f}%</td>"
            f"</tr>"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>多 ETF 轮动策略每日信号 {today}</title>
<style>
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif; margin: 0; padding: 24px; background: #f5f6f8; color: #222; }}
  .wrap {{ max-width: 900px; margin: 0 auto; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }}
  .sub {{ color: #888; font-size: 13px; margin-bottom: 20px; }}
  .signal {{ background: #fff; padding: 16px 20px; border-radius: 8px; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 16px; }}
  .signal-title {{ font-size: 15px; font-weight: 600; margin-bottom: 12px; }}
  .holds {{ display: flex; flex-wrap: wrap; gap: 12px; }}
  .hold-card {{ flex: 1 1 160px; background: #fdf0f0; border: 1px solid #f3caca; border-radius: 8px; padding: 14px; text-align: center; }}
  .hold-name {{ font-size: 14px; font-weight: 600; }}
  .hold-price {{ font-size: 20px; font-weight: 700; color: #d43d3d; margin: 6px 0 2px; }}
  .hold-mom {{ font-size: 13px; font-weight: 600; }}
  .hold-sub {{ font-size: 11px; color: #999; margin-top: 4px; }}
  .vol-card {{ flex: 1 1 100%; background: #fff8e6; border: 1px solid #f0dca0; border-radius: 8px; padding: 14px 16px; margin-top: 4px; }}
  .vol-title {{ font-size: 14px; font-weight: 600; color: #8a6d1a; margin-bottom: 6px; }}
  .vol-note {{ font-size: 13px; color: #555; }}
  .vol-scale {{ font-size: 14px; color: #333; margin-top: 6px; }}
  .empty {{ padding: 20px; text-align: center; color: #888; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
  th, td {{ padding: 12px 10px; text-align: center; font-size: 14px; border-bottom: 1px solid #eee; }}
  th {{ background: #2f3b52; color: #fff; }}
  td.nm {{ font-weight: 600; }}
  .note {{ margin-top: 16px; color: #999; font-size: 12px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>多 ETF 轮动策略每日信号</h1>
  <div class="sub">参数：MA{sig['ma_period']} 趋势过滤 + 等权持有全部站上MA候选 + 波动率目标{sig['vol_target']*100:.0f}% &nbsp;|&nbsp; 数据日期：{sig['date']}</div>

  <div class="signal">
    <div class="signal-title">今日信号：{sig['action']}</div>
    <div class="holds">{hold_html}</div>
  </div>

  <table>
    <thead><tr><th>排名</th><th>ETF</th><th>现价</th><th>MA{sig['ma_period']}</th><th>趋势</th><th>近{sig['lookback']}日动量</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>

  <div class="note">⚠️ 本信号基于公开数据量化生成，仅供研究参考，不构成投资建议。调仓节奏：每 5 个交易日重选一次，其余时间持有不动。</div>
</div>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


def main():
    parser = argparse.ArgumentParser(description="多 ETF 轮动策略每日信号")
    parser.add_argument("--ma", type=int, default=20, help="趋势过滤均线周期（默认20，来自参数扫描最优）")
    parser.add_argument("--lookback", type=int, default=20, help="动量回看周期（默认20）")
    parser.add_argument("--top", type=int, default=None, help="持有最强 Top N 只（默认None=持有全部站上MA的候选，经扫描验证最优）")
    parser.add_argument("--min-candidates", type=int, default=2, help="最少候选数，不足则空仓（默认2）")
    parser.add_argument("--vol-target", type=float, default=0.18, help="波动率目标（默认0.18=18%%，经扫描验证最优）")
    parser.add_argument("--no-vol-target", action="store_true", help="关闭波动率目标仓位控制")
    parser.add_argument("--no-html", action="store_true", help="只输出文本")
    args = parser.parse_args()

    print("正在拉取 ETF 数据...")
    panel, _ = latest_panel(MULTI_ASSET_POOL)
    print(f"面板：{panel.shape[0]} 个交易日，{panel.shape[1]} 只 ETF，"
          f"{panel.index[0]} ~ {panel.index[-1]}\n")

    sig = compute_signal(panel, ma_period=args.ma, lookback=args.lookback,
                         top_n=args.top, min_candidates=args.min_candidates,
                         use_vol_target=not args.no_vol_target,
                         vol_target=args.vol_target)
    print_report(sig)

    if not args.no_html:
        path = write_html(sig)
        print(f"[HTML 报告已生成] {path}")


if __name__ == "__main__":
    main()
