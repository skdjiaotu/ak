# -*- coding: utf-8 -*-
"""
小市值/流动性溢价验证框架（中证500，无前视口径）

核心思想：
  A股经典异象——小市值/低流动性股票长期跑赢大市值/高流动性股票。
  本框架用「成交额(amount)」作为流动性/市值的代理，在中证500成分内分层验证。

数据：
  - 成分股：index_stock_cons_sina('000905') → 500只，含实时成交额 amount
  - 历史行情：stock_zh_a_hist_tx（腾讯，前复权，稳定）

无前视口径（从第一行做对）：
  - 每月末，用「截至月末」的成交额/价格对股票分组
  - 下月首个交易日按分组建仓，吃下月真实收益
  - 绝不用当日数据决定当日持仓

验证：
  1. 分组回测：按成交额分成5组(1=最小成交额/冷门小票 ... 5=最大成交额/热门)
     看是否单调（组1 > 组2 > ... > 组5）——单调性 = 真溢价，非运气
  2. 多空组合：做多最小成交额组、做空最大成交额组，看纯因子收益
  3. 对比基准：中证500等权
"""
from __future__ import annotations

import os
import time
import numpy as np
import pandas as pd
import akshare as ak

from stock_factor_backtest import perf, COMMISSION, STAMP_TAX, TRANSFER_FEE, SLIPPAGE

CACHE_DIR = "../stock/cache"
PRICE_CACHE = os.path.join(CACHE_DIR, "zz500_price.csv")
CONS_CACHE = os.path.join(CACHE_DIR, "zz500_cons.csv")


def get_zz500_cons() -> pd.DataFrame:
    """获取中证500成分股（含实时成交额）。"""
    if os.path.exists(CONS_CACHE):
        return pd.read_csv(CONS_CACHE, dtype={"code": str})
    df = ak.index_stock_cons_sina(symbol="000905")
    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df[["symbol", "name", "amount", "code"]].copy()
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    df.to_csv(CONS_CACHE, index=False)
    return df


def build_price_panel(codes: list, cache_path: str = PRICE_CACHE) -> pd.DataFrame:
    """用腾讯接口拉中证500成分股历史行情（前复权），带缓存。"""
    if os.path.exists(cache_path):
        return pd.read_csv(cache_path, index_col=0, parse_dates=True)

    closes = {}
    total = len(codes)
    for i, code in enumerate(codes):
        # 腾讯接口 symbol 需带交易所前缀
        sym = code
        if code.startswith(("6", "5", "9")):
            sym = "sh" + code
        elif code.startswith(("0", "1", "2", "3")):
            sym = "sz" + code
        try:
            df = ak.stock_zh_a_hist_tx(symbol=sym, start_date="20180101", end_date="20261030")
            if len(df):
                df = df.sort_values("date")
                closes[code] = df.set_index("date")["close"]
        except Exception as e:
            print(f"  [跳过] {code}: {str(e)[:50]}")
        if (i + 1) % 50 == 0:
            print(f"  已拉 {i+1}/{total} 只")
        time.sleep(0.3)

    panel = pd.DataFrame(closes).sort_index()
    os.makedirs(CACHE_DIR, exist_ok=True)
    panel.to_csv(cache_path)
    return panel


def group_backtest(panel, amounts, n_groups=5, top_each=None):
    """分组回测：按成交额分成 n_groups 组，各自等权持有，月度调仓。

    amounts: dict {code: 成交额}（实时快照，作为流动性分组的截面）
    返回 dict {group_idx: 收益序列}
    """
    # 排序：成交额从小到大
    codes_with_amount = [(c, amounts.get(c, np.inf)) for c in panel.columns]
    codes_with_amount.sort(key=lambda x: x[1])  # 小成交额在前

    # 分组（每组等数量）
    valid_codes = [c for c, a in codes_with_amount if a < np.inf and not np.isnan(a)]
    k = len(valid_codes)
    per = k // n_groups

    groups = {}
    for g in range(n_groups):
        start = g * per
        end = (g + 1) * per if g < n_groups - 1 else k
        groups[g] = valid_codes[start:end]

    # 月度调仓，无前视
    n, m = panel.shape
    close = panel.values
    idx = panel.index

    month_key = pd.Series([(d.year, d.month) for d in idx])
    is_month_end = month_key != month_key.shift(-1)
    month_end_positions = np.where(is_month_end.values)[0]

    result = {g: [] for g in range(n_groups)}
    result_idx = []

    for k_pos, pos in enumerate(month_end_positions):
        next_pos = month_end_positions[k_pos + 1] if k_pos + 1 < len(month_end_positions) else n - 1
        hold_start = pos + 1
        if hold_start > next_pos:
            continue
        for i in range(hold_start, next_pos + 1):
            if i <= 0:
                continue
            result_idx.append(idx[i])
            for g in range(n_groups):
                grp = groups[g]
                valid = [c for c in grp if c in panel.columns]
                if valid:
                    r = np.mean([close[i, list(panel.columns).index(c)] /
                                 close[i - 1, list(panel.columns).index(c)] - 1
                                 for c in valid])
                else:
                    r = 0.0
                result[g].append(r)

    return {g: pd.Series(v, index=result_idx) for g, v in result.items()}, groups


def show(name, rets):
    t, a, d, s = perf(rets)
    print(f"{name:32s} 累计={t*100:7.1f}%  年化={a*100:5.1f}%  "
          f"回撤={d*100:6.1f}%  夏普={s:.2f}")


def main():
    print("[1/3] 获取中证500成分股...")
    cons = get_zz500_cons()
    codes = list(cons["code"])
    print(f"  成分股 {len(codes)} 只，成交额中位数 "
          f"{cons['amount'].median()/1e8:.2f} 亿")

    print("[2/3] 拉取历史行情（腾讯前复权，缓存）...")
    panel = build_price_panel(codes)
    print(f"  价格面板: {panel.shape[0]} 日 × {panel.shape[1]} 只, "
          f"{panel.index[0].date()} ~ {panel.index[-1].date()}")

    # 成交额映射（实时快照作为截面分组依据）
    amounts = dict(zip(cons["code"], cons["amount"]))

    print("[3/3] 分组回测（按成交额分5组，月度调仓，无前视）...")
    grp_rets, groups = group_backtest(panel, amounts, n_groups=5)

    print()
    print("=" * 82)
    print("  中证500 流动性/小市值溢价分组回测（无前视口径）")
    print("=" * 82)
    labels = ["1(最小成交额/冷门)", "2", "3(中)", "4", "5(最大成交额/热门)"]
    for g in range(5):
        show(f"组{g+1} {labels[g]}", grp_rets[g])

    # 基准：中证500等权
    bench = panel.pct_change().mean(axis=1).dropna()
    show("基准(中证500等权)", bench)

    # 多空：做多组1 - 做空组5
    long_short = grp_rets[0] - grp_rets[4]
    show("多空(组1 - 组5)", long_short)

    print()
    print("  各组成交额区间(亿):")
    for g in range(5):
        grp_amounts = [amounts.get(c, 0) for c in groups[g] if c in amounts]
        if grp_amounts:
            print(f"    组{g+1}: {min(grp_amounts)/1e8:.2f} ~ {max(grp_amounts)/1e8:.2f} 亿 "
                  f"({len(grp_amounts)}只)")


if __name__ == "__main__":
    main()
