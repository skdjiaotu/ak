# -*- coding: utf-8 -*-
"""样本外验证（时间切割）：前段定参 + 后段验证，排除过拟合。

方法（前向检验 Walk-Forward 的简化版）：
  1. 把数据切成两段：
     - 训练段 train：2019-01 ~ 2023-12（约5年，用于定参数）
     - 验证段 test ：2024-01 ~ 2026-10（约3年，用于验证，参数从未"见过"这段）
  2. 在 train 段做参数网格扫描，找出 train 段最优的 cap / rebalance。
  3. 把 train 段最优参数直接套到 test 段，看：
     - 夏普/收益是否仍然显著为正（真实 alpha）
     - 还是塌方（说明 train 段选出来的只是运气/过拟合）
  4. 同时对比「全样本最优参数」与「train 段最优参数」是否一致：
     - 若一致 → 参数稳健
     - 若漂移 → 存在过拟合风险

复用 analyze_final_stack 的扩池+波动率+cap倾斜框架，成本口径一致。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation import MULTI_ASSET_POOL, build_panel, perf, \
    COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE

VOL_TARGET = 0.18
VOL_WINDOW = 20
VOL_LEVER_CAP = 1.0

TRAIN_END = "2023-12-31"
TEST_START = "2024-01-01"


def turnover_cost(old_held, new_held):
    if new_held == old_held:
        return 0.0
    sell_names = [c for c in old_held if c not in new_held]
    buy_names = [c for c in new_held if c not in old_held]
    cost = 0.0
    if sell_names:
        sell_w = len(sell_names) / len(old_held) if old_held else 0.0
        cost += sell_w * (COMMISSION + STAMP_TAX + TRANSFER_FEE + SLIPPAGE)
    if buy_names:
        buy_w = len(buy_names) / len(new_held) if new_held else 0.0
        cost += buy_w * (COMMISSION + TRANSFER_FEE + SLIPPAGE)
    return cost


def tilt_weights(sel, close_i, ma_i, cols, cap):
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


def backtest(panel, ma_period=20, lookback=20, rebalance=5, min_candidates=2,
             use_vol_target=True, tilt_cap=None):
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values
    ma = pd.DataFrame(close).rolling(ma_period).mean().values
    start = max(ma_period, lookback + 1)

    held = {}
    rets = []

    for i in range(start, n):
        if i % rebalance == 0 or not held:
            above = [cols[j] for j in range(m) if close[i, j] > ma[i, j]]
            if len(above) >= max(1, min_candidates):
                past = close[i - lookback:i]
                mom = {c: past[-1][cols.index(c)] / past[0][cols.index(c)] - 1
                       for c in above}
                ranked = sorted(above, key=lambda c: mom[c], reverse=True)
                sel = ranked  # 全池（top_n=None，与最优配置一致）
                if tilt_cap is None:
                    new_held = {c: 1.0 / len(sel) for c in sel}
                else:
                    new_held = tilt_weights(sel, close[i], ma[i], cols, tilt_cap)
            else:
                new_held = {}
        else:
            new_held = held

        scale = 1.0
        if use_vol_target and new_held:
            if i >= start + VOL_WINDOW:
                hist = np.array(rets[-(VOL_WINDOW):])
                realized_vol = np.std(hist) * np.sqrt(250) if len(hist) > 1 else 0.0
                if realized_vol > 0:
                    scale = min(VOL_TARGET / realized_vol, VOL_LEVER_CAP)
                    scale = max(scale, 0.0)
            new_held = {c: w * scale for c, w in new_held.items()}

        tc = turnover_cost(list(held.keys()), list(new_held.keys())) \
            if new_held != held else 0.0
        held = new_held

        if held:
            ret = sum(w * (close[i, cols.index(c)] / close[i - 1, cols.index(c)] - 1)
                      for c, w in held.items())
        else:
            ret = 0.0
        rets.append(ret - tc)

    return pd.Series(rets, index=panel.index[start:])


def metrics(rets):
    t, a, d, s = perf(rets)
    calmar = t / abs(d) if d < 0 else 0
    vol = rets.std() * np.sqrt(250)
    return dict(ret=t, ann=a, dd=d, sharpe=s, calmar=calmar, vol=vol)


def grid_on(panel, caps, rebalances):
    """在给定面板上扫描 cap × rebalance，返回结果表。"""
    out = {}
    for cap in caps:
        for rb in rebalances:
            rets = backtest(panel, rebalance=rb, tilt_cap=cap)
            out[(cap, rb)] = metrics(rets)
    return out


def main():
    print("拉取数据...")
    full = build_panel(MULTI_ASSET_POOL)
    train = full[full.index <= TRAIN_END]
    test = full[full.index >= TEST_START]
    print(f"全样本：{full.shape[0]} 日（{full.index[0]} ~ {full.index[-1]}）")
    print(f"训练段：{train.shape[0]} 日（{train.index[0]} ~ {train.index[-1]}）")
    print(f"验证段：{test.shape[0]} 日（{test.index[0]} ~ {test.index[-1]}）\n")

    caps = [None, 0.3, 0.4, 0.5]
    rebalances = [3, 5, 10]

    # ---------- 训练段定参 ----------
    print("=" * 82)
    print("  STEP 1：训练段(2019-2023) 参数网格扫描 —— 定参数")
    print("=" * 82)
    tr = grid_on(train, caps, rebalances)
    print(f"{'cap':>6s}{'调仓':>5s}{'累计':>9s}{'夏普':>7s}{'回撤':>8s}{'Calmar':>8s}")
    for (cap, rb), m in tr.items():
        cap_s = "等权" if cap is None else f"{cap}"
        print(f"{cap_s:>6s}{rb:>5d}{m['ret']*100:>8.1f}%{m['sharpe']:>7.2f}"
              f"{m['dd']*100:>7.1f}%{m['calmar']:>8.1f}")

    best_train = max(tr.items(), key=lambda kv: kv[1]["sharpe"])
    (bc, brb), bm = best_train
    bc_s = "等权" if bc is None else f"cap={bc}"
    print(f"\n  → 训练段最优（按夏普）：{bc_s} + 调仓{brb}  "
          f"夏普 {bm['sharpe']:.2f}，收益 {bm['ret']*100:.1f}%")

    # 全样本最优，用于对照
    full_g = grid_on(full, caps, rebalances)
    best_full = max(full_g.items(), key=lambda kv: kv[1]["sharpe"])
    (fc, frb), fm = best_full
    fc_s = "等权" if fc is None else f"cap={fc}"
    print(f"  → 全样本最优（按夏普）：{fc_s} + 调仓{frb}  "
          f"夏普 {fm['sharpe']:.2f}，收益 {fm['ret']*100:.1f}%")

    # ---------- 验证段套用 ----------
    print("\n" + "=" * 82)
    print("  STEP 2：验证段(2024-2026) 套用训练段最优参数 —— 检验是否塌方")
    print("=" * 82)
    print(f"{'参数来源':18s}{'累计':>9s}{'夏普':>7s}{'回撤':>8s}{'年化':>8s}{'Calmar':>8s}")
    print("-" * 82)

    # 1) 训练段最优参数 → 套到验证段
    rets_test = backtest(test, rebalance=brb, tilt_cap=bc)
    mt = metrics(rets_test)
    print(f"{bc_s+' 调仓'+str(brb):18s}{mt['ret']*100:>8.1f}%{mt['sharpe']:>7.2f}"
          f"{mt['dd']*100:>7.1f}%{mt['ann']*100:>7.1f}%{mt['calmar']:>8.1f}")

    # 2) 全样本最优参数 → 套到验证段（对照，看是否因"偷看"未来而虚高）
    rets_test2 = backtest(test, rebalance=frb, tilt_cap=fc)
    mf = metrics(rets_test2)
    print(f"{fc_s+' 调仓'+str(frb):18s}{mf['ret']*100:>8.1f}%{mf['sharpe']:>7.2f}"
          f"{mf['dd']*100:>7.1f}%{mf['ann']*100:>7.1f}%{mf['calmar']:>8.1f}")

    # 3) 等权基准（无倾斜）→ 套到验证段，作为"有没有alpha"的基准
    rets_eq = backtest(test, rebalance=5, tilt_cap=None)
    me = metrics(rets_eq)
    print(f"{'等权 调仓5(基准)':18s}{me['ret']*100:>8.1f}%{me['sharpe']:>7.2f}"
          f"{me['dd']*100:>7.1f}%{me['ann']*100:>7.1f}%{me['calmar']:>8.1f}")

    # 4) 验证段"自身最优"参数（理论天花板，用于对照过拟合程度）
    test_g = grid_on(test, caps, rebalances)
    best_test = max(test_g.items(), key=lambda kv: kv[1]["sharpe"])
    (tc2, trb2), tm2 = best_test
    tc2_s = "等权" if tc2 is None else f"cap={tc2}"
    print(f"{tc2_s+' 调仓'+str(trb2):18s}{tm2['ret']*100:>8.1f}%{tm2['sharpe']:>7.2f}"
          f"{tm2['dd']*100:>7.1f}%{tm2['ann']*100:>7.1f}%{tm2['calmar']:>8.1f}")

    # ---------- 结论 ----------
    print("\n" + "=" * 82)
    print("  判读")
    print("=" * 82)
    print(f"  1. 训练段最优参数：{bc_s} + 调仓{brb}")
    print(f"     验证段表现：夏普 {mt['sharpe']:.2f}，收益 {mt['ret']*100:.1f}%，"
          f"回撤 {mt['dd']*100:.1f}%")
    print(f"  2. 等权基准在验证段：夏普 {me['sharpe']:.2f}，收益 {me['ret']*100:.1f}%")
    if mt["sharpe"] > me["sharpe"]:
        print(f"     → 训练段选出的倾斜参数在验证段仍跑赢等权（夏普 {mt['sharpe']:.2f} > {me['sharpe']:.2f}），")
        print(f"       说明「趋势强度倾斜」的 alpha 在样本外依然成立，不是过拟合。")
    else:
        print(f"     → 训练段选出的倾斜参数在验证段跑输等权，说明存在过拟合风险。")
    print(f"  3. 训练段最优 vs 全样本最优：{bc_s}+调仓{brb} vs {fc_s}+调仓{frb}")
    if (bc, brb) == (fc, frb):
        print("     → 两者一致，参数稳健，无漂移。")
    else:
        print("     → 参数有漂移，最优参数对样本区间敏感（需谨慎）。")
    print(f"  4. 验证段自身最优（天花板）：夏普 {tm2['sharpe']:.2f}，"
          f"训练段参数的验证夏普 {mt['sharpe']:.2f} 是其 {mt['sharpe']/tm2['sharpe']*100:.0f}%，")
    print("     越接近 100% 说明训练段选的参数越接近真实最优，过拟合越轻。")
    print("\n  本分析仅供研究参考，不构成投资建议。")
    print("=" * 82)


if __name__ == "__main__":
    main()
