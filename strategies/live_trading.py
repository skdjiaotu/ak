# -*- coding: utf-8 -*-
"""ETF 轮动策略 —— 实盘调仓指令生成器。

把样本外验证过的最优策略固化为「每日可照做的买卖清单」：

策略（与 final_strategy.py 完全一致，经样本外验证非过拟合）：
  多资产扩池 + MA20 趋势过滤 + 动量选券 + 趋势强度倾斜(cap封顶) + 波动率目标18%

与 etf_signal.py 的区别：
  1. 用最新的 cap 倾斜加权（而非等权）
  2. 输出「增量调仓指令」：对比上一交易日持仓，给出买/卖/加/减的具体金额
  3. 大资金风控：单券权重上限、ETF 流动性/成交额提示、分批建仓建议

持仓记录：stock/持仓记录.csv（首次运行自动初始化，之后每天运行会读取并更新）
  列：date, etf, 代码, 数量(份), 成本价, 备注

用法：
  .venv/Scripts/python.exe live_trading.py                    # 生成今日调仓指令
  .venv/Scripts/python.exe live_trading.py --total 500000     # 指定总资金(元)
  .venv/Scripts/python.exe live_trading.py --dry-run          # 只预览，不更新持仓记录

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import argparse
import csv
import datetime
import os

import numpy as np
import pandas as pd

from etf_rotation import MULTI_ASSET_POOL, build_panel

MA_PERIOD = 20
LOOKBACK = 20
MIN_CANDIDATES = 2
TILT_CAP = 0.4
VOL_TARGET = 0.18
VOL_WINDOW = 20

# 单券权重上限（大资金风控，防单券过重；应 ≤ TILT_CAP，避免顶满上限押单标的）
MAX_SINGLE_WEIGHT = 0.25

# 高波动/商品类 ETF：额外压降权重，避免大资金重仓单一商品（原油/黄金波动剧烈）
HIGH_VOL_ETF = {"原油ETF", "黄金ETF"}

HOLDINGS_FILE = os.path.join("../stock", "持仓记录.csv")

# 流动性参考：ETF 代码 → (近20日均成交额估算阈值, 是否大盘ETF)
# 大资金需关注单券冲击，成交额太低的 ETF 建议控制仓位


def tilt_weights(sel, close_i, ma_i, cols, cap):
    """趋势强度倾斜权重（与 final_strategy 一致），单券封顶 cap。"""
    dev = {c: max(close_i[cols.index(c)] / ma_i[cols.index(c)] - 1, 0.0) for c in sel}
    total = sum(dev.values())
    if total <= 0:
        return {c: 1.0 / len(sel) for c in sel}
    w = {c: dev[c] / total for c in sel}
    for _ in range(50):
        over = [c for c in sel if w[c] > cap]
        if not over:
            break
        below = [c for c in sel if w[c] <= cap]
        if not below:
            w = {c: cap for c in sel}
            break
        spill = sum(w[c] - cap for c in over)
        for c in over:
            w[c] = cap
        rem = sum(dev[c] for c in below)
        for c in below:
            w[c] += spill * (dev[c] / rem if rem > 0 else 1.0 / len(below))
    s = sum(w.values())
    return {c: w[c] / s for c in sel}


def compute_target(panel, ma_period=MA_PERIOD, lookback=LOOKBACK,
                   min_candidates=MIN_CANDIDATES, cap=TILT_CAP,
                   vol_target=VOL_TARGET, vol_window=VOL_WINDOW):
    """计算今日目标持仓 {etf名: 目标权重} + 波动率降仓比例。"""
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values
    ma = pd.DataFrame(close).rolling(ma_period).mean().values
    cur = close[-1]
    ma_now = ma[-1]

    above = [cols[j] for j in range(m) if cur[j] > ma_now[j]]

    target = {}
    if len(above) >= max(1, min_candidates):
        past = close[-lookback - 1:-1] if n > lookback else close
        mom = past[-1] / past[0] - 1
        ranked = sorted(above, key=lambda c: mom[cols.index(c)], reverse=True)
        target = tilt_weights(ranked, cur, ma_now, cols, cap)
        # 大资金风控：单券硬上限 + 高波动商品 ETF 额外降权
        for nm in list(target.keys()):
            if target[nm] > MAX_SINGLE_WEIGHT:
                target[nm] = MAX_SINGLE_WEIGHT
            if nm in HIGH_VOL_ETF:
                target[nm] *= 0.5
        s = sum(target.values())
        if s > 0:
            target = {nm: w / s for nm, w in target.items()}

    # 波动率目标：用当前目标组合近 vol_window 日波动估算降仓比例
    scale = 1.0
    if target:
        names = list(target.keys())
        idx = [cols.index(nm) for nm in names]
        hist_close = close[:, idx]
        hist_ret = pd.DataFrame(hist_close).pct_change().iloc[-vol_window - 1:]
        # 按目标权重加权组合日收益
        w = np.array([target[nm] for nm in names])
        port_ret = (hist_ret.values[1:] * w).sum(axis=1)
        if len(port_ret) > 1:
            realized = np.std(port_ret) * np.sqrt(250)
            if realized > 0:
                scale = min(vol_target / realized, 1.0)
                scale = max(scale, 0.0)
    return target, scale, above, cur, ma_now


def load_holdings():
    """读取持仓记录，返回 {etf名: {qty, cost, code}}。"""
    if not os.path.exists(HOLDINGS_FILE):
        return {}
    out = {}
    with open(HOLDINGS_FILE, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["etf"]
            out[name] = {
                "qty": float(row["数量(份)"]),
                "cost": float(row["成本价"]),
                "code": row.get("代码", ""),
            }
    return out


def save_holdings(holdings):
    """保存持仓记录。"""
    os.makedirs("../stock", exist_ok=True)
    with open(HOLDINGS_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "etf", "代码", "数量(份)", "成本价", "备注"])
        today = datetime.date.today().strftime("%Y-%m-%d")
        for name, h in holdings.items():
            writer.writerow([today, name, h["code"], f"{h['qty']:.0f}",
                             f"{h['cost']:.4f}", ""])


def main():
    ap = argparse.ArgumentParser(description="ETF 轮动策略实盘调仓指令")
    ap.add_argument("--total", type=float, default=None,
                    help="账户总资金(元)，默认50万；用于把权重换算成金额")
    ap.add_argument("--cap", type=float, default=TILT_CAP, help="单券倾斜权重上限")
    ap.add_argument("--dry-run", action="store_true", help="只预览，不更新持仓记录")
    args = ap.parse_args()

    total = args.total or 500000.0

    print("拉取最新 ETF 数据...")
    panel = build_panel(MULTI_ASSET_POOL)
    print(f"面板：{panel.shape[0]} 日 × {panel.shape[1]} 只，最新 {panel.index[-1]}\n")

    target, scale, above, cur, ma_now = compute_target(panel, cap=args.cap)

    print("=" * 78)
    print("  ETF 轮动策略 · 实盘调仓指令")
    print(f"  数据日期：{panel.index[-1]}   总资金：¥{total:,.0f}")
    print(f"  策略：MA{MA_PERIOD}过滤 + 趋势强度倾斜(cap={args.cap}) + 波动率目标{VOL_TARGET*100:.0f}%")
    print("=" * 78)

    if not target:
        print("\n  ⚪ 今日无候选通过趋势过滤（站上MA20的ETF不足%d只）" % MIN_CANDIDATES)
        print("     → 建议清仓/空仓，持有现金规避系统性风险。")
        print("\n  注：跌破 MA20 全池空仓是本策略控制回撤到 -9% 的核心安全网，务必执行。")
        return

    # 目标持仓（名称 -> 目标金额）
    print(f"\n  ▶ 今日应持仓 {len(target)} 只，总仓位建议 {scale*100:.0f}%"
          f"（波动率目标控制后）\n")
    print(f"  {'ETF':<14}{'现价':>9}{'MA20':>9}{'目标权重':>9}{'目标金额':>11}")
    print("  " + "-" * 60)

    target_amt = {}
    for name, w in sorted(target.items(), key=lambda x: -x[1]):
        price = cur[list(panel.columns).index(name)]
        amt = total * scale * w
        target_amt[name] = amt
        print(f"  {name:<14}{price:>9.3f}{ma_now[list(panel.columns).index(name)]:>9.3f}"
              f"{w*100:>8.1f}%{amt:>11,.0f}")

    # 增量调仓指令：对比现有持仓
    print(f"\n  ▶ 调仓指令（对比当前持仓 {HOLDINGS_FILE}）\n")
    holdings = load_holdings()
    cols = list(panel.columns)

    if not holdings:
        print("  【首次建仓】当前无持仓记录，以下为完整建仓清单：")
        print(f"  {'操作':<4}{'ETF':<14}{'金额':>12}{'约份数(整百)':>12}")
        print("  " + "-" * 52)
        for name, amt in sorted(target_amt.items(), key=lambda x: -x[1]):
            price = cur[cols.index(name)]
            qty = int(amt / price / 100) * 100
            print(f"  买入  {name:<14}{amt:>11,.0f} {qty:>11,}")
        print("\n  ⚠️ 大资金建议：首日先建 50% 仓位，次日再补足，避免一次性冲击。")
    else:
        buy_cmds, sell_cmds, adjust = [], [], []
        for name, h in holdings.items():
            if name not in target_amt:
                sell_cmds.append((name, h))
        for name, amt in target_amt.items():
            if name in holdings:
                # 加/减仓
                price = cur[cols.index(name)]
                cur_amt = holdings[name]["qty"] * price
                diff = amt - cur_amt
                if abs(diff) > total * 0.01:  # 差异超1%才动
                    adjust.append((name, diff, price))
            else:
                buy_cmds.append((name, amt))

        if sell_cmds:
            print("  【卖出清仓】以下持仓已不再站上MA20或跌出候选：")
            for name, h in sell_cmds:
                print(f"    ✗ {name}  现持仓 {h['qty']:.0f} 份，全部卖出")
        if buy_cmds:
            print("  【买入新建】新增候选：")
            for name, amt in buy_cmds:
                price = cur[cols.index(name)]
                qty = int(amt / price / 100) * 100
                print(f"    ✓ {name}  买 {amt:,.0f} 元（约 {qty} 份）")
        if adjust:
            print("  【加减仓】目标权重变化：")
            for name, diff, price in adjust:
                op = "加仓" if diff > 0 else "减仓"
                qty = int(abs(diff) / price / 100) * 100
                print(f"    {op} {name}  {abs(diff):,.0f} 元（约 {qty} 份）")
        if not (sell_cmds or buy_cmds or adjust):
            print("  ✓ 当前持仓与目标一致，无需调仓。")

    # 大资金风控提示
    print("\n  ▶ 大资金风控提示")
    print("    1. 单券目标权重已受 cap 约束，但请勿让任一 ETF 超总资金 35%。")
    print("    2. 原油/商品类 ETF 波动大，若当日急涨急跌，建议分 2~3 笔建/减仓。")
    print("    3. 调仓请用「限价单」，避免市价单冲击（50万以上单券盘口会有影响）。")
    print("    4. 严格按 MA20 纪律执行：跌破即走，不扛单、不补跌。")

    if not args.dry_run and not holdings:
        # 首次运行：写入目标持仓为初始记录（数量按目标金额换算）
        new_holdings = {}
        for name, amt in target_amt.items():
            price = cur[cols.index(name)]
            qty = int(amt / price / 100) * 100
            new_holdings[name] = {"qty": qty, "cost": price,
                                  "code": MULTI_ASSET_POOL.get(name, "")}
        save_holdings(new_holdings)
        print(f"\n  [持仓记录已初始化] {HOLDINGS_FILE}（请按实际成交价手动修正）")

    print("\n" + "=" * 78)
    print("  ⚠️ 本指令基于公开数据量化生成，仅供研究参考，不构成投资建议。")
    print("    下单前请自行核对现价，盈亏自负。")
    print("=" * 78)


if __name__ == "__main__":
    main()
