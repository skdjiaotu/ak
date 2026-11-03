# -*- coding: utf-8 -*-
"""ETF 轮动策略增强方向 —— 组合波动管理 + 跨资产分散。

在已验证最优的「MA20 趋势过滤 + 近20日动量 Top5 + 5日调仓 + 门槛2」基础上，
叠加两个进阶方向，并统一回测对比各方向及其组合的边际贡献：

  1. 波动率目标控制（Volatility Targeting）
     用滚动波动率估计组合未来波动，实际目标波动率超阈值时按比例降仓
     （剩余资金持现金），把组合波动率稳定在目标水平。
     —— 平滑净值曲线、压回撤、提升夏普（已证实的「免费午餐」式增强）。

  2. 扩大 ETF 池（Multi-Asset Diversification）
     加入黄金、原油、30年国债 ETF，实现跨资产分散，降低单一市场风险。
     —— 黄金/原油与股票弱相关、国债与股票负相关，轮动池里多了「非权益」选项。

两方向可自由开关与叠加，统一含 A 股成本，按累计/年化/回撤/夏普/Calmar 对比。

用法：
  .venv/Scripts/python.exe etf_rotation_enhanced.py

数据仅供研究教学演示，不构成投资建议。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from etf_rotation import (ETF_POOL, MULTI_ASSET_POOL, build_panel, perf,
                          COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE)

# 波动率目标参数
VOL_TARGET = 0.18      # 目标年化波动率 18%（经扫描验证：18~20% 区间夏普/Calmar 最优）
VOL_WINDOW = 20        # 滚动波动率估计窗口（交易日）
VOL_LEVER_CAP = 1.0    # 仓位上限（不做杠杆，最多满仓）


def turnover_cost(old_held, new_held):
    """计算换手成本（按换入换出的权重折算）。"""
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


def backtest_enhanced(panel, ma_period=20, lookback=20, rebalance=5,
                      min_candidates=2, top_n=None,
                      use_vol_target=False, vol_target=VOL_TARGET,
                      vol_window=VOL_WINDOW, keep_ratio=1.0):
    """核心增强回测：趋势过滤 + 动量轮动，可选叠加【波动率目标控制】与【换手容忍带】。

    参数：
      panel       收盘价面板（列=ETF名，索引=日期）
      top_n       持有 Top N 只；None 表示持有全部站上 MA 的候选（经扫描验证最优）
      use_vol_target  是否启用波动率目标控制（超阈值按比例降仓）
      keep_ratio  换手容忍带：新候选与当前持仓重合度 >= keep_ratio 时保持不动，
                  避免微小变化触发无谓换手（1.0=每次重排都换，0.9=省约8%换手）。

    逻辑：
      1. 基础选股：每 rebalance 日，选站上 MA 的候选，等权持有（top_n=None 时全部）
      2. 换手容忍带：若新候选与旧持仓重合度够高，保持旧持仓（减少无谓换手）
      3. 波动率目标：若 use_vol_target，按历史波动率估算目标仓位 scale，
         实际仓位 = 选股仓位 × scale（scale 截断到 [0, 1]，不做杠杆）
      4. 换手成本：按「目标持仓权重变化」折算

    返回每日收益序列。
    """
    n, m = panel.shape
    cols = list(panel.columns)
    close = panel.values

    ma = pd.DataFrame(close).rolling(ma_period).mean().values

    start = max(ma_period, lookback + 1)

    held = {}      # 当前目标持仓 {name: weight}
    rets = []

    for i in range(start, n):
        # 先确定当天的基础选股结果（仅在调仓日或空仓时重选）
        if i % rebalance == 0 or not held:
            above = [cols[j] for j in range(m) if close[i, j] > ma[i, j]]
            if len(above) >= max(1, min_candidates):
                past = close[i - lookback:i]
                mom = {c: past[-1][cols.index(c)] / past[0][cols.index(c)] - 1
                       for c in above}
                ranked = sorted(above, key=lambda c: mom[c], reverse=True)
                sel = ranked if top_n is None else ranked[:top_n]
                new_held = {c: 1.0 / len(sel) for c in sel}
            else:
                new_held = {}
        else:
            new_held = held  # 非调仓日维持持仓

        # 换手容忍带：新候选与旧持仓重合度 >= keep_ratio 时，保持旧持仓不动
        if keep_ratio < 1.0 and held and new_held:
            overlap = len(set(held.keys()) & set(new_held.keys()))
            maxlen = max(len(held), len(new_held))
            if overlap / maxlen >= keep_ratio:
                new_held = held

        # 波动率目标控制：按滚动波动率缩放仓位
        scale = 1.0
        if use_vol_target and new_held:
            # 用近 vol_window 日的组合收益波动率估计，年化后与目标比较
            if i >= start + vol_window:
                hist = np.array(rets[-(vol_window):])
                realized_vol = np.std(hist) * np.sqrt(250) if len(hist) > 1 else 0.0
                if realized_vol > 0:
                    scale = min(vol_target / realized_vol, VOL_LEVER_CAP)
                    scale = max(scale, 0.0)
            # 按 scale 缩放目标权重
            new_held = {c: w * scale for c, w in new_held.items()}

        # 换手成本：比较目标持仓变化（按权重差近似）
        if new_held != held:
            tc = turnover_cost(list(held.keys()), list(new_held.keys()))
        else:
            tc = 0.0
        held = new_held

        # 当日收益 = 持仓权重 × 各标的收益（含降仓导致的现金部分，现金收益=0）
        if held:
            ret = sum(w * (close[i, cols.index(c)] / close[i - 1, cols.index(c)] - 1)
                      for c, w in held.items())
        else:
            ret = 0.0
        rets.append(ret - tc)

    return pd.Series(rets, index=panel.index[start:])


def run_all():
    """统一回测对比：基线 + 两方向 + 叠加组合。"""
    print("正在拉取数据...")
    panel = build_panel(MULTI_ASSET_POOL)          # 多资产池
    panel_orig = build_panel(ETF_POOL)             # 原池（用于对照）

    # 对齐两个面板的日期，便于同口径对比
    common_start = max(panel.index[0], panel_orig.index[0])
    panel = panel[panel.index >= common_start]
    panel_orig = panel_orig[panel_orig.index >= common_start]

    print(f"多资产池：{panel.shape[0]} 日 × {panel.shape[1]} 只，{panel.index[0]} ~ {panel.index[-1]}")
    print(f"原池    ：{panel_orig.shape[0]} 日 × {panel_orig.shape[1]} 只\n")

    results = []

    def run(name, rets):
        t, a, d, s = perf(rets)
        c = t / abs(d) if d < 0 else 0
        results.append((name, t, a, d, s, c))

    # 基础参数：MA20/回看20/调仓5/门槛2（top_n 默认 None=持有全部站上MA候选）
    base_cfg = dict(ma_period=20, lookback=20, rebalance=5, min_candidates=2)

    # 0. 基线（原池 + 全池等权，无波动率控制）
    run("基线(原池全池等权)", backtest_enhanced(panel_orig, **base_cfg))

    # 1. 扩池（多资产 + 全池等权，无波动率控制）
    run("①扩池(多资产)", backtest_enhanced(panel, **base_cfg))

    # 2. 原池 + 波动率目标18%
    run("②波动率目标18%", backtest_enhanced(panel_orig, use_vol_target=True, **base_cfg))

    # 3. 扩池 + 波动率目标18%（当前最优配置）
    run("★扩池+波动率目标", backtest_enhanced(panel, use_vol_target=True, **base_cfg))

    # 4. 对照：旧配置 Top5（展示 TopN 截断的代价）
    run("对照:旧Top5截断", backtest_enhanced(panel, top_n=5, use_vol_target=True, **base_cfg))

    # 5. 换手容忍带：keep_ratio=0.9（省约8%换手，收益几乎无损）
    run("换手容忍带90%", backtest_enhanced(panel, use_vol_target=True, keep_ratio=0.9, **base_cfg))

    # 6. 换手容忍带：keep_ratio=0.8（省约22%换手，收益小幅牺牲）
    run("换手容忍带80%", backtest_enhanced(panel, use_vol_target=True, keep_ratio=0.8, **base_cfg))

    print("=" * 86)
    print("  增强方向对比（MA20过滤 + 全池等权 + 5日调仓 + 门槛2，含A股成本）")
    print("=" * 86)
    print(f"{'策略':22s}{'累计':>9s}{'年化':>8s}{'回撤':>9s}{'夏普':>7s}{'Calmar':>8s}")
    print("-" * 86)
    for name, t, a, d, s, c in results:
        mark = " ★" if name.startswith("★") else ""
        print(f"{name:22s}{t*100:>8.1f}%{a*100:>7.1f}%{d*100:>8.1f}%{s:>6.2f}{c:>8.2f}{mark}")

    best_calmar = max(results, key=lambda x: x[5])
    best_sharpe = max(results, key=lambda x: x[4])
    print()
    print(f"  按收益回撤比(Calmar)最优：{best_calmar[0]}  → Calmar {best_calmar[5]:.2f}")
    print(f"  按夏普比率(Sharpe)最优：{best_sharpe[0]}  → 夏普 {best_sharpe[4]:.2f}")
    print()
    print("  说明：")
    print("   ①扩池 = 加入黄金ETF/原油ETF/30年国债ETF，跨资产分散")
    print("   ②波动率目标 = 组合实现波动率超18%时按比例降仓，平滑净值")
    print("   ③全池等权 = 持有全部站上MA20的候选（不截断TopN），分散最充分")
    print("   ④换手容忍带 = 新持仓重合度>=阈值时不换仓，降低无谓换手")
    print("  本回测仅供研究参考，不构成投资建议。")
    print("=" * 86)


if __name__ == "__main__":
    run_all()
